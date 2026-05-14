"""
Airtop connector — one Integration row per saved authenticated site.

Use the Connectors UI (or POST /api/connectors/airtop/connect) to start a login session; finish saves
the Airtop profile. Agent actions: run_task, extract_structured, re_authenticate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified

from connectors.account_metadata import AccountMetadata
from connectors.airtop_ops import (
    create_session_window_live_view,
    run_page_query,
    save_profile_and_terminate,
    terminate_session,
)
from connectors.base import BaseConnector
from connectors.registry import (
    AuthType,
    Capability,
    ConnectorAction,
    ConnectorMeta,
    ConnectorScope,
)
from models.database import get_session
from models.integration import Integration

logger = logging.getLogger(__name__)

PROFILE_STATUS_PENDING: str = "pending"
PROFILE_STATUS_SAVED: str = "saved"
PROFILE_STATUS_PENDING_REAUTH: str = "pending_reauth"


class AirtopConnector(BaseConnector):
    """One connected site = one integration row (account_identifier set, extra_data has profile)."""

    source_system: str = "airtop"

    meta = ConnectorMeta(
        name="Airtop",
        slug="airtop",
        description=(
            "Cloud browser sessions with one saved login per connected site. "
            "Add sites from Connectors, then use run_on_connector with the account label matching that site."
        ),
        auth_type=AuthType.CUSTOM,
        scope=ConnectorScope.USER,
        capabilities=[Capability.ACTION],
        auth_fields=[],
        actions=[
            ConnectorAction(
                name="run_task",
                description=(
                    "Open a URL using this site's saved Airtop profile and run a natural-language task. "
                    "Returns the model's text answer."
                ),
                parameters=[
                    {"name": "url", "type": "string", "required": True, "description": "https URL to open"},
                    {"name": "instructions", "type": "string", "required": True, "description": "What to do on the page"},
                    {
                        "name": "timeout_seconds",
                        "type": "integer",
                        "required": False,
                        "description": "Soft time threshold for the AI step (Airtop page-query); HTTP wait up to 5 min",
                    },
                ],
            ),
            ConnectorAction(
                name="extract_structured",
                description="Same as run_task but supply output_schema (JSON Schema object or string) for structured JSON.",
                parameters=[
                    {"name": "url", "type": "string", "required": True},
                    {"name": "instructions", "type": "string", "required": True},
                    {"name": "output_schema", "type": "object", "required": True, "description": "JSON Schema as object or string"},
                ],
            ),
            ConnectorAction(
                name="re_authenticate",
                description=(
                    "Start a new live-view session with the saved profile at the site's target URL so the user can "
                    "refresh cookies. Persists pending session on this integration; call POST "
                    "/api/connectors/airtop/{integration_id}/finish when done (or cancel)."
                ),
                parameters=[],
            ),
        ],
        usage_guide=(
            "Each Airtop site is a separate connector card. Use run_on_connector(connector='airtop', account='<account_label>', "
            "action='run_task', params={url, instructions}). For JSON, use action extract_structured with output_schema. "
            "If cookies expire, action re_authenticate then complete login in the live view and call the finish endpoint."
        ),
    )

    async def get_oauth_token(self) -> tuple[str, str]:
        key: str = await self._get_api_key()
        return key, ""

    async def fetch_account_metadata(self) -> AccountMetadata:
        label: str | None = None
        if self._integration and self._integration.account_label:
            label = str(self._integration.account_label).strip() or None
        ident: str = label or (self._integration.account_identifier if self._integration else None) or "airtop"
        return AccountMetadata(identifier=ident, label=label or "Airtop", avatar_url=None)

    async def _get_api_key(self) -> str:
        if not self._integration:
            await self._load_integration()
        if not self._integration:
            raise ValueError("No Airtop integration row loaded")
        extra: dict[str, Any] = self._integration.extra_data or {}
        raw: Any = extra.get("api_key")
        key: str = (str(raw).strip() if raw is not None else "") or ""
        if not key:
            raise ValueError("Airtop integration missing api_key in extra_data")
        return key

    def _profile_payload(self) -> dict[str, Any]:
        if not self._integration:
            return {}
        return dict(self._integration.extra_data or {})

    async def _require_saved_site(self) -> tuple[str, str, str]:
        """Return (api_key, profile_name, target_url) when profile is saved."""
        extra = self._profile_payload()
        status: str = str(extra.get("profile_status") or "").strip()
        if status not in (PROFILE_STATUS_SAVED,):
            raise ValueError(
                "This Airtop site is not ready (profile not saved). Finish setup in Connectors or wait for save to complete."
            )
        profile_name: str = str(extra.get("profile_name") or "").strip()
        target_url: str = str(extra.get("target_url") or "").strip()
        if not profile_name:
            raise ValueError("Airtop integration missing profile_name")
        if not target_url.startswith(("http://", "https://")):
            raise ValueError("Airtop integration missing valid target_url")
        api_key: str = await self._get_api_key()
        return api_key, profile_name, target_url

    async def _patch_extra(self, mutator: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        if not self._integration or not self._integration.id:
            await self._load_integration()
        if not self._integration or not self._integration.id:
            raise ValueError("No integration to update")
        iid: UUID = self._integration.id
        async with get_session(organization_id=self.organization_id) as session:
            row: Integration | None = await session.get(Integration, iid)
            if not row:
                raise ValueError("Integration row not found")
            base: dict[str, Any] = dict(row.extra_data or {})
            new_extra: dict[str, Any] = mutator(base)
            row.extra_data = new_extra
            flag_modified(row, "extra_data")
            row.updated_at = datetime.utcnow()
            await session.commit()
        await self._load_integration()

    async def sync_deals(self) -> int:
        return 0

    async def sync_accounts(self) -> int:
        return 0

    async def sync_contacts(self) -> int:
        return 0

    async def sync_activities(self) -> int:
        return 0

    async def fetch_deal(self, deal_id: str) -> dict[str, Any]:
        return {}

    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "run_task":
            return await self._run_task(params, structured=False)
        if action == "extract_structured":
            return await self._run_task(params, structured=True)
        if action == "re_authenticate":
            return await self._re_authenticate()
        raise ValueError(f"Unknown action: {action}")

    async def _run_task(self, params: dict[str, Any], *, structured: bool) -> dict[str, Any]:
        url: str = (params.get("url") or "").strip()
        instructions: str = (params.get("instructions") or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"error": "url must be an http(s) URL"}
        if not instructions:
            return {"error": "instructions is required"}

        api_key: str
        profile_name: str
        _target: str
        try:
            api_key, profile_name, _target = await self._require_saved_site()
        except ValueError as exc:
            return {"error": str(exc)}

        output_schema: str | dict[str, Any] | None = None
        if structured:
            raw_schema: Any = params.get("output_schema")
            if raw_schema is None:
                return {"error": "output_schema is required for extract_structured"}
            if isinstance(raw_schema, str):
                output_schema = raw_schema.strip() or None
            elif isinstance(raw_schema, dict):
                output_schema = raw_schema
            else:
                return {"error": "output_schema must be a string or object"}
            if not output_schema:
                return {"error": "output_schema is empty"}

        tts: int | None = None
        raw_to: Any = params.get("timeout_seconds")
        if raw_to is not None:
            try:
                tts = int(raw_to)
            except (TypeError, ValueError):
                tts = None

        req_timeout: float = 300.0
        try:
            out = await run_page_query(
                api_key,
                profile_name=profile_name,
                url=url,
                prompt=instructions,
                output_schema=output_schema,
                time_threshold_seconds=tts,
                request_timeout_seconds=req_timeout,
                session_timeout_minutes=20,
            )
            return {"status": "completed", **out}
        except Exception as exc:
            logger.warning("Airtop run_task failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    async def _re_authenticate(self) -> dict[str, Any]:
        extra = self._profile_payload()
        status: str = str(extra.get("profile_status") or "").strip()
        if status != PROFILE_STATUS_SAVED:
            return {"error": "Site must be in saved state before re-authentication"}
        profile_name: str = str(extra.get("profile_name") or "").strip()
        target_url: str = str(extra.get("target_url") or "").strip()
        if not profile_name or not target_url.startswith(("http://", "https://")):
            return {"error": "Missing profile_name or target_url on integration"}
        api_key: str = await self._get_api_key()

        try:
            session_id, _window_id, live_url = await create_session_window_live_view(
                api_key,
                initial_url=target_url,
                profile_name=profile_name,
                timeout_minutes=30,
                client_timeout=180.0,
            )
        except Exception as exc:
            return {"error": f"Failed to start Airtop session: {exc}"}

        async def mutator(base: dict[str, Any]) -> dict[str, Any]:
            merged = dict(base)
            merged["airtop_session_id"] = session_id
            merged["profile_status"] = PROFILE_STATUS_PENDING_REAUTH
            return merged

        await self._patch_extra(mutator)
        return {
            "status": "pending_reauth",
            "live_view_url": live_url,
            "session_id": session_id,
            "message": (
                "Open live_view_url, complete login refresh, then POST "
                "/api/connectors/airtop/{this_integration_id}/finish — or cancel."
            ),
            "integration_id": str(self._integration.id) if self._integration else None,
        }
