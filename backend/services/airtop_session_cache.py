"""Redis-backed ephemeral state for Airtop multi-step browser automation (session reuse)."""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis

from config import get_redis_connection_kwargs, settings

logger = logging.getLogger(__name__)

REDIS_KEY_SESSION: str = "airtop:browser:h:{handle}"
REDIS_KEY_ACTIVE: str = "airtop:browser:active:{org_id}:{user_id}:{integration_id}"

# Slightly under Airtop session timeout so keys disappear before the cloud session hard-expires.
DEFAULT_TTL_SECONDS: int = 19 * 60


@dataclass(frozen=True)
class AirtopBrowserReuseRecord:
    """Serialized session/window binding for one reuse handle."""

    organization_id: str
    owner_user_id: str
    integration_id: str
    session_id: str
    window_id: str


def _session_key(handle: str) -> str:
    return REDIS_KEY_SESSION.format(handle=handle)


def _active_key(organization_id: str, owner_user_id: str, integration_id: str) -> str:
    return REDIS_KEY_ACTIVE.format(
        org_id=organization_id,
        user_id=owner_user_id,
        integration_id=integration_id,
    )


def _record_to_dict(rec: AirtopBrowserReuseRecord) -> dict[str, str]:
    return {
        "organization_id": rec.organization_id,
        "owner_user_id": rec.owner_user_id,
        "integration_id": rec.integration_id,
        "session_id": rec.session_id,
        "window_id": rec.window_id,
    }


def _dict_to_record(data: dict[str, Any]) -> AirtopBrowserReuseRecord | None:
    try:
        return AirtopBrowserReuseRecord(
            organization_id=str(data["organization_id"]),
            owner_user_id=str(data["owner_user_id"]),
            integration_id=str(data["integration_id"]),
            session_id=str(data["session_id"]),
            window_id=str(data["window_id"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def new_reuse_handle() -> str:
    """Opaque handle for the agent to pass on subsequent tool calls."""
    return secrets.token_urlsafe(32)


async def get_record(handle: str) -> AirtopBrowserReuseRecord | None:
    """Load a reuse record by handle, or None if missing/expired."""
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )
    try:
        async with redis_client:
            raw: str | None = await redis_client.get(_session_key(handle))
    except Exception as exc:
        logger.warning("Airtop reuse Redis get failed handle=%s: %s", handle[:12], exc)
        return None
    if not raw:
        return None
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _dict_to_record(data)


async def get_active_handle(
    organization_id: str, owner_user_id: str, integration_id: str
) -> str | None:
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )
    try:
        async with redis_client:
            h: str | None = await redis_client.get(_active_key(organization_id, owner_user_id, integration_id))
    except Exception as exc:
        logger.warning("Airtop reuse Redis active get failed: %s", exc)
        return None
    return h.strip() if h else None


async def save_record(
    handle: str,
    record: AirtopBrowserReuseRecord,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )
    payload: str = json.dumps(_record_to_dict(record))
    async with redis_client:
        await redis_client.set(_session_key(handle), payload, ex=ttl_seconds)
        await redis_client.set(
            _active_key(record.organization_id, record.owner_user_id, record.integration_id),
            handle,
            ex=ttl_seconds,
        )


async def refresh_ttl(
    handle: str,
    organization_id: str,
    owner_user_id: str,
    integration_id: str,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    """Sliding TTL after a successful run_in_session."""
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )
    async with redis_client:
        await redis_client.expire(_session_key(handle), ttl_seconds)
        await redis_client.expire(_active_key(organization_id, owner_user_id, integration_id), ttl_seconds)


async def delete_record_and_active(
    handle: str,
    organization_id: str,
    owner_user_id: str,
    integration_id: str,
) -> None:
    """Remove handle payload and clear active pointer if it still points at this handle."""
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )
    active_k: str = _active_key(organization_id, owner_user_id, integration_id)
    async with redis_client:
        current: str | None = await redis_client.get(active_k)
        await redis_client.delete(_session_key(handle))
        if current and current.strip() == handle:
            await redis_client.delete(active_k)
