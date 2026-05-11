"""
Attio CRM connector — sync people, companies, deals, and notes; query, write, and actions.

Uses OAuth2 via Nango and Attio REST API v2 (https://api.attio.com).

LISTEN (webhooks) is intentionally deferred (see plan).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime
from typing import Any, Final

import httpx

from connectors.base import BaseConnector
from connectors.models import AccountRecord, ActivityRecord, ContactRecord, DealRecord
from connectors.registry import (
    AuthType,
    Capability,
    ConnectorAction,
    ConnectorMeta,
    ConnectorScope,
    WriteOperation,
)

logger = logging.getLogger(__name__)

ATTIO_API_BASE: Final[str] = "https://api.attio.com"
DEFAULT_PAGE_LIMIT_RECORDS: Final[int] = 500
DEFAULT_PAGE_LIMIT_NOTES: Final[int] = 50
_MAX_429_RETRIES: Final[int] = 5


def _iso_utc_z(dt: datetime) -> str:
    """Format naive UTC datetime as Attio-friendly ISO-8601 with Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_attio_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None) if raw.tzinfo else raw
    if isinstance(raw, str):
        cleaned: str = raw.strip()
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _parse_attio_date(raw: Any) -> date | None:
    dt: datetime | None = _parse_attio_datetime(raw)
    if dt:
        return dt.date()
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return None
    return None


def _record_id_from_payload(record: dict[str, Any]) -> str | None:
    id_obj: Any = record.get("id")
    if isinstance(id_obj, dict):
        rid: Any = id_obj.get("record_id")
        if rid is not None:
            return str(rid).strip() or None
    return None


def _first_attr_item(values: dict[str, Any], key: str) -> dict[str, Any] | None:
    items: Any = values.get(key)
    if not isinstance(items, list) or len(items) == 0:
        return None
    first: Any = items[0]
    return first if isinstance(first, dict) else None


def _employee_range_to_int(raw_title: str | None) -> int | None:
    if not raw_title:
        return None
    text: str = raw_title.strip().lower()
    # e.g. "51-200", "201-500", "1000+"
    range_match: re.Match[str] | None = re.search(r"(\d+)\s*-\s*(\d+)", text)
    if range_match:
        low: int = int(range_match.group(1))
        high: int = int(range_match.group(2))
        return (low + high) // 2
    plus_match: re.Match[str] | None = re.search(r"(\d+)\s*\+", text)
    if plus_match:
        return int(plus_match.group(1))
    single_match: re.Match[str] | None = re.search(r"(\d+)", text)
    if single_match:
        return int(single_match.group(1))
    return None


def _attio_deal_stage_values(stage: str) -> list[dict[str, Any]]:
    """POST/PATCH deal `stage`: Attio expects `[{\"status\": \"<title or UUID>\"}]`, not `[\"Lead\"]`"""
    s: str = str(stage).strip()
    if not s:
        raise ValueError("stage must be a non-empty pipeline status title or status UUID (e.g. Lead)")
    return [{"status": s}]


_DEAL_CREATE_WRITE_RESERVED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "stage",
        "owner_email",
        "owner_workspace_member_id",
        "owner_id",
        "value",
        "currency",
        "company_id",
        "values",
    }
)
_DEAL_UPDATE_WRITE_RESERVED_KEYS: Final[frozenset[str]] = frozenset(
    _DEAL_CREATE_WRITE_RESERVED_KEYS
    | {
        "id",
        "deal_id",
    }
)


def _deal_extra_values_from_write_payload(
    payload: dict[str, Any],
    *,
    reserved_keys: frozenset[str],
) -> dict[str, Any]:
    """Build Attio ``data.values`` entries for custom attributes (slug → payload).

    Merges optional nested ``values`` first, then any top-level keys not in
    ``reserved_keys``. Standard deal fields are applied afterward and always win.
    """
    extras: dict[str, Any] = {}
    nested: Any = payload.get("values")
    if isinstance(nested, dict):
        for slug_raw, val in nested.items():
            slug: str = str(slug_raw).strip() if isinstance(slug_raw, str) else ""
            if not slug or slug.startswith("_"):
                continue
            if val is None:
                continue
            extras[slug] = val
    for key_raw, val in payload.items():
        if key_raw in reserved_keys or key_raw == "values":
            continue
        key: str = str(key_raw).strip() if isinstance(key_raw, str) else ""
        if not key or key.startswith("_"):
            continue
        if val is None:
            continue
        extras[key] = val
    return extras


def _attio_deal_owner_values(data: dict[str, Any], *, required: bool) -> list[dict[str, Any]] | None:
    """Standard Attio deals require an owner (workspace member)."""
    wid: Any = data.get("owner_workspace_member_id") or data.get("owner_id")
    if wid is not None and str(wid).strip():
        return [
            {
                "referenced_actor_type": "workspace-member",
                "referenced_actor_id": str(wid).strip(),
            }
        ]
    email: Any = data.get("owner_email")
    if email is not None and str(email).strip():
        return [{"workspace_member_email_address": str(email).strip()}]
    if required:
        raise ValueError(
            "create_deal requires owner_email or owner_workspace_member_id "
            "(Deal owner is required in Attio; use run_on_connector list_workspace_members for IDs)."
        )
    return None


class AttioConnector(BaseConnector):
    """Connector for Attio CRM (people, companies, deals, notes)."""

    source_system: str = "attio"

    meta = ConnectorMeta(
        name="Attio",
        slug="attio",
        auth_type=AuthType.OAUTH2,
        scope=ConnectorScope.ORGANIZATION,
        entity_types=["deals", "accounts", "contacts", "activities"],
        capabilities=[Capability.SYNC, Capability.QUERY, Capability.WRITE, Capability.ACTION],
        oauth_scopes=[
            "record_permission:read-write",
            "object_configuration:read",
            "note:read-write",
            "note:read",
            "task:read",
            "user_management:read",
            "list_entry:read",
            "list_configuration:read",
        ],
        write_operations=[
            WriteOperation(
                name="create_person",
                entity_type="contact",
                description="Create or update a person in Attio (idempotent on email_addresses)",
                parameters=[
                    {"name": "email", "type": "string", "required": True, "description": "Primary email"},
                    {"name": "first_name", "type": "string", "required": False},
                    {"name": "last_name", "type": "string", "required": False},
                    {"name": "company_id", "type": "string", "required": False, "description": "Attio company record_id"},
                    {"name": "job_title", "type": "string", "required": False},
                    {"name": "phone", "type": "string", "required": False},
                ],
            ),
            WriteOperation(
                name="update_person",
                entity_type="contact",
                description="Patch an existing Attio person by record_id",
                parameters=[
                    {"name": "id", "type": "string", "required": True, "description": "Attio person record_id"},
                    {"name": "email", "type": "string", "required": False},
                    {"name": "first_name", "type": "string", "required": False},
                    {"name": "last_name", "type": "string", "required": False},
                    {"name": "company_id", "type": "string", "required": False},
                    {"name": "job_title", "type": "string", "required": False},
                    {"name": "phone", "type": "string", "required": False},
                ],
            ),
            WriteOperation(
                name="create_company",
                entity_type="company",
                description="Create or update a company (idempotent on domains matching_attribute)",
                parameters=[
                    {"name": "name", "type": "string", "required": True},
                    {"name": "domains", "type": "array", "required": False, "description": "Domains e.g. [\"acme.com\"]"},
                    {"name": "domain", "type": "string", "required": False, "description": "Single domain shorthand"},
                ],
            ),
            WriteOperation(
                name="update_company",
                entity_type="company",
                description="Patch an existing Attio company by record_id",
                parameters=[
                    {"name": "id", "type": "string", "required": True},
                    {"name": "name", "type": "string", "required": False},
                    {"name": "domains", "type": "array", "required": False},
                ],
            ),
            WriteOperation(
                name="create_deal",
                entity_type="deal",
                description="Create a deal record in Attio",
                parameters=[
                    {"name": "name", "type": "string", "required": True},
                    {
                        "name": "stage",
                        "type": "string",
                        "required": True,
                        "description": "Deal stage status title or UUID (must match a pipeline stage, e.g. Lead)",
                    },
                    {
                        "name": "owner_email",
                        "type": "string",
                        "required": False,
                        "description": "Workspace member email for Deal owner (required unless owner_workspace_member_id)",
                    },
                    {
                        "name": "owner_workspace_member_id",
                        "type": "string",
                        "required": False,
                        "description": "Workspace member UUID for Deal owner (required unless owner_email)",
                    },
                    {"name": "value", "type": "number", "required": False, "description": "Deal value amount"},
                    {"name": "currency", "type": "string", "required": False, "description": "ISO currency e.g. USD"},
                    {"name": "company_id", "type": "string", "required": False, "description": "associated_company target_record_id"},
                    {
                        "name": "values",
                        "type": "object",
                        "required": False,
                        "description": "Additional deal attributes by Attio api_slug (merged into data.values; use get_schema for slugs)",
                    },
                ],
            ),
            WriteOperation(
                name="update_deal",
                entity_type="deal",
                description="Patch an existing Attio deal by record_id",
                parameters=[
                    {"name": "id", "type": "string", "required": True},
                    {"name": "name", "type": "string", "required": False},
                    {"name": "stage", "type": "string", "required": False},
                    {"name": "owner_email", "type": "string", "required": False},
                    {"name": "owner_workspace_member_id", "type": "string", "required": False},
                    {"name": "value", "type": "number", "required": False},
                    {"name": "currency", "type": "string", "required": False},
                    {"name": "company_id", "type": "string", "required": False},
                    {
                        "name": "values",
                        "type": "object",
                        "required": False,
                        "description": "Additional deal attributes by Attio api_slug (merged into data.values)",
                    },
                ],
            ),
            WriteOperation(
                name="create_note",
                entity_type="note",
                description="Create a note attached to a record",
                parameters=[
                    {"name": "parent_object", "type": "string", "required": True, "description": "Slug e.g. people, companies, deals"},
                    {"name": "parent_record_id", "type": "string", "required": True},
                    {"name": "title", "type": "string", "required": True},
                    {"name": "content", "type": "string", "required": True},
                    {"name": "format", "type": "string", "required": False, "description": "plaintext or markdown"},
                ],
            ),
            WriteOperation(
                name="delete_person",
                entity_type="contact",
                description="Permanently delete an Attio person record by record_id",
                parameters=[
                    {"name": "id", "type": "string", "required": True, "description": "Attio person record_id"},
                ],
            ),
            WriteOperation(
                name="delete_company",
                entity_type="company",
                description="Permanently delete an Attio company record by record_id",
                parameters=[
                    {"name": "id", "type": "string", "required": True, "description": "Attio company record_id"},
                ],
            ),
            WriteOperation(
                name="delete_deal",
                entity_type="deal",
                description="Permanently delete an Attio deal record by record_id",
                parameters=[
                    {"name": "id", "type": "string", "required": True, "description": "Attio deal record_id"},
                ],
            ),
            WriteOperation(
                name="delete_note",
                entity_type="note",
                description="Permanently delete an Attio note by note_id",
                parameters=[
                    {"name": "id", "type": "string", "required": True, "description": "Attio note_id"},
                ],
            ),
        ],
        actions=[
            ConnectorAction(
                name="search_records",
                description="POST /v2/objects/{object}/records/query with filter/sorts",
                parameters=[
                    {"name": "object", "type": "string", "required": True, "description": "Object slug e.g. people, companies, deals"},
                    {"name": "filter", "type": "object", "required": False},
                    {"name": "sorts", "type": "array", "required": False},
                    {"name": "limit", "type": "integer", "required": False},
                    {"name": "offset", "type": "integer", "required": False},
                ],
            ),
            ConnectorAction(
                name="get_record",
                description="GET a single record by object slug and record_id",
                parameters=[
                    {"name": "object", "type": "string", "required": True},
                    {"name": "id", "type": "string", "required": True},
                ],
            ),
            ConnectorAction(
                name="list_workspace_members",
                description="GET /v2/workspace_members",
                parameters=[],
            ),
            ConnectorAction(
                name="list_lists",
                description="GET /v2/lists",
                parameters=[],
            ),
            ConnectorAction(
                name="list_list_entries",
                description="POST /v2/lists/{list}/entries/query",
                parameters=[
                    {"name": "list", "type": "string", "required": True, "description": "List api_slug or list UUID"},
                    {"name": "filter", "type": "object", "required": False},
                    {"name": "sorts", "type": "array", "required": False},
                    {"name": "limit", "type": "integer", "required": False},
                    {"name": "offset", "type": "integer", "required": False},
                ],
            ),
            ConnectorAction(
                name="list_statuses",
                description=(
                    "GET /v2/objects/{object}/attributes/{attribute}/statuses — "
                    "list selectable status values (titles and IDs). Default: deals.stage for pipeline stages."
                ),
                parameters=[
                    {
                        "name": "object",
                        "type": "string",
                        "required": False,
                        "description": "Object api_slug (default: deals)",
                    },
                    {
                        "name": "attribute",
                        "type": "string",
                        "required": False,
                        "description": "Status attribute api_slug (default: stage)",
                    },
                ],
            ),
        ],
        nango_integration_id="attio",
        query_description=(
            "Pass JSON: {\"object\":\"people|companies|deals\", \"filter\": {...}, \"sorts\": [...], \"limit\": 50}. "
            "Use get_schema (query_system with schema) for attribute slugs. Omit filter for first page of all records."
        ),
        description="Attio CRM — people, companies, deals, notes; live search and writes",
        usage_guide="""# Attio Usage Guide

Attio does **not** expose HubSpot-style pipelines as separate entities; deal **stage** lives on the deal record.

## Synced tables

After connecting and syncing, query SQL on `contacts`, `accounts`, `deals`, `activities` with `source_system = 'attio'`.

## Write (`write_on_connector`)

- **create_person** — Required: `email`. Uses assert on `email_addresses`. Optional: `first_name`, `last_name`, `company_id`, `job_title`, `phone`.
- **update_person** — Required: `id` (Attio `record_id`).
- **create_company** — Required: `name`. Optional: `domains` (array) or `domain` (string). Assert uses `domains`.
- **update_company** — Required: `id`.
- **create_deal** — Required: `name`, `stage` (must match a configured pipeline status **title** or **status UUID**), and **either** `owner_email` **or** `owner_workspace_member_id`. Call **`list_statuses`** first (default: deals + stage) to see exact titles/IDs for this workspace—do not guess. Optional: `value`, `currency`, `company_id`. **Custom attributes:** pass Attio attribute **api_slug** as extra top-level keys (e.g. `pipeline_type`) or grouped under optional `values` — each value is sent as-is in `data.values` per [Attio deals API](https://docs.attio.com/rest-api/endpoint-reference/deals/create-a-deal-record).
- **update_deal** — Required: `id`. Optional: `name`, `stage`, `owner_email`, `owner_workspace_member_id`, `value`, `currency`, `company_id`. Same **custom attributes** rules as `create_deal`.
- **create_note** — Required: `parent_object`, `parent_record_id`, `title`, `content`. Optional: `format` (`plaintext`|`markdown`).
- **delete_person** / **delete_company** / **delete_deal** — Required: `id` (Attio `record_id`). Permanently deletes the record in Attio (irreversible). Use to clean up duplicates or unwanted records.
- **delete_note** — Required: `id` (Attio `note_id`). Permanently deletes the note (irreversible).

## Actions (`run_on_connector`)

- **search_records** — `object`, optional `filter`, `sorts`, `limit`, `offset`.
- **get_record** — `object`, `id`.
- **list_workspace_members** — no params.
- **list_lists** — no params.
- **list_list_entries** — `list` (slug or id), optional `filter`, `sorts`, `limit`, `offset`.
- **list_statuses** — Optional `object` (default `deals`), optional `attribute` (default `stage`). Returns workspace-specific status titles/UUIDs; **use before create_deal** so `stage` matches Attio.
""",
    )

    async def _get_headers(self) -> dict[str, str]:
        token: str
        token, _ = await self.get_oauth_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers: dict[str, str] = await self._get_headers()
        url: str = f"{ATTIO_API_BASE}{endpoint}"
        last_exc: httpx.HTTPStatusError | None = None

        for attempt in range(_MAX_429_RETRIES + 1):
            async with httpx.AsyncClient(timeout=60.0) as client:
                response: httpx.Response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )

                if response.status_code == 429 and attempt < _MAX_429_RETRIES:
                    retry_after: float = float(response.headers.get("Retry-After", "5"))
                    wait_secs: float = min(max(retry_after, 1.0), 60.0)
                    logger.warning(
                        "Attio 429 on %s %s, sleeping %.1fs (attempt %d)",
                        method,
                        endpoint,
                        wait_secs,
                        attempt + 1,
                    )
                    await asyncio.sleep(wait_secs)
                    continue

                if response.status_code >= 400:
                    detail: str = ""
                    try:
                        err_body: dict[str, Any] = response.json()
                        detail = str(err_body.get("message", err_body))
                    except Exception:
                        detail = response.text[:500] if response.text else ""
                    last_exc = httpx.HTTPStatusError(
                        f"Attio API error ({response.status_code}): {detail}",
                        request=response.request,
                        response=response,
                    )
                    raise last_exc

                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()

        assert last_exc is not None
        raise last_exc

    # Object types where Attio's `last_interaction` system attribute is
    # available. `last_interaction` aggregates email + calendar interactions
    # and is updated whenever the record is touched, so filtering on it lets
    # us catch records that were *updated* (not just created) since last sync.
    # Per Attio v2 docs, this is supported on people and companies. Deals do
    # not expose a queryable "last modified" timestamp; we fall back to
    # `created_at` only for those (see ``_incremental_record_filter_for``).
    _OBJECTS_WITH_LAST_INTERACTION: frozenset[str] = frozenset({"people", "companies"})

    def _incremental_record_filter_for(
        self, object_slug: str
    ) -> dict[str, Any] | None:
        """Incremental filter for a specific object type.

        Catches records *created* AND *updated/interacted with* since the last
        successful sync, where Attio supports it. Object types differ in which
        timestamps are filterable; emitting an unknown slug returns
        ``400 Unknown attribute slug``, so we whitelist per object type.
        """
        if self.sync_since is None:
            return None
        iso: str = _iso_utc_z(self.sync_since)
        created_clause: dict[str, Any] = {"created_at": {"$gte": iso}}
        if object_slug not in self._OBJECTS_WITH_LAST_INTERACTION:
            return created_clause
        last_interaction_clause: dict[str, Any] = {
            "last_interaction": {"interacted_at": {"$gte": iso}}
        }
        return {"$or": [created_clause, last_interaction_clause]}

    async def _paginate_object_records(
        self,
        object_slug: str,
        *,
        extra_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        base_filter: dict[str, Any] | None = self._incremental_record_filter_for(
            object_slug
        )
        merged_filter: dict[str, Any] | None
        if base_filter and extra_filter:
            merged_filter = {"$and": [base_filter, extra_filter]}
        elif base_filter:
            merged_filter = base_filter
        else:
            merged_filter = extra_filter

        out: list[dict[str, Any]] = []
        offset: int = 0
        attempted_fallback: bool = False
        while True:
            body: dict[str, Any] = {
                "limit": DEFAULT_PAGE_LIMIT_RECORDS,
                "offset": offset,
            }
            if merged_filter:
                body["filter"] = merged_filter

            try:
                data: dict[str, Any] = await self._make_request(
                    "POST",
                    f"/v2/objects/{object_slug}/records/query",
                    json_body=body,
                )
            except httpx.HTTPStatusError as exc:
                # Defensive fallback: if Attio rejects an attribute slug we
                # assumed was supported (e.g. workspace customization disabled
                # `last_interaction`), retry once with `created_at` only so the
                # sync still picks up newly-created records instead of failing.
                response: httpx.Response | None = exc.response
                status_code: int | None = (
                    response.status_code if response is not None else None
                )
                if (
                    status_code == 400
                    and not attempted_fallback
                    and base_filter is not None
                    and "Unknown attribute slug" in str(exc)
                ):
                    logger.warning(
                        "Attio %s incremental filter rejected (%s); "
                        "falling back to created_at-only filter",
                        object_slug,
                        exc,
                    )
                    iso_fallback: str = _iso_utc_z(self.sync_since) if self.sync_since else ""
                    created_only: dict[str, Any] = {"created_at": {"$gte": iso_fallback}}
                    if extra_filter is not None:
                        merged_filter = {"$and": [created_only, extra_filter]}
                    else:
                        merged_filter = created_only
                    attempted_fallback = True
                    continue
                raise
            rows: Any = data.get("data", [])
            if not isinstance(rows, list):
                break
            out.extend([r for r in rows if isinstance(r, dict)])
            if len(rows) < DEFAULT_PAGE_LIMIT_RECORDS:
                break
            offset += DEFAULT_PAGE_LIMIT_RECORDS
            await self.ensure_sync_active(f"sync_{object_slug}:page")

        return out

    def _contact_from_attio(self, record: dict[str, Any]) -> ContactRecord | None:
        rid: str | None = _record_id_from_payload(record)
        if not rid:
            return None
        values: dict[str, Any] = record.get("values") if isinstance(record.get("values"), dict) else {}

        name_val: dict[str, Any] | None = _first_attr_item(values, "name")
        full_name: str | None = None
        if name_val:
            full_name = name_val.get("full_name") if isinstance(name_val.get("full_name"), str) else None
            if not full_name:
                fn: str = str(name_val.get("first_name", "") or "")
                ln: str = str(name_val.get("last_name", "") or "")
                full_name = (fn + " " + ln).strip() or None

        email: str | None = None
        emails: Any = values.get("email_addresses")
        if isinstance(emails, list) and emails:
            e0: Any = emails[0]
            if isinstance(e0, str):
                email = e0.strip() or None
            elif isinstance(e0, dict):
                ea: Any = e0.get("email_address")
                email = str(ea).strip() if ea else None

        phone: str | None = None
        phones: Any = values.get("phone_numbers")
        if isinstance(phones, list) and phones and isinstance(phones[0], dict):
            phone = phones[0].get("original_phone_number")
            phone = str(phone).strip() if phone else None

        title: str | None = None
        titles: Any = values.get("job_title")
        if isinstance(titles, list) and titles and isinstance(titles[0], dict):
            tv: Any = titles[0].get("value")
            title = str(tv).strip() if tv else None

        company_id: str | None = None
        companies: Any = values.get("company")
        if isinstance(companies, list) and companies and isinstance(companies[0], dict):
            trid: Any = companies[0].get("target_record_id")
            company_id = str(trid).strip() if trid else None

        return ContactRecord(
            source_id=rid,
            name=full_name or email or "Unknown",
            email=email,
            title=title,
            phone=phone,
            account_source_id=company_id,
            custom_fields=dict(values) if values else None,
            source_system=self.source_system,
        )

    def _account_from_attio(self, record: dict[str, Any]) -> AccountRecord | None:
        rid: str | None = _record_id_from_payload(record)
        if not rid:
            return None
        values: dict[str, Any] = record.get("values") if isinstance(record.get("values"), dict) else {}

        name: str = "Unknown"
        names: Any = values.get("name")
        if isinstance(names, list) and names and isinstance(names[0], dict):
            nv: Any = names[0].get("value")
            if nv:
                name = str(nv)

        domain: str | None = None
        domains: Any = values.get("domains")
        if isinstance(domains, list) and domains and isinstance(domains[0], dict):
            dv: Any = domains[0].get("domain")
            domain = str(dv).strip().lower() if dv else None

        industry: str | None = None
        cats: Any = values.get("categories")
        if isinstance(cats, list) and cats and isinstance(cats[0], dict):
            opt: Any = cats[0].get("option")
            if isinstance(opt, dict):
                title: Any = opt.get("title")
                industry = str(title) if title else None

        employee_count: int | None = None
        er: Any = values.get("employee_range")
        if isinstance(er, list) and er and isinstance(er[0], dict):
            opt2: Any = er[0].get("option")
            if isinstance(opt2, dict):
                etitle: Any = opt2.get("title")
                employee_count = _employee_range_to_int(str(etitle) if etitle else None)

        return AccountRecord(
            source_id=rid,
            name=name,
            domain=domain,
            industry=industry,
            employee_count=employee_count,
            custom_fields=dict(values) if values else None,
            source_system=self.source_system,
        )

    def _deal_from_attio(self, record: dict[str, Any]) -> DealRecord | None:
        rid: str | None = _record_id_from_payload(record)
        if not rid:
            return None
        values: dict[str, Any] = record.get("values") if isinstance(record.get("values"), dict) else {}

        deal_name: str = "Untitled deal"
        names: Any = values.get("name")
        if isinstance(names, list) and names and isinstance(names[0], dict):
            nv: Any = names[0].get("value")
            if nv:
                deal_name = str(nv)

        amount: float | None = None
        vals: Any = values.get("value")
        if isinstance(vals, list) and vals and isinstance(vals[0], dict):
            cv: Any = vals[0].get("currency_value")
            if cv is not None:
                try:
                    amount = float(cv)
                except (TypeError, ValueError):
                    amount = None

        stage: str | None = None
        stages: Any = values.get("stage")
        if isinstance(stages, list) and stages and isinstance(stages[0], dict):
            st: Any = stages[0].get("status")
            if isinstance(st, dict):
                stitle: Any = st.get("title")
                stage = str(stitle) if stitle else None

        company_id: str | None = None
        assoc: Any = values.get("associated_company")
        if isinstance(assoc, list) and assoc and isinstance(assoc[0], dict):
            tr: Any = assoc[0].get("target_record_id")
            company_id = str(tr).strip() if tr else None

        close_date: date | None = None
        ecd: Any = values.get("expected_close_date")
        if isinstance(ecd, list) and ecd and isinstance(ecd[0], dict):
            raw_d: Any = ecd[0].get("value")
            close_date = _parse_attio_date(raw_d)

        created_date: datetime | None = None
        lm: datetime | None = None
        ca: Any = values.get("created_at")
        if isinstance(ca, list) and ca and isinstance(ca[0], dict):
            raw_ca: Any = ca[0].get("value")
            created_date = _parse_attio_datetime(raw_ca)

        return DealRecord(
            source_id=rid,
            name=deal_name,
            amount=amount,
            stage=stage,
            close_date=close_date,
            created_date=created_date,
            last_modified_date=lm,
            account_source_id=company_id,
            custom_fields=dict(values) if values else None,
            source_system=self.source_system,
        )

    def _activity_from_note(self, note: dict[str, Any]) -> ActivityRecord | None:
        nid_obj: Any = note.get("id")
        note_id: str | None = None
        if isinstance(nid_obj, dict):
            raw_nid: Any = nid_obj.get("note_id")
            note_id = str(raw_nid).strip() if raw_nid else None
        if not note_id:
            return None

        parent_obj: str = str(note.get("parent_object", "") or "").strip()
        parent_rec: str = str(note.get("parent_record_id", "") or "").strip()

        contact_sid: str | None = None
        account_sid: str | None = None
        deal_sid: str | None = None
        pol: str = parent_obj.lower()
        if pol == "people":
            contact_sid = parent_rec or None
        elif pol == "companies":
            account_sid = parent_rec or None
        elif pol == "deals":
            deal_sid = parent_rec or None

        title: str = str(note.get("title", "") or "Note")
        body: str = str(note.get("content_plaintext", "") or "")
        created: datetime | None = _parse_attio_datetime(note.get("created_at"))

        return ActivityRecord(
            source_id=note_id,
            type="note",
            subject=title,
            description=body,
            activity_date=created,
            deal_source_id=deal_sid,
            account_source_id=account_sid,
            contact_source_id=contact_sid,
            custom_fields={"parent_object": parent_obj, "parent_record_id": parent_rec},
            source_system=self.source_system,
        )

    # ------------------------------------------------------------------ SYNC

    async def sync_contacts(self) -> list[ContactRecord]:
        raw: list[dict[str, Any]] = await self._paginate_object_records("people")
        out: list[ContactRecord] = []
        for rec in raw:
            try:
                c: ContactRecord | None = self._contact_from_attio(rec)
                if c:
                    out.append(c)
            except Exception:
                logger.exception("Attio sync_contacts: skip bad record")
        return out

    async def sync_accounts(self) -> list[AccountRecord]:
        raw: list[dict[str, Any]] = await self._paginate_object_records("companies")
        out: list[AccountRecord] = []
        for rec in raw:
            try:
                a: AccountRecord | None = self._account_from_attio(rec)
                if a:
                    out.append(a)
            except Exception:
                logger.exception("Attio sync_accounts: skip bad record")
        return out

    async def sync_deals(self) -> list[DealRecord]:
        raw: list[dict[str, Any]] = await self._paginate_object_records("deals")
        out: list[DealRecord] = []
        for rec in raw:
            try:
                d: DealRecord | None = self._deal_from_attio(rec)
                if d:
                    out.append(d)
            except Exception:
                logger.exception("Attio sync_deals: skip bad record")
        return out

    async def sync_activities(self) -> list[ActivityRecord]:
        await self.ensure_sync_active("sync_activities:start")
        since: datetime | None = self.sync_since
        out: list[ActivityRecord] = []
        offset: int = 0
        while True:
            params: dict[str, Any] = {
                "limit": DEFAULT_PAGE_LIMIT_NOTES,
                "offset": offset,
            }
            data: dict[str, Any] = await self._make_request("GET", "/v2/notes", params=params)
            notes: Any = data.get("data", [])
            if not isinstance(notes, list) or len(notes) == 0:
                break
            for n in notes:
                if not isinstance(n, dict):
                    continue
                act: ActivityRecord | None = self._activity_from_note(n)
                if act and act.activity_date and since and act.activity_date < since:
                    continue
                if act:
                    out.append(act)
            if len(notes) < DEFAULT_PAGE_LIMIT_NOTES:
                break
            offset += DEFAULT_PAGE_LIMIT_NOTES
            await self.ensure_sync_active("sync_activities:page")
        return out

    async def fetch_deal(self, deal_id: str) -> dict[str, Any]:
        path: str = f"/v2/objects/deals/records/{deal_id.strip()}"
        return await self._make_request("GET", path)

    # ------------------------------------------------------------------ QUERY

    async def get_schema(self) -> list[dict[str, Any]]:
        objects_resp: dict[str, Any] = await self._make_request("GET", "/v2/objects")
        objs: Any = objects_resp.get("data", [])
        if not isinstance(objs, list):
            return []

        schema: list[dict[str, Any]] = []
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            slug: Any = obj.get("api_slug")
            if not slug or not isinstance(slug, str):
                continue
            try:
                attrs_resp: dict[str, Any] = await self._make_request(
                    "GET",
                    f"/v2/objects/{slug}/attributes",
                )
            except Exception:
                logger.warning("Attio get_schema: failed attributes for %s", slug)
                continue
            attrs: Any = attrs_resp.get("data", [])
            field_names: list[str] = []
            if isinstance(attrs, list):
                for a in attrs:
                    if isinstance(a, dict):
                        api_slug: Any = a.get("api_slug") or a.get("title")
                        if api_slug:
                            field_names.append(str(api_slug))
            schema.append({
                "entity": slug,
                "fields": sorted(set(field_names)),
                "singular": obj.get("singular_noun"),
                "plural": obj.get("plural_noun"),
            })
        return schema

    async def query(self, request: str) -> dict[str, Any]:
        try:
            payload: dict[str, Any] = json.loads(request)
        except (json.JSONDecodeError, TypeError):
            return {"error": "Invalid JSON. Expected {\"object\":\"people\", \"filter\": {...}, ...}"}

        obj_slug: str | None = payload.get("object")
        if not obj_slug or not isinstance(obj_slug, str):
            return {"error": "Missing string field 'object' (e.g. people, companies, deals)"}

        body: dict[str, Any] = {
            "limit": int(payload.get("limit", 50)),
            "offset": int(payload.get("offset", 0)),
        }
        filt: Any = payload.get("filter")
        if isinstance(filt, dict):
            body["filter"] = filt
        sorts: Any = payload.get("sorts")
        if isinstance(sorts, list):
            body["sorts"] = sorts

        data: dict[str, Any] = await self._make_request(
            "POST",
            f"/v2/objects/{obj_slug.strip()}/records/query",
            json_body=body,
        )
        return {"object": obj_slug, **data}

    # ------------------------------------------------------------------ WRITE

    def _person_values_from_data(self, data: dict[str, Any], *, include_email: bool) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if include_email:
            em: str | None = data.get("email")
            if em:
                values["email_addresses"] = [str(em).strip()]
        fn: str | None = data.get("first_name")
        ln: str | None = data.get("last_name")
        if fn or ln:
            entry: dict[str, Any] = {}
            if fn:
                entry["first_name"] = str(fn)
            if ln:
                entry["last_name"] = str(ln)
            full: str = (str(fn or "") + " " + str(ln or "")).strip()
            if full:
                entry["full_name"] = full
            values["name"] = [entry]
        if data.get("job_title"):
            values["job_title"] = [str(data["job_title"])]
        if data.get("phone"):
            values["phone_numbers"] = [
                {"original_phone_number": str(data["phone"]), "country_code": "US"},
            ]
        cid: str | None = data.get("company_id")
        if cid:
            values["company"] = [
                {"target_object": "companies", "target_record_id": str(cid).strip()},
            ]
        return values

    async def write(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        d: dict[str, Any] = dict(data)
        if operation == "create_person":
            values: dict[str, Any] = self._person_values_from_data(d, include_email=True)
            if not values.get("email_addresses"):
                raise ValueError("create_person requires email")
            return await self._make_request(
                "PUT",
                "/v2/objects/people/records",
                params={"matching_attribute": "email_addresses"},
                json_body={"data": {"values": values}},
            )
        if operation == "update_person":
            pid: str = str(d.pop("person_id", None) or d.pop("id", "") or "").strip()
            if not pid:
                raise ValueError("update_person requires id")
            values_u: dict[str, Any] = self._person_values_from_data(d, include_email=bool(d.get("email")))
            if not values_u:
                raise ValueError("update_person requires at least one field to update")
            return await self._make_request(
                "PATCH",
                f"/v2/objects/people/records/{pid}",
                json_body={"data": {"values": values_u}},
            )
        if operation == "create_company":
            name: str = str(d.get("name", "") or "").strip()
            if not name:
                raise ValueError("create_company requires name")
            domain_list: list[str] = []
            if isinstance(d.get("domains"), list):
                domain_list = [str(x).strip() for x in d["domains"] if str(x).strip()]
            elif d.get("domain"):
                domain_list = [str(d["domain"]).strip()]
            values_c: dict[str, Any] = {"name": [{"value": name}]}
            if domain_list:
                values_c["domains"] = [{"domain": dom.lower()} for dom in domain_list]
            if domain_list:
                return await self._make_request(
                    "PUT",
                    "/v2/objects/companies/records",
                    params={"matching_attribute": "domains"},
                    json_body={"data": {"values": values_c}},
                )
            return await self._make_request(
                "POST",
                "/v2/objects/companies/records",
                json_body={"data": {"values": values_c}},
            )
        if operation == "update_company":
            cid: str = str(d.pop("company_id", None) or d.pop("id", "") or "").strip()
            if not cid:
                raise ValueError("update_company requires id")
            values_uc: dict[str, Any] = {}
            if d.get("name"):
                values_uc["name"] = [{"value": str(d["name"])}]
            if isinstance(d.get("domains"), list):
                doms: list[str] = [str(x).strip() for x in d["domains"] if str(x).strip()]
                if doms:
                    values_uc["domains"] = [{"domain": x.lower()} for x in doms]
            if not values_uc:
                raise ValueError("update_company requires fields to update")
            return await self._make_request(
                "PATCH",
                f"/v2/objects/companies/records/{cid}",
                json_body={"data": {"values": values_uc}},
            )
        if operation == "create_deal":
            extras_cd: dict[str, Any] = _deal_extra_values_from_write_payload(
                d,
                reserved_keys=_DEAL_CREATE_WRITE_RESERVED_KEYS,
            )
            dn: str = str(d.get("name", "") or "").strip()
            if not dn:
                raise ValueError("create_deal requires name")
            stage_raw: Any = d.get("stage")
            if stage_raw is None or not str(stage_raw).strip():
                raise ValueError("create_deal requires stage (pipeline status title or UUID)")
            owner_vals: list[dict[str, Any]] | None = _attio_deal_owner_values(d, required=True)
            values_d: dict[str, Any] = dict(extras_cd)
            values_d["name"] = [{"value": dn}]
            values_d["stage"] = _attio_deal_stage_values(str(stage_raw))
            values_d["owner"] = owner_vals
            if d.get("value") is not None:
                cur: str = str(d.get("currency") or "USD")
                values_d["value"] = [{"currency_value": float(d["value"]), "currency_code": cur}]
            if d.get("company_id"):
                values_d["associated_company"] = [
                    {"target_object": "companies", "target_record_id": str(d["company_id"]).strip()},
                ]
            return await self._make_request(
                "POST",
                "/v2/objects/deals/records",
                json_body={"data": {"values": values_d}},
            )
        if operation == "update_deal":
            extras_ud: dict[str, Any] = _deal_extra_values_from_write_payload(
                d,
                reserved_keys=_DEAL_UPDATE_WRITE_RESERVED_KEYS,
            )
            did: str = str(d.pop("deal_id", None) or d.pop("id", "") or "").strip()
            if not did:
                raise ValueError("update_deal requires id")
            values_ud: dict[str, Any] = dict(extras_ud)
            if d.get("name"):
                values_ud["name"] = [{"value": str(d["name"])}]
            if d.get("stage") is not None and str(d.get("stage")).strip():
                values_ud["stage"] = _attio_deal_stage_values(str(d["stage"]))
            owner_patch: list[dict[str, Any]] | None = _attio_deal_owner_values(d, required=False)
            if owner_patch is not None:
                values_ud["owner"] = owner_patch
            if d.get("value") is not None:
                cur2: str = str(d.get("currency") or "USD")
                values_ud["value"] = [{"currency_value": float(d["value"]), "currency_code": cur2}]
            if d.get("company_id"):
                values_ud["associated_company"] = [
                    {"target_object": "companies", "target_record_id": str(d["company_id"]).strip()},
                ]
            if not values_ud:
                raise ValueError("update_deal requires fields to update")
            return await self._make_request(
                "PATCH",
                f"/v2/objects/deals/records/{did}",
                json_body={"data": {"values": values_ud}},
            )
        if operation == "create_note":
            po: str = str(d.get("parent_object", "") or "").strip()
            pr: str = str(d.get("parent_record_id", "") or "").strip()
            tl: str = str(d.get("title", "") or "").strip()
            content: str = str(d.get("content", "") or "").strip()
            fmt: str = str(d.get("format") or "plaintext").strip().lower()
            if fmt not in ("plaintext", "markdown"):
                fmt = "plaintext"
            if not po or not pr or not tl or not content:
                raise ValueError("create_note requires parent_object, parent_record_id, title, content")
            return await self._make_request(
                "POST",
                "/v2/notes",
                json_body={
                    "data": {
                        "parent_object": po,
                        "parent_record_id": pr,
                        "title": tl,
                        "format": fmt,
                        "content": content,
                    },
                },
            )
        if operation in ("delete_person", "delete_company", "delete_deal"):
            object_slug: str = {
                "delete_person": "people",
                "delete_company": "companies",
                "delete_deal": "deals",
            }[operation]
            id_key: str = {
                "delete_person": "person_id",
                "delete_company": "company_id",
                "delete_deal": "deal_id",
            }[operation]
            rid: str = str(d.pop(id_key, None) or d.pop("id", "") or "").strip()
            if not rid:
                raise ValueError(f"{operation} requires id")
            await self._make_request(
                "DELETE",
                f"/v2/objects/{object_slug}/records/{rid}",
            )
            return {"deleted": True, "id": rid, "object": object_slug}
        if operation == "delete_note":
            nid: str = str(d.pop("note_id", None) or d.pop("id", "") or "").strip()
            if not nid:
                raise ValueError("delete_note requires id")
            await self._make_request("DELETE", f"/v2/notes/{nid}")
            return {"deleted": True, "id": nid, "object": "notes"}
        raise ValueError(f"Unknown Attio write operation: {operation}")

    async def capture_before_state(self, operation: str, data: dict[str, Any]) -> dict[str, Any] | None:
        # Mapping of operations that target a specific record to the (object_slug, id_key)
        # used to fetch the current record state for the action ledger. Captures
        # both update_* (so we can show the diff) and delete_* (so the deletion
        # is recoverable / auditable).
        record_lookups: dict[str, tuple[str, str]] = {
            "update_person": ("people", "person_id"),
            "update_company": ("companies", "company_id"),
            "update_deal": ("deals", "deal_id"),
            "delete_person": ("people", "person_id"),
            "delete_company": ("companies", "company_id"),
            "delete_deal": ("deals", "deal_id"),
        }
        try:
            if operation in record_lookups:
                object_slug, id_key = record_lookups[operation]
                rid: str = str(data.get("id") or data.get(id_key) or "").strip()
                if rid:
                    return await self._make_request(
                        "GET", f"/v2/objects/{object_slug}/records/{rid}"
                    )
            if operation == "delete_note":
                nid: str = str(data.get("id") or data.get("note_id") or "").strip()
                if nid:
                    return await self._make_request("GET", f"/v2/notes/{nid}")
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------ ACTIONS

    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        raw: dict[str, Any] = dict(params)
        if action == "search_records":
            obj_s: str = str(raw.get("object", "") or "").strip()
            if not obj_s:
                raise ValueError("search_records requires params.object")
            body_sr: dict[str, Any] = {
                "limit": int(raw.get("limit", 50)),
                "offset": int(raw.get("offset", 0)),
            }
            if isinstance(raw.get("filter"), dict):
                body_sr["filter"] = raw["filter"]
            if isinstance(raw.get("sorts"), list):
                body_sr["sorts"] = raw["sorts"]
            return await self._make_request(
                "POST",
                f"/v2/objects/{obj_s}/records/query",
                json_body=body_sr,
            )
        if action == "get_record":
            obj_g: str = str(raw.get("object", "") or "").strip()
            rec_id: str = str(raw.get("id", "") or "").strip()
            if not obj_g or not rec_id:
                raise ValueError("get_record requires params.object and params.id")
            return await self._make_request("GET", f"/v2/objects/{obj_g}/records/{rec_id}")
        if action == "list_workspace_members":
            return await self._make_request("GET", "/v2/workspace_members")
        if action == "list_lists":
            return await self._make_request("GET", "/v2/lists")
        if action == "list_list_entries":
            lst: str = str(raw.get("list", "") or "").strip()
            if not lst:
                raise ValueError("list_list_entries requires params.list")
            body_le: dict[str, Any] = {
                "limit": int(raw.get("limit", 50)),
                "offset": int(raw.get("offset", 0)),
            }
            if isinstance(raw.get("filter"), dict):
                body_le["filter"] = raw["filter"]
            if isinstance(raw.get("sorts"), list):
                body_le["sorts"] = raw["sorts"]
            return await self._make_request(
                "POST",
                f"/v2/lists/{lst}/entries/query",
                json_body=body_le,
            )
        if action == "list_statuses":
            obj_ls: str = str(raw.get("object") or "deals").strip()
            attr_ls: str = str(raw.get("attribute") or "stage").strip()
            if not obj_ls or not attr_ls:
                raise ValueError("list_statuses requires non-empty object and attribute (or omit both for defaults deals/stage)")
            return await self._make_request(
                "GET",
                f"/v2/objects/{obj_ls}/attributes/{attr_ls}/statuses",
            )
        raise ValueError(f"Unknown Attio action: {action}")
