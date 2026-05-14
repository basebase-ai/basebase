"""
Connector metadata and webhook endpoint.

- Serves the dynamically-discovered connector registry to the frontend.
- Single webhook route: POST /webhook/{provider}/{organization_id}. Connectors
  that support LISTEN and set webhook_secret_extra_data_key in meta handle
  verification and payload parsing; this route dispatches and emits workflow events.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm.attributes import flag_modified

from api.auth_middleware import AuthContext, get_current_auth, require_organization
from config import BUILTIN_CONNECTORS, get_provider_sharing_defaults, resolve_airtop_api_key, settings
from connectors.airtop_ops import create_session_window_live_view, save_profile_and_terminate, terminate_session
from connectors.registry import Capability, ConnectorMeta, discover_connectors
from models.database import get_admin_session, get_session
from models.integration import Integration
from models.user import User
from workers.events import emit_event

router = APIRouter()
logger = logging.getLogger(__name__)

def _connection_flow(meta: ConnectorMeta) -> str:
    """Return oauth | builtin | custom_credentials for the frontend connect flow.

    OAuth connectors go through Nango. Builtin connectors with user-provided
    credentials (mcp, ispot_tv) open a form; builtin connectors without
    credentials (apps, web_search, artifacts, twilio) are toggled server-side
    with no user input.
    """
    if meta.slug not in BUILTIN_CONNECTORS:
        return "oauth"
    if meta.slug == "airtop":
        return "custom_credentials"
    if meta.auth_fields:
        return "custom_credentials"
    return "builtin"


@router.get("")
async def list_connectors() -> list[dict[str, Any]]:
    """Return metadata for every registered connector."""
    registry = discover_connectors()
    result: list[dict[str, Any]] = []

    for slug, cls in sorted(registry.items()):
        meta = cls.meta  # type: ignore[attr-defined]
        sharing = get_provider_sharing_defaults(slug)
        result.append({
            "slug": meta.slug,
            "name": meta.name,
            "description": meta.description,
            "auth_type": meta.auth_type.value,
            "scope": meta.scope.value,
            "default_sharing": {
                "share_synced_data": sharing.share_synced_data,
                "share_query_access": sharing.share_query_access,
                "share_write_access": sharing.share_write_access,
            },
            "connection_flow": _connection_flow(meta),
            "entity_types": meta.entity_types,
            "capabilities": [c.value for c in meta.capabilities],
            "write_operations": [
                {"name": op.name, "entity_type": op.entity_type, "description": op.description}
                for op in meta.write_operations
            ],
            "actions": [
                {"name": a.name, "description": a.description}
                for a in meta.actions
            ],
            "event_types": [
                {"name": e.name, "description": e.description}
                for e in meta.event_types
            ],
            "query_description": meta.query_description,
            "auth_fields": [
                {"name": f.name, "label": f.label, "type": f.type, "required": f.required, "help_text": f.help_text}
                for f in meta.auth_fields
            ],
            "icon": meta.icon,
        })

    return result


@router.post("/webhook/{provider}/{organization_id}", response_model=None)
async def handle_connector_webhook(
    request: Request, provider: str, organization_id: str
) -> dict[str, str]:
    """
    Generic webhook endpoint for LISTEN connectors. URL format:
    https://<api>/api/connectors/webhook/<provider>/<organization_id>
    e.g. .../webhook/linear/<org_uuid>. Configure the provider's webhook to point
    here and store the signing secret in integration.extra_data under the key
    defined by the connector's meta.webhook_secret_extra_data_key.
    """
    raw_body: bytes = await request.body()
    headers_dict: dict[str, str] = dict(request.headers)

    try:
        org_uuid: UUID = UUID(organization_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid organization_id")

    registry: dict[str, type[Any]] = discover_connectors()
    connector_cls: type[Any] | None = registry.get(provider)
    if not connector_cls or not hasattr(connector_cls, "meta"):
        raise HTTPException(status_code=404, detail="Connector not found")
    meta = connector_cls.meta
    if Capability.LISTEN not in meta.capabilities or not meta.webhook_secret_extra_data_key:
        raise HTTPException(
            status_code=404,
            detail="Connector does not accept webhooks",
        )

    async with get_session(organization_id=organization_id) as session:
        result = await session.execute(
            select(Integration)
            .where(
                Integration.organization_id == org_uuid,
                Integration.connector == provider,
                Integration.is_active == True,  # noqa: E712
            )
            .order_by(Integration.updated_at.desc().nullslast())
            .limit(1)
        )
        integration: Integration | None = result.scalars().first()

    if not integration:
        logger.warning(
            "[connectors] No active %s integration for org %s", provider, organization_id
        )
        raise HTTPException(status_code=404, detail="Integration not found")

    extra: dict[str, Any] | None = integration.extra_data
    raw_secret: Any = (extra or {}).get(meta.webhook_secret_extra_data_key)
    secret: str | None = raw_secret if isinstance(raw_secret, str) and raw_secret else None
    if not secret:
        logger.warning(
            "[connectors] No webhook secret for %s org %s (key=%s)",
            provider,
            organization_id,
            meta.webhook_secret_extra_data_key,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Webhook secret not configured. Set extra_data.{meta.webhook_secret_extra_data_key}.",
        )

    request_url: str = str(request.url)
    if not connector_cls.verify_webhook(
        raw_body, headers_dict, secret, request_url=request_url
    ):
        logger.warning("[connectors] Invalid webhook signature for %s org %s", provider, organization_id)
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.warning("[connectors] Invalid webhook JSON (%s): %s", provider, e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events: list[tuple[str, dict[str, Any]]] = connector_cls.process_webhook_payload(payload)
    for event_type, data in events:
        await emit_event(
            event_type=event_type,
            organization_id=organization_id,
            data=data,
        )
        logger.info(
            "[connectors] Emitted %s for %s org %s",
            event_type,
            provider,
            organization_id,
        )

    return {"ok": "true"}


@router.head("/webhook/{provider}/{organization_id}", response_model=None)
async def handle_connector_webhook_head(
    provider: str, organization_id: str
) -> Response:
    """
    Trello (and others) send HTTP HEAD to verify the callback URL when creating a webhook.
    Return 200 when the connector supports LISTEN webhooks for this path.
    """
    try:
        UUID(organization_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid organization_id")

    registry: dict[str, type[Any]] = discover_connectors()
    connector_cls: type[Any] | None = registry.get(provider)
    if not connector_cls or not hasattr(connector_cls, "meta"):
        raise HTTPException(status_code=404, detail="Connector not found")
    meta = connector_cls.meta
    if Capability.LISTEN not in meta.capabilities or not meta.webhook_secret_extra_data_key:
        raise HTTPException(
            status_code=404,
            detail="Connector does not accept webhooks",
        )
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Airtop — one Integration row per saved site (multi-account)
# ---------------------------------------------------------------------------

PROFILE_PENDING: str = "pending"
PROFILE_SAVED: str = "saved"
PROFILE_PENDING_REAUTH: str = "pending_reauth"


class AirtopConnectBody(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=8, max_length=2048)


async def _airtop_reject_guest(user_id: UUID) -> None:
    async with get_admin_session() as session:
        user: User | None = await session.get(User, user_id)
        if user is None or bool(getattr(user, "is_guest", False)):
            raise HTTPException(status_code=403, detail="Guest users cannot connect integrations")


def _airtop_extra(row: Integration) -> dict[str, Any]:
    return dict(row.extra_data or {})


@router.post("/airtop/connect")
async def airtop_connect(
    body: AirtopConnectBody,
    auth: AuthContext = Depends(require_organization),
) -> dict[str, Any]:
    """Start interactive login: create pending Integration + Airtop session; returns live_view_url."""
    await _airtop_reject_guest(auth.user_id)
    org_uuid: UUID = auth.organization_id  # type: ignore[assignment]
    url: str = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must start with http:// or https://")

    env_key: str = (settings.AIRTOP_KEY or "").strip()
    if len(env_key) < 8:
        raise HTTPException(
            status_code=400,
            detail="Set AIRTOP_KEY in the server environment (minimum 8 characters) to add Airtop sites.",
        )

    profile_name: str = f"bb{uuid4().hex[:24]}"
    account_identifier: str = f"airtop_{uuid4().hex[:12]}"

    try:
        session_id, _wid, live_view_url = await create_session_window_live_view(
            env_key,
            initial_url=url,
            profile_name=None,
            timeout_minutes=30,
            client_timeout=180.0,
        )
    except Exception as exc:
        logger.warning("Airtop connect session failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Airtop error: {exc}") from exc

    sharing = get_provider_sharing_defaults("airtop")
    extra_data: dict[str, Any] = {
        "profile_name": profile_name,
        "target_url": url,
        "profile_status": PROFILE_PENDING,
        "airtop_session_id": session_id,
    }

    async with get_session(organization_id=str(org_uuid)) as session:
        await session.execute(text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": str(org_uuid)})
        row = Integration(
            organization_id=org_uuid,
            connector="airtop",
            provider="airtop",
            user_id=auth.user_id,
            scope="user",
            nango_connection_id="builtin",
            connected_by_user_id=auth.user_id,
            is_active=False,
            account_identifier=account_identifier,
            account_label=body.label.strip(),
            extra_data=extra_data,
            share_synced_data=sharing.share_synced_data,
            share_query_access=sharing.share_query_access,
            share_write_access=sharing.share_write_access,
            pending_sharing_config=False,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        new_integration_id: str = str(row.id)

    return {
        "integration_id": new_integration_id,
        "live_view_url": live_view_url,
        "profile_name": profile_name,
        "account_identifier": account_identifier,
    }


@router.post("/airtop/{integration_id}/finish")
async def airtop_finish(
    integration_id: UUID,
    auth: AuthContext = Depends(require_organization),
) -> dict[str, str]:
    await _airtop_reject_guest(auth.user_id)
    org_uuid: UUID = auth.organization_id  # type: ignore[assignment]

    async with get_session(organization_id=str(org_uuid)) as session:
        await session.execute(text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": str(org_uuid)})
        row: Integration | None = await session.get(Integration, integration_id)
        if (
            row is None
            or row.organization_id != org_uuid
            or row.user_id != auth.user_id
            or row.connector != "airtop"
        ):
            raise HTTPException(status_code=404, detail="Integration not found")
        extra = _airtop_extra(row)
        status: str = str(extra.get("profile_status") or "").strip()
        if status not in (PROFILE_PENDING, PROFILE_PENDING_REAUTH):
            raise HTTPException(status_code=400, detail="Integration is not awaiting finish")
        sid: str | None = (extra.get("airtop_session_id") or "").strip() or None
        profile_name: str = (extra.get("profile_name") or "").strip()
        try:
            key: str = resolve_airtop_api_key(extra)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not sid or not profile_name or not key:
            raise HTTPException(status_code=400, detail="Integration is missing session or profile data")

        try:
            await save_profile_and_terminate(key, sid, profile_name)
        except Exception as exc:
            logger.warning("Airtop finish failed integration=%s: %s", integration_id, exc, exc_info=True)
            raise HTTPException(status_code=400, detail=f"Airtop error: {exc}") from exc

        extra2 = dict(extra)
        extra2["profile_status"] = PROFILE_SAVED
        extra2.pop("airtop_session_id", None)
        row.extra_data = extra2
        flag_modified(row, "extra_data")
        row.is_active = True
        row.last_error = None
        row.updated_at = datetime.utcnow()
        await session.commit()

    return {"status": "saved", "integration_id": str(integration_id)}


@router.post("/airtop/{integration_id}/cancel")
async def airtop_cancel(
    integration_id: UUID,
    auth: AuthContext = Depends(require_organization),
) -> dict[str, str]:
    await _airtop_reject_guest(auth.user_id)
    org_uuid: UUID = auth.organization_id  # type: ignore[assignment]

    async with get_session(organization_id=str(org_uuid)) as session:
        await session.execute(text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": str(org_uuid)})
        row: Integration | None = await session.get(Integration, integration_id)
        if (
            row is None
            or row.organization_id != org_uuid
            or row.user_id != auth.user_id
            or row.connector != "airtop"
        ):
            raise HTTPException(status_code=404, detail="Integration not found")
        extra = _airtop_extra(row)
        status: str = str(extra.get("profile_status") or "").strip()
        sid: str | None = (extra.get("airtop_session_id") or "").strip() or None
        try:
            key: str = resolve_airtop_api_key(extra)
        except ValueError:
            key = ""

        if sid and key:
            try:
                await terminate_session(key, sid)
            except Exception as exc:
                logger.warning("Airtop cancel terminate failed: %s", exc)

        if status == PROFILE_PENDING:
            await session.delete(row)
            await session.commit()
            return {"status": "deleted"}

        if status == PROFILE_PENDING_REAUTH:
            extra2 = dict(extra)
            extra2["profile_status"] = PROFILE_SAVED
            extra2.pop("airtop_session_id", None)
            row.extra_data = extra2
            flag_modified(row, "extra_data")
            row.updated_at = datetime.utcnow()
            await session.commit()
            return {"status": "reauth_cancelled"}

    raise HTTPException(status_code=400, detail="Nothing to cancel for this integration")
