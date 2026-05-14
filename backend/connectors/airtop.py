"""
Airtop connector — one Integration row per saved authenticated site.

Use the Connectors UI (or POST /api/connectors/airtop/connect) to start a login session; the server must have
AIRTOP_KEY set. Finish saves the Airtop profile. Actions include run_task, session reuse (open_browser / run_in_session / close_browser), extract_structured, re_authenticate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm.attributes import flag_modified

from config import resolve_airtop_api_key
from connectors.account_metadata import AccountMetadata
from connectors.airtop_ops import (
    create_session_window_live_view,
    load_window_url,
    page_query_on_window,
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
from services.airtop_session_cache import (
    AirtopBrowserReuseRecord,
    delete_record_and_active,
    get_active_handle,
    get_record,
    new_reuse_handle,
    save_record,
)

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
                    "Single-shot: open a URL, run one query, terminate. Use ONLY when you are certain one page load "
                    "and one query is enough. For anything requiring navigation, clicking, or multiple steps, "
                    "use open_browser + run_in_session + close_browser instead."
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
            ConnectorAction(
                name="open_browser",
                description=(
                    "Start a reusable Airtop browser for this saved site. Returns session_handle and live_view_url. "
                    "DEFAULT for any task that requires navigating pages, clicking, or more than one query — "
                    "cheaper and faster than repeated run_task calls because the session stays alive."
                ),
                parameters=[
                    {
                        "name": "url",
                        "type": "string",
                        "required": False,
                        "description": "Initial https URL (defaults to the site's saved target_url)",
                    },
                    {
                        "name": "session_timeout_minutes",
                        "type": "integer",
                        "required": False,
                        "description": "Airtop session lifetime 5–120; default 20",
                    },
                ],
            ),
            ConnectorAction(
                name="run_in_session",
                description=(
                    "Run a natural-language step in an existing browser session opened with open_browser. "
                    "Optional url navigates the same window before the step. Optional output_schema for JSON extraction."
                ),
                parameters=[
                    {"name": "session_handle", "type": "string", "required": True},
                    {"name": "instructions", "type": "string", "required": True},
                    {"name": "url", "type": "string", "required": False, "description": "If set, navigate this window first"},
                    {"name": "timeout_seconds", "type": "integer", "required": False},
                    {
                        "name": "output_schema",
                        "type": "object",
                        "required": False,
                        "description": "If set, structured JSON output (JSON Schema object or string)",
                    },
                ],
            ),
            ConnectorAction(
                name="close_browser",
                description="End a reusable browser session started with open_browser. Always call when done to free resources.",
                parameters=[{"name": "session_handle", "type": "string", "required": True}],
            ),
        ],
        usage_guide=(
            "Each Airtop site is a separate connector card. "
            "IMPORTANT: When the task involves more than one page load or step (e.g. search then click a result, "
            "navigate then extract, or any sequence of actions), ALWAYS use the session-reuse flow: "
            "open_browser first, then run_in_session for each step (pass url to navigate between pages), "
            "then close_browser when done. This is faster, cheaper, and keeps the login cookie alive across steps.\n\n"
            "Session-reuse flow:\n"
            "1. run_on_connector(connector='airtop', account='<label>', action='open_browser')\n"
            "2. run_on_connector(connector='airtop', account='<label>', action='run_in_session', "
            "params={session_handle, instructions, url (optional — navigates before querying)})\n"
            "3. Repeat step 2 as needed for additional steps\n"
            "4. run_on_connector(connector='airtop', account='<label>', action='close_browser', params={session_handle})\n\n"
            "Only use run_task for truly single-shot queries where you are certain one page load + one query is enough. "
            "When in doubt, prefer open_browser.\n\n"
            "Structured JSON: pass output_schema in run_in_session (reuse) or use extract_structured (single-shot). "
            "If cookies expire: re_authenticate then POST /api/connectors/airtop/{integration_id}/finish."
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
        try:
            return resolve_airtop_api_key(extra)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    def _profile_payload(self) -> dict[str, Any]:
        if not self._integration:
            return {}
        return dict(self._integration.extra_data or {})

    async def _require_saved_site(self) -> tuple[str, str, str]:
        """Return (api_key, profile_name, target_url) when profile is saved."""
        if not self._integration:
            await self._load_integration()
        if not self._integration:
            raise ValueError(
                "No Airtop integration found for this user. Add a site from Connectors first."
            )
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
        if action == "open_browser":
            return await self._open_browser(params)
        if action == "run_in_session":
            return await self._run_in_session(params)
        if action == "close_browser":
            return await self._close_browser(params)
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

    def _redis_ttl_seconds(self, session_timeout_minutes: int) -> int:
        mins: int = max(5, min(session_timeout_minutes, 120))
        return max(120, mins * 60 - 30)

    async def _open_browser(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            api_key: str
            profile_name: str
            target_url: str
            api_key, profile_name, target_url = await self._require_saved_site()
        except ValueError as exc:
            return {"error": str(exc)}
        if not self._integration or not self._integration.id:
            return {"error": "No integration row"}
        org_id: str = self.organization_id
        owner_user_id: str = self.user_id or ""
        int_id: str = str(self._integration.id)
        raw_tm: Any = params.get("session_timeout_minutes")
        session_timeout_minutes: int = 20
        if raw_tm is not None:
            try:
                session_timeout_minutes = int(raw_tm)
            except (TypeError, ValueError):
                session_timeout_minutes = 20
        session_timeout_minutes = max(5, min(session_timeout_minutes, 120))

        initial_url: str = (params.get("url") or "").strip() or target_url
        if not initial_url.startswith(("http://", "https://")):
            return {"error": "url must be an http(s) URL or set a valid target_url on the integration"}

        old_handle: str | None = await get_active_handle(org_id, owner_user_id, int_id)
        if old_handle:
            old_rec: AirtopBrowserReuseRecord | None = await get_record(old_handle)
            if old_rec:
                try:
                    await terminate_session(api_key, old_rec.session_id)
                except Exception as exc:
                    logger.warning("Airtop reuse: terminate previous session failed: %s", exc)
            await delete_record_and_active(old_handle, org_id, owner_user_id, int_id)

        try:
            session_id, window_id, live_url = await create_session_window_live_view(
                api_key,
                initial_url=initial_url,
                profile_name=profile_name,
                timeout_minutes=session_timeout_minutes,
                client_timeout=180.0,
            )
        except Exception as exc:
            logger.warning("Airtop open_browser failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

        handle: str = new_reuse_handle()
        record = AirtopBrowserReuseRecord(
            organization_id=org_id,
            owner_user_id=owner_user_id,
            integration_id=int_id,
            session_id=session_id,
            window_id=window_id,
        )
        ttl_sec: int = self._redis_ttl_seconds(session_timeout_minutes)
        try:
            await save_record(handle, record, ttl_seconds=ttl_sec)
        except Exception as exc:
            logger.warning("Airtop reuse: Redis save failed, terminating session: %s", exc)
            try:
                await terminate_session(api_key, session_id)
            except Exception:
                pass
            return {"error": f"Could not store session handle (Redis): {exc}"}

        return {
            "status": "opened",
            "session_handle": handle,
            "live_view_url": live_url,
            "expires_in_seconds": ttl_sec,
            "message": "Use run_in_session with this session_handle for further steps, then close_browser.",
        }

    async def _validate_reuse_record(self, record: AirtopBrowserReuseRecord | None) -> str | None:
        if record is None:
            return "Unknown or expired session_handle. Call open_browser again."
        if not self._integration:
            await self._load_integration()
        if not self._integration:
            return "No Airtop integration loaded"
        if record.organization_id != self.organization_id:
            return "session_handle does not belong to this organization"
        if record.owner_user_id != (self.user_id or ""):
            return "session_handle does not belong to this user"
        if record.integration_id != str(self._integration.id):
            return "session_handle does not match this connector site"
        return None

    async def _run_in_session(self, params: dict[str, Any]) -> dict[str, Any]:
        handle: str = (params.get("session_handle") or "").strip()
        if not handle:
            return {"error": "session_handle is required"}
        instructions: str = (params.get("instructions") or "").strip()
        if not instructions:
            return {"error": "instructions is required"}

        record: AirtopBrowserReuseRecord | None = await get_record(handle)
        err: str | None = await self._validate_reuse_record(record)
        if err or record is None:
            return {"error": err or "Invalid session"}

        api_key: str
        try:
            api_key = await self._get_api_key()
        except ValueError as exc:
            return {"error": str(exc)}

        nav_url: str = (params.get("url") or "").strip()
        if nav_url:
            if not nav_url.startswith(("http://", "https://")):
                return {"error": "url must be http(s)"}
            try:
                await load_window_url(
                    api_key,
                    session_id=record.session_id,
                    window_id=record.window_id,
                    url=nav_url,
                )
            except Exception as exc:
                logger.warning("Airtop run_in_session load_url failed: %s", exc, exc_info=True)
                return {"error": f"Navigation failed: {exc}"}

        output_schema: str | dict[str, Any] | None = None
        raw_schema: Any = params.get("output_schema")
        if raw_schema is not None:
            if isinstance(raw_schema, str):
                output_schema = raw_schema.strip() or None
            elif isinstance(raw_schema, dict):
                output_schema = raw_schema if raw_schema else None
            else:
                return {"error": "output_schema must be a string or object"}

        tts: int | None = None
        raw_to: Any = params.get("timeout_seconds")
        if raw_to is not None:
            try:
                tts = int(raw_to)
            except (TypeError, ValueError):
                tts = None

        req_timeout: float = 300.0
        try:
            out = await page_query_on_window(
                api_key,
                session_id=record.session_id,
                window_id=record.window_id,
                prompt=instructions,
                output_schema=output_schema,
                time_threshold_seconds=tts,
                request_timeout_seconds=req_timeout,
            )
            return {"status": "completed", "session_handle": handle, **out}
        except Exception as exc:
            logger.warning("Airtop run_in_session page_query failed: %s", exc, exc_info=True)
            return {"error": str(exc)}

    async def _close_browser(self, params: dict[str, Any]) -> dict[str, Any]:
        handle: str = (params.get("session_handle") or "").strip()
        if not handle:
            return {"error": "session_handle is required"}
        record: AirtopBrowserReuseRecord | None = await get_record(handle)
        err: str | None = await self._validate_reuse_record(record)
        if err or record is None:
            return {"error": err or "Invalid session"}

        api_key: str
        try:
            api_key = await self._get_api_key()
        except ValueError as exc:
            return {"error": str(exc)}

        try:
            await terminate_session(api_key, record.session_id)
        except Exception as exc:
            logger.warning("Airtop close_browser terminate failed: %s", exc)
        try:
            await delete_record_and_active(
                handle,
                record.organization_id,
                record.owner_user_id,
                record.integration_id,
            )
        except Exception as exc:
            logger.warning("Airtop close_browser Redis cleanup failed: %s", exc)
        return {"status": "closed", "session_handle": handle}

    async def _re_authenticate(self) -> dict[str, Any]:
        if not self._integration:
            await self._load_integration()
        if not self._integration:
            return {"error": "No Airtop integration found for this user."}
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
