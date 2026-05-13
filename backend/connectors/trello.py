"""
Trello connector – syncs workspaces (organizations), boards, and cards.

Maps to tracker_teams / tracker_projects / tracker_issues (same tier as Asana/Jira).

OAuth via Nango (Trello). REST calls use api key + token query parameters.

API docs: https://developer.atlassian.com/cloud/trello/rest/
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import settings
from connectors.base import BaseConnector
from connectors.registry import (
    AuthType,
    Capability,
    ConnectorMeta,
    ConnectorScope,
    EventType,
    WriteOperation,
)
from models.database import get_session
from models.integration import Integration
from models.tracker_issue import TrackerIssue
from models.tracker_project import TrackerProject
from models.tracker_team import TrackerTeam

logger = logging.getLogger(__name__)

TRELLO_API_BASE: str = "https://api.trello.com/1"
TRELLO_CARD_DONE_EVENT: str = "trello.card.done"
TRELLO_CARD_UPDATED_EVENT: str = "trello.card.updated"

# Label text -> (priority int, priority_label) — align with other trackers
_LABEL_PRIORITY_MAP: dict[str, tuple[int, str]] = {
    "p0": (1, "P0"),
    "p1": (2, "P1"),
    "urgent": (1, "Urgent"),
    "high": (2, "High"),
    "medium": (3, "Medium"),
    "low": (4, "Low"),
}


class TrelloConnector(BaseConnector):
    """Connector for Trello boards, lists, and cards."""

    source_system: str = "trello"
    meta = ConnectorMeta(
        name="Trello",
        slug="trello",
        auth_type=AuthType.OAUTH2,
        scope=ConnectorScope.USER,
        entity_types=["teams", "projects", "issues"],
        capabilities=[Capability.SYNC, Capability.WRITE, Capability.LISTEN],
        nango_integration_id="trello",
        description="Trello – boards, lists, and cards",
        icon="trello",
        webhook_secret_extra_data_key="trello_api_secret",
        write_operations=[
            WriteOperation(
                name="create_issue",
                entity_type="issue",
                description="Create a Trello card on a list",
                parameters=[
                    {
                        "name": "board_name",
                        "type": "string",
                        "required": False,
                        "description": "Board name (if board_id not set)",
                    },
                    {
                        "name": "board_id",
                        "type": "string",
                        "required": False,
                        "description": "Trello board id",
                    },
                    {
                        "name": "list_name",
                        "type": "string",
                        "required": True,
                        "description": "List/column name",
                    },
                    {"name": "title", "type": "string", "required": True, "description": "Card title"},
                    {
                        "name": "description",
                        "type": "string",
                        "required": False,
                        "description": "Card description",
                    },
                    {
                        "name": "due_date",
                        "type": "string",
                        "required": False,
                        "description": "Due date YYYY-MM-DD",
                    },
                    {
                        "name": "assignee_name",
                        "type": "string",
                        "required": False,
                        "description": "Assignee full name",
                    },
                    {
                        "name": "labels",
                        "type": "array",
                        "required": False,
                        "description": "Label names to add",
                    },
                ],
            ),
            WriteOperation(
                name="update_issue",
                entity_type="issue",
                description="Update or move a Trello card",
                parameters=[
                    {
                        "name": "issue_identifier",
                        "type": "string",
                        "required": True,
                        "description": "Card id or shortLink",
                    },
                    {"name": "title", "type": "string", "required": False, "description": "New title"},
                    {
                        "name": "description",
                        "type": "string",
                        "required": False,
                        "description": "New description",
                    },
                    {
                        "name": "state_name",
                        "type": "string",
                        "required": False,
                        "description": "Target list name (moves card)",
                    },
                    {
                        "name": "due_date",
                        "type": "string",
                        "required": False,
                        "description": "Due date YYYY-MM-DD or empty to clear",
                    },
                    {
                        "name": "assignee_name",
                        "type": "string",
                        "required": False,
                        "description": "Assignee full name",
                    },
                ],
            ),
        ],
        event_types=[
            EventType(name=TRELLO_CARD_UPDATED_EVENT, description="Trello card changed"),
            EventType(name=TRELLO_CARD_DONE_EVENT, description="Card moved to a Done-style list"),
        ],
    )

    def __init__(
        self,
        organization_id: str,
        user_id: Optional[str] = None,
        *,
        sync_since_override: datetime | None = None,
        integration_id: str | None = None,
        account_identifier: str | None = None,
    ) -> None:
        super().__init__(
            organization_id,
            user_id,
            sync_since_override=sync_since_override,
            integration_id=integration_id,
            account_identifier=account_identifier,
        )
        self._member_me_id: Optional[str] = None

    # ── Auth: Trello requires key + token on every request ───────────────

    async def _auth_params(self) -> dict[str, str]:
        token, _ = await self.get_oauth_token()
        creds: dict[str, Any] = await self.get_credentials()
        raw: dict[str, Any] = creds.get("raw") if isinstance(creds.get("raw"), dict) else {}
        api_key: str | None = (
            _str_or_none(creds.get("oauth_client_id"))
            or _str_or_none(raw.get("oauth_client_id"))
            or _str_or_none(raw.get("oauth_consumer_key"))
            or _str_or_none(raw.get("consumer_key"))
            or _str_or_none(creds.get("client_id"))
            or _str_or_none(creds.get("api_key"))
        )
        extra: dict[str, Any] = {}
        if self._integration:
            extra = self._integration.extra_data or {}
        if not api_key:
            api_key = _str_or_none(extra.get("trello_api_key"))
        if not api_key:
            api_key = _str_or_none(settings.TRELLO_API_KEY)
        if not api_key:
            raise ValueError(
                "Missing Trello API key. Set TRELLO_API_KEY in the backend env (same Power-Up / "
                "OAuth client id as in Nango), or put it in integration.extra_data['trello_api_key']."
            )
        return {"key": api_key, "token": token}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        auth: dict[str, str] = await self._auth_params()
        query: dict[str, Any] = dict(params or {})
        query.update(auth)
        url: str = f"{TRELLO_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp: httpx.Response = await client.request(
                method,
                url,
                params=query,
                json=json_body,
            )
            resp.raise_for_status()
            if resp.status_code == 204 or not resp.content:
                return None
            ctype: str = resp.headers.get("content-type", "")
            if "application/json" in ctype:
                return resp.json()
            return resp.text

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("POST", path, params=params, json_body=json_body)

    async def _put(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("PUT", path, params=params, json_body=json_body)

    async def _delete(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("DELETE", path, params=params)

    async def _get_integration_row(self) -> Integration:
        if self._integration:
            return self._integration
        await self.get_oauth_token()
        assert self._integration is not None
        return self._integration

    # ── Sync: teams (Trello organizations + personal bucket) ─────────────

    async def sync_teams(self) -> int:
        """Upsert Trello organizations and a personal workspace bucket into tracker_teams."""
        org_uuid: UUID = UUID(self.organization_id)
        integration = await self._get_integration_row()
        integration_id: UUID = integration.id

        me: Any = await self._get("/members/me", {"fields": "id,fullName"})
        if not isinstance(me, dict):
            raise RuntimeError("Unexpected Trello /members/me response")
        self._member_me_id = str(me.get("id", ""))

        orgs_raw: Any = await self._get(
            f"/members/{self._member_me_id}/organizations",
            {"fields": "id,displayName,desc"},
        )
        organizations: list[dict[str, Any]] = orgs_raw if isinstance(orgs_raw, list) else []

        count: int = 0
        async with get_session(organization_id=self.organization_id) as session:
            for org in organizations:
                oid: str | None = _str_or_none(org.get("id"))
                if not oid:
                    continue
                stmt = pg_insert(TrackerTeam).values(
                    organization_id=org_uuid,
                    integration_id=integration_id,
                    source_system=self.source_system,
                    source_id=oid,
                    name=str(org.get("displayName") or "Workspace"),
                    key=None,
                    description=_str_or_none(org.get("desc")),
                ).on_conflict_do_update(
                    index_elements=["organization_id", "source_system", "source_id"],
                    set_={
                        "name": str(org.get("displayName") or "Workspace"),
                        "description": _str_or_none(org.get("desc")),
                        "updated_at": datetime.utcnow(),
                    },
                )
                await session.execute(stmt)
                count += 1

            personal_source: str = f"personal:{self._member_me_id}"
            personal_name: str = (
                f"{me.get('fullName') or 'Me'}'s boards"
                if me.get("fullName")
                else "Personal boards"
            )
            stmt_p = pg_insert(TrackerTeam).values(
                organization_id=org_uuid,
                integration_id=integration_id,
                source_system=self.source_system,
                source_id=personal_source,
                name=personal_name,
                key=None,
                description=None,
            ).on_conflict_do_update(
                index_elements=["organization_id", "source_system", "source_id"],
                set_={
                    "name": personal_name,
                    "updated_at": datetime.utcnow(),
                },
            )
            await session.execute(stmt_p)
            count += 1
            await session.commit()

        logger.info("Synced %d Trello teams for org %s", count, self.organization_id)
        return count

    # ── Sync: projects (boards) ───────────────────────────────────────────

    async def sync_projects(self) -> int:
        """Upsert open boards as tracker_projects."""
        org_uuid: UUID = UUID(self.organization_id)
        if not self._member_me_id:
            await self.sync_teams()

        boards_raw: Any = await self._get(
            f"/members/{self._member_me_id}/boards",
            {
                "filter": "open",
                "fields": "id,name,desc,url,closed,idOrganization",
            },
        )
        boards: list[dict[str, Any]] = boards_raw if isinstance(boards_raw, list) else []

        count: int = 0
        async with get_session(organization_id=self.organization_id) as session:
            for b in boards:
                if b.get("closed"):
                    continue
                bid: str | None = _str_or_none(b.get("id"))
                if not bid:
                    continue
                id_org: str | None = _str_or_none(b.get("idOrganization"))
                team_key: str = (
                    id_org if id_org else f"personal:{self._member_me_id}"
                )
                team_ids: list[str] = [team_key]

                stmt = pg_insert(TrackerProject).values(
                    organization_id=org_uuid,
                    source_system=self.source_system,
                    source_id=bid,
                    name=str(b.get("name") or ""),
                    description=_truncate_text(_str_or_none(b.get("desc")), 5000),
                    state="active",
                    progress=None,
                    target_date=None,
                    start_date=None,
                    url=str(b.get("url") or ""),
                    lead_name=None,
                    team_ids=team_ids,
                ).on_conflict_do_update(
                    index_elements=["organization_id", "source_system", "source_id"],
                    set_={
                        "name": str(b.get("name") or ""),
                        "description": _truncate_text(_str_or_none(b.get("desc")), 5000),
                        "state": "active",
                        "url": str(b.get("url") or ""),
                        "team_ids": team_ids,
                        "updated_at": datetime.utcnow(),
                    },
                )
                await session.execute(stmt)
                count += 1
            await session.commit()

        logger.info("Synced %d Trello boards for org %s", count, self.organization_id)
        return count

    # ── Sync: issues (cards) ─────────────────────────────────────────────

    async def sync_issues(self) -> int:
        """Fetch cards per board and upsert tracker_issues."""
        org_uuid: UUID = UUID(self.organization_id)
        if not self._member_me_id:
            await self.sync_teams()

        team_map: dict[str, UUID] = {}
        project_map: dict[str, UUID] = {}
        project_team_key: dict[str, str] = {}

        async with get_session(organization_id=self.organization_id) as session:
            res = await session.execute(
                select(TrackerTeam.source_id, TrackerTeam.id).where(
                    TrackerTeam.organization_id == org_uuid,
                    TrackerTeam.source_system == self.source_system,
                )
            )
            for sid, tid in res.all():
                team_map[str(sid)] = tid

            res2 = await session.execute(
                select(
                    TrackerProject.source_id,
                    TrackerProject.id,
                    TrackerProject.team_ids,
                ).where(
                    TrackerProject.organization_id == org_uuid,
                    TrackerProject.source_system == self.source_system,
                )
            )
            for psid, pid, tids in res2.all():
                project_map[str(psid)] = pid
                lst: list[str] = tids or []
                project_team_key[str(psid)] = lst[0] if lst else f"personal:{self._member_me_id}"

        boards_raw: Any = await self._get(
            f"/members/{self._member_me_id}/boards",
            {"filter": "open", "fields": "id,name"},
        )
        boards: list[dict[str, Any]] = boards_raw if isinstance(boards_raw, list) else []

        count: int = 0
        since_param: str | None = None
        if self.sync_since:
            since_param = self.sync_since.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        async with get_session(organization_id=self.organization_id) as session:
            for b in boards:
                bid: str | None = _str_or_none(b.get("id"))
                if not bid or bid not in project_map:
                    continue
                internal_project_id: UUID = project_map[bid]
                team_key: str = project_team_key.get(bid, f"personal:{self._member_me_id}")
                internal_team_id: UUID | None = team_map.get(team_key)
                if not internal_team_id and team_map:
                    internal_team_id = next(iter(team_map.values()))
                if not internal_team_id:
                    continue

                lists_raw: Any = await self._get(
                    f"/boards/{bid}/lists",
                    {"filter": "open", "fields": "id,name"},
                )
                list_items: list[dict[str, Any]] = (
                    lists_raw if isinstance(lists_raw, list) else []
                )
                list_name_by_id: dict[str, str] = {
                    str(x["id"]): str(x.get("name") or "")
                    for x in list_items
                    if x.get("id")
                }

                members_raw: Any = await self._get(
                    f"/boards/{bid}/members",
                    {"fields": "id,fullName,username"},
                )
                members: list[dict[str, Any]] = (
                    members_raw if isinstance(members_raw, list) else []
                )
                member_name: dict[str, str] = {
                    str(m["id"]): str(m.get("fullName") or m.get("username") or "")
                    for m in members
                    if m.get("id")
                }

                card_params: dict[str, Any] = {
                    "fields": (
                        "id,shortLink,idShort,name,desc,closed,dateLastActivity,"
                        "idList,idBoard,idMembers,labels,due,dueComplete,url"
                    ),
                }
                if since_param:
                    card_params["since"] = since_param

                cards_raw: Any = await self._get(
                    f"/boards/{bid}/cards",
                    dict(card_params, filter="open"),
                )
                cards: list[dict[str, Any]] = (
                    cards_raw if isinstance(cards_raw, list) else []
                )

                for card in cards:
                    if card.get("closed"):
                        continue
                    cid: str | None = _str_or_none(card.get("id"))
                    if not cid:
                        continue
                    id_list: str | None = _str_or_none(card.get("idList"))
                    state_name: str | None = (
                        list_name_by_id.get(id_list) if id_list else None
                    )
                    state_type: str = _resolve_state_type(
                        bool(card.get("dueComplete")), state_name
                    )
                    labels: list[str] = [
                        str(lb.get("name"))
                        for lb in (card.get("labels") or [])
                        if isinstance(lb, dict) and lb.get("name")
                    ]
                    priority, priority_label = _priority_from_labels(labels)

                    assignee_name: str | None = None
                    id_members: list[Any] = card.get("idMembers") or []
                    if id_members:
                        mid0: str = str(id_members[0])
                        assignee_name = member_name.get(mid0) or None

                    short_link: str = str(card.get("shortLink") or cid[-8:])
                    identifier: str = f"TRELLO-{short_link}"[:30]

                    created_dt: datetime = _trello_id_to_datetime(cid)
                    updated_dt: datetime | None = _parse_dt_optional(
                        card.get("dateLastActivity")
                    )
                    completed_dt: datetime | None = None
                    if card.get("dueComplete"):
                        completed_dt = updated_dt or datetime.utcnow()

                    stmt = pg_insert(TrackerIssue).values(
                        organization_id=org_uuid,
                        team_id=internal_team_id,
                        source_system=self.source_system,
                        source_id=cid,
                        identifier=identifier,
                        title=str(card.get("name") or ""),
                        description=_truncate_text(_str_or_none(card.get("desc")), 5000),
                        state_name=state_name,
                        state_type=state_type,
                        priority=priority,
                        priority_label=priority_label,
                        assignee_name=assignee_name,
                        assignee_email=None,
                        creator_name=None,
                        project_id=internal_project_id,
                        labels=labels or None,
                        estimate=None,
                        url=str(card.get("url") or ""),
                        due_date=_parse_date_only(card.get("due")),
                        created_date=created_dt,
                        updated_date=updated_dt,
                        completed_date=completed_dt,
                        cancelled_date=None,
                    ).on_conflict_do_update(
                        index_elements=[
                            "organization_id",
                            "source_system",
                            "source_id",
                        ],
                        set_={
                            "team_id": internal_team_id,
                            "identifier": identifier,
                            "title": str(card.get("name") or ""),
                            "description": _truncate_text(
                                _str_or_none(card.get("desc")), 5000
                            ),
                            "state_name": state_name,
                            "state_type": state_type,
                            "priority": priority,
                            "priority_label": priority_label,
                            "assignee_name": assignee_name,
                            "project_id": internal_project_id,
                            "labels": labels or None,
                            "url": str(card.get("url") or ""),
                            "due_date": _parse_date_only(card.get("due")),
                            "updated_date": updated_dt,
                            "completed_date": completed_dt,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                    await session.execute(stmt)
                    count += 1

            await session.commit()

        logger.info("Synced %d Trello cards for org %s", count, self.organization_id)
        return count

    async def sync_all(self) -> dict[str, int]:
        await self.ensure_sync_active("sync_all:start")
        teams_count: int = await self.sync_teams()
        await self.ensure_sync_active("sync_all:after_teams")
        projects_count: int = await self.sync_projects()
        await self.ensure_sync_active("sync_all:after_projects")
        issues_count: int = await self.sync_issues()
        await self.ensure_sync_active("sync_all:after_issues")
        await self._register_webhooks_for_boards()
        return {
            "teams": teams_count,
            "projects": projects_count,
            "issues": issues_count,
        }

    async def _register_webhooks_for_boards(self) -> None:
        """Create Trello webhooks per open board when public URL and API secret exist."""
        base: str | None = settings.BACKEND_PUBLIC_URL
        if not base or not base.strip():
            logger.debug("[trello] BACKEND_PUBLIC_URL unset; skipping webhook registration")
            return
        integration = await self._get_integration_row()
        extra: dict[str, Any] = integration.extra_data or {}
        api_secret: str | None = _str_or_none(extra.get("trello_api_secret"))
        if not api_secret:
            logger.info(
                "[trello] trello_api_secret not in extra_data; skipping webhook registration"
            )
            return

        callback: str = f"{base.rstrip('/')}/api/connectors/webhook/trello/{self.organization_id}"

        boards_raw: Any = await self._get(
            f"/members/{self._member_me_id}/boards",
            {"filter": "open", "fields": "id"},
        )
        boards: list[dict[str, Any]] = boards_raw if isinstance(boards_raw, list) else []
        board_ids: list[str] = [
            str(b["id"]) for b in boards if b.get("id")
        ]

        auth_params: dict[str, str] = await self._auth_params()
        token: str = auth_params["token"]
        try:
            existing: Any = await self._get(f"/tokens/{token}/webhooks", {})
        except Exception as exc:
            logger.warning("[trello] Could not list webhooks: %s", exc)
            existing = []

        hook_list: list[dict[str, Any]] = existing if isinstance(existing, list) else []
        for h in hook_list:
            cb: str | None = _str_or_none(h.get("callbackURL"))
            hid: str | None = _str_or_none(h.get("id"))
            if cb and hid and callback in cb:
                try:
                    await self._delete(f"/webhooks/{hid}")
                except Exception as exc:
                    logger.warning("[trello] Failed to delete webhook %s: %s", hid, exc)

        registered: list[dict[str, str]] = []
        for bid in board_ids:
            try:
                created: Any = await self._post(
                    "/webhooks",
                    params={
                        "callbackURL": callback,
                        "idModel": bid,
                        "description": "basebase",
                    },
                )
                if isinstance(created, dict) and created.get("id"):
                    registered.append({"board_id": bid, "webhook_id": str(created["id"])})
            except Exception as exc:
                logger.warning("[trello] Webhook create failed for board %s: %s", bid, exc)

        if registered:
            from sqlalchemy.orm.attributes import flag_modified

            new_extra: dict[str, Any] = dict(extra)
            new_extra["webhook_ids"] = registered
            async with get_session(organization_id=self.organization_id) as session:
                row: Integration | None = await session.get(Integration, integration.id)
                if row:
                    row.extra_data = new_extra
                    flag_modified(row, "extra_data")
                    await session.commit()

    # ── Write ────────────────────────────────────────────────────────────

    async def write(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        if operation == "create_issue":
            return await self.create_issue(**data)
        if operation == "update_issue":
            return await self.update_issue(**data)
        raise ValueError(f"Unknown write operation: {operation}")

    async def create_issue(
        self,
        *,
        list_name: str,
        title: str,
        board_name: str | None = None,
        board_id: str | None = None,
        description: str | None = None,
        due_date: str | None = None,
        assignee_name: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        bid: str | None = board_id
        if not bid and board_name:
            b: dict[str, Any] | None = await self.resolve_board_by_name(board_name)
            bid = _str_or_none(b.get("id")) if b else None
        if not bid:
            raise ValueError("board_id or resolvable board_name is required")

        lists_raw: Any = await self._get(
            f"/boards/{bid}/lists",
            {"filter": "open", "fields": "id,name"},
        )
        lst_items: list[dict[str, Any]] = (
            lists_raw if isinstance(lists_raw, list) else []
        )
        list_id: str | None = None
        ln_lower: str = list_name.lower().strip()
        for li in lst_items:
            if str(li.get("name", "")).lower().strip() == ln_lower:
                list_id = str(li["id"])
                break
        if not list_id:
            raise ValueError(f"List '{list_name}' not found on board")

        body: dict[str, Any] = {
            "name": title,
            "idList": list_id,
        }
        if description:
            body["desc"] = description
        if due_date:
            body["due"] = due_date
            body["dueComplete"] = False

        member_id: str | None = None
        if assignee_name:
            m = await self.resolve_member_by_name(bid, assignee_name)
            if m:
                member_id = str(m.get("id"))

        created: Any = await self._post("/cards", json_body=body)
        if not isinstance(created, dict):
            raise RuntimeError("Unexpected create card response")
        cid: str = str(created.get("id", ""))

        if member_id:
            await self._put(
                f"/cards/{cid}/idMembers",
                params={"value": member_id},
            )

        if labels:
            for lab in labels:
                try:
                    await self._post(
                        f"/cards/{cid}/idLabels",
                        params={"value": await self._ensure_label_id(bid, lab)},
                    )
                except Exception as exc:
                    logger.warning("[trello] Could not add label %s: %s", lab, exc)

        return {
            "id": cid,
            "shortLink": created.get("shortLink"),
            "url": created.get("url", ""),
            "name": created.get("name"),
        }

    async def _ensure_label_id(self, board_id: str, label_name: str) -> str:
        """Return label id, creating a green label on the board if missing."""
        labels_raw: Any = await self._get(
            f"/boards/{board_id}/labels",
            {"fields": "id,name,color"},
        )
        items: list[dict[str, Any]] = (
            labels_raw if isinstance(labels_raw, list) else []
        )
        target: str = label_name.strip()
        for lb in items:
            if str(lb.get("name", "")).lower() == target.lower() and lb.get("id"):
                return str(lb["id"])
        created: Any = await self._post(
            f"/boards/{board_id}/labels",
            params={"name": target, "color": "green"},
        )
        if isinstance(created, dict) and created.get("id"):
            return str(created["id"])
        raise RuntimeError(f"Could not create label {target}")

    async def update_issue(
        self,
        *,
        issue_identifier: str,
        title: str | None = None,
        description: str | None = None,
        state_name: str | None = None,
        due_date: str | None = None,
        assignee_name: str | None = None,
    ) -> dict[str, Any]:
        card_id: str = await self._resolve_card_id(issue_identifier)
        board_id: str = await self._board_id_for_card(card_id)

        body: dict[str, Any] = {}
        if title is not None:
            body["name"] = title
        if description is not None:
            body["desc"] = description
        if due_date is not None:
            if due_date.strip() == "":
                body["due"] = None
                body["dueComplete"] = False
            else:
                body["due"] = due_date
                body["dueComplete"] = False

        if body:
            await self._put(f"/cards/{card_id}", json_body=body)

        if state_name:
            lists_raw: Any = await self._get(
                f"/boards/{board_id}/lists",
                {"filter": "open", "fields": "id,name"},
            )
            lst_items: list[dict[str, Any]] = (
                lists_raw if isinstance(lists_raw, list) else []
            )
            target_list: str | None = None
            sn_lower: str = state_name.lower().strip()
            for li in lst_items:
                if str(li.get("name", "")).lower().strip() == sn_lower:
                    target_list = str(li["id"])
                    break
            if not target_list:
                raise ValueError(f"List '{state_name}' not found on board")
            await self._put(
                f"/cards/{card_id}",
                json_body={"idList": target_list},
            )

        if assignee_name is not None:
            if assignee_name.strip() == "":
                mem_raw: Any = await self._get(
                    f"/cards/{card_id}/members",
                    {"fields": "id"},
                )
                mem_list: list[dict[str, Any]] = (
                    mem_raw if isinstance(mem_raw, list) else []
                )
                for mem in mem_list:
                    mid: str | None = _str_or_none(mem.get("id"))
                    if mid:
                        try:
                            await self._delete(
                                f"/cards/{card_id}/idMembers/{mid}",
                            )
                        except Exception as exc:
                            logger.warning(
                                "[trello] Could not remove member %s: %s", mid, exc
                            )
            else:
                m = await self.resolve_member_by_name(board_id, assignee_name)
                if m and m.get("id"):
                    await self._put(
                        f"/cards/{card_id}/idMembers",
                        params={"value": str(m["id"])},
                    )

        refreshed: Any = await self._get(
            f"/cards/{card_id}",
            {
                "fields": (
                    "id,shortLink,name,desc,url,due,dueComplete,"
                    "idList,idBoard,labels"
                ),
            },
        )
        return refreshed if isinstance(refreshed, dict) else {"id": card_id}

    async def _resolve_card_id(self, issue_identifier: str) -> str:
        raw: str = issue_identifier.strip()
        if raw.startswith("TRELLO-"):
            raw = raw.split("TRELLO-", 1)[-1]
        # Trello accepts 24-char id or card shortLink as {id} in GET /cards/{id}
        try:
            card: Any = await self._get(
                f"/cards/{raw}",
                {"fields": "id"},
            )
            if isinstance(card, dict) and card.get("id"):
                return str(card["id"])
        except Exception:
            pass
        return raw

    async def _board_id_for_card(self, card_id: str) -> str:
        c: Any = await self._get(
            f"/cards/{card_id}",
            {"fields": "idBoard"},
        )
        if isinstance(c, dict) and c.get("idBoard"):
            return str(c["idBoard"])
        raise RuntimeError("Could not resolve board for card")

    async def resolve_board_by_name(self, name: str) -> dict[str, Any] | None:
        if not self._member_me_id:
            await self.sync_teams()
        boards_raw: Any = await self._get(
            f"/members/{self._member_me_id}/boards",
            {"filter": "open", "fields": "id,name"},
        )
        boards: list[dict[str, Any]] = boards_raw if isinstance(boards_raw, list) else []
        nl: str = name.lower().strip()
        for b in boards:
            if str(b.get("name", "")).lower().strip() == nl:
                return b
        return None

    async def resolve_member_by_name(
        self, board_id: str, name: str
    ) -> dict[str, Any] | None:
        members_raw: Any = await self._get(
            f"/boards/{board_id}/members",
            {"fields": "id,fullName,username"},
        )
        members: list[dict[str, Any]] = (
            members_raw if isinstance(members_raw, list) else []
        )
        nl: str = name.lower().strip()
        for m in members:
            fn: str = str(m.get("fullName") or "").lower().strip()
            un: str = str(m.get("username") or "").lower().strip()
            if fn == nl or un == nl:
                return m
        return None

    # ── LISTEN ───────────────────────────────────────────────────────────

    @staticmethod
    def verify_webhook(
        raw_body: bytes,
        headers: dict[str, str],
        secret: str,
        **kwargs: Any,
    ) -> bool:
        """Verify Trello webhook (HMAC-SHA1 of body + callback URL, base64)."""
        request_url: str | None = kwargs.get("request_url")
        if not request_url or not secret:
            return False
        trello_hdr: str | None = (
            headers.get("x-trello-webhook")
            or headers.get("X-Trello-Webhook")
        )
        if not trello_hdr:
            return False
        try:
            body_str: str = raw_body.decode("utf-8")
            msg: bytes = (body_str + request_url).encode("utf-8")
            digest: bytes = hmac.new(
                secret.encode("utf-8"), msg, hashlib.sha1
            ).digest()
            expected_b64: str = base64.b64encode(digest).decode("ascii")
            return hmac.compare_digest(expected_b64.strip(), trello_hdr.strip())
        except (UnicodeDecodeError, ValueError, TypeError):
            return False

    @staticmethod
    def process_webhook_payload(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        events: list[tuple[str, dict[str, Any]]] = []
        action: dict[str, Any] | None = payload.get("action")
        if not isinstance(action, dict):
            return events

        atype: str = str(action.get("type") or "")
        data: dict[str, Any] = action.get("data") if isinstance(action.get("data"), dict) else {}

        # Card lifecycle signals
        if atype in (
            "createCard",
            "updateCard",
            "moveCardFromListToList",
            "copyCard",
            "commentCard",
        ):
            events.append((TRELLO_CARD_UPDATED_EVENT, dict(payload)))

        list_after: dict[str, Any] | None = data.get("listAfter")
        if isinstance(list_after, dict):
            lname: str = str(list_after.get("name") or "")
            if _list_name_implies_done(lname):
                events.append((TRELLO_CARD_DONE_EVENT, dict(payload)))

        return events

    async def handle_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == TRELLO_CARD_DONE_EVENT:
            card = (payload.get("action") or {}).get("data", {}).get("card") or {}
            logger.info(
                "[trello] card.done org=%s card=%s",
                self.organization_id,
                card.get("id"),
            )
        elif event_type == TRELLO_CARD_UPDATED_EVENT:
            logger.info("[trello] card.updated org=%s", self.organization_id)

    # ── CRM stubs ─────────────────────────────────────────────────────────

    async def sync_deals(self) -> int:
        return 0

    async def sync_accounts(self) -> int:
        return 0

    async def sync_contacts(self) -> int:
        return 0

    async def sync_activities(self) -> int:
        return 0

    async def fetch_deal(self, deal_id: str) -> dict[str, Any]:
        raise NotImplementedError("Trello connector does not support deals")


def _str_or_none(val: Any) -> str | None:
    if val is None:
        return None
    s: str = str(val).strip()
    return s or None


def _truncate_text(text: str | None, max_len: int) -> str | None:
    if text is None:
        return None
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _trello_id_to_datetime(card_id: str) -> datetime:
    """Decode Mongo-style Trello id timestamp (ms)."""
    try:
        prefix: str = card_id[:8]
        ms: int = int(prefix, 16)
        return datetime.utcfromtimestamp(ms / 1000.0)
    except (ValueError, TypeError):
        return datetime.utcnow()


def _parse_dt_optional(val: Any) -> datetime | None:
    if not val or not isinstance(val, str):
        return None
    try:
        cleaned: str = val.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _parse_date_only(val: Any) -> date | None:
    if not val or not isinstance(val, str):
        return None
    try:
        return date.fromisoformat(val[:10])
    except (ValueError, TypeError):
        return None


def _priority_from_labels(labels: list[str]) -> tuple[int | None, str | None]:
    for lb in labels:
        key: str = lb.lower().strip()
        if key in _LABEL_PRIORITY_MAP:
            return _LABEL_PRIORITY_MAP[key]
    return None, None


def _resolve_state_type(due_complete: bool, list_name: str | None) -> str:
    if due_complete:
        return "completed"
    if list_name:
        lower: str = list_name.lower()
        if lower in ("done", "complete", "completed"):
            return "completed"
        if lower in ("backlog", "later", "icebox", "someday"):
            return "backlog"
        if lower in (
            "in progress",
            "doing",
            "in review",
            "started",
            "doing now",
        ):
            return "started"
    return "unstarted"


def _list_name_implies_done(name: str) -> bool:
    lower: str = name.lower().strip()
    return lower in ("done", "complete", "completed", "closed")

