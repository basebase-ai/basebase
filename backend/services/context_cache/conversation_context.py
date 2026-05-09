"""Small Redis hot cache for conversation model context."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from config import get_redis_connection_kwargs, settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TTL_SECONDS = 60 * 60 * 24
MAX_MESSAGES = 40


def _key(org_id: str, conversation_id: str) -> str:
    return f"ctx:v{SCHEMA_VERSION}:conversation:{org_id}:{conversation_id}"


def _client() -> aioredis.Redis:
    return aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )


def _loads(raw: Any) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw)) if raw else None
    except Exception:
        logger.warning("[context_cache.conversation] invalid_json")
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    return payload if isinstance(payload.get("messages"), list) else None


def _attachment_note(block: dict[str, Any]) -> dict[str, str]:
    label = block.get("title") or block.get("type") or "attachment"
    return {
        "type": "text",
        "text": f"[Cached attachment reference: {label}; raw bytes omitted from hot cache]",
    }


def _safe(value: Any) -> Any:
    """Keep Redis JSON small: preserve references, not raw image/PDF base64 bytes."""
    if isinstance(value, list):
        return [_attachment_note(v) if _has_inline_bytes(v) else _safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    return value


def _has_inline_bytes(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") in {"image", "document"}
        and isinstance(value.get("source"), dict)
        and bool(value["source"].get("data"))
    )


def _message_id(message: dict[str, Any]) -> str:
    return str(message.get("message_id") or message.get("id") or "")


def build_conversation_payload(
    *, org_id: str | None = None, organization_id: str | None = None,
    conversation_id: str, messages: list[dict[str, Any]],
) -> dict[str, Any]:
    safe_messages = []
    for message in messages[-MAX_MESSAGES:]:
        if isinstance(message, dict):
            copied = dict(message)
            if "content" in copied:
                copied["content"] = _safe(copied["content"])
            safe_messages.append(copied)
    return {
        "schema_version": SCHEMA_VERSION,
        "organization_id": organization_id or org_id,
        "conversation_id": conversation_id,
        "latest_message_id": next((_message_id(m) for m in reversed(safe_messages) if _message_id(m)), ""),
        "messages": safe_messages,
        "updated_at": datetime.now(UTC).isoformat(),
    }


async def get_or_rebuild_history(
    *,
    organization_id: str | None,
    conversation_id: str | None,
    rebuild: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    if not organization_id or not conversation_id:
        return await rebuild()
    cache_key = _key(organization_id, conversation_id)
    try:
        redis_client = _client()
        async with redis_client:
            payload = _loads(await redis_client.get(cache_key))
            if payload is not None:
                await redis_client.expire(cache_key, TTL_SECONDS)
                messages = [m for m in payload["messages"] if isinstance(m, dict)]
                logger.info(
                    "[context_cache.conversation] hit conversation_id=%s messages=%d",
                    conversation_id,
                    len(messages),
                )
                return messages
    except Exception as exc:
        logger.warning("[context_cache.conversation] read_failed conversation_id=%s error=%s", conversation_id, exc)

    history = await rebuild()
    await set_cached_history(organization_id=organization_id, conversation_id=conversation_id, messages=history)
    return history


async def set_cached_history(
    *, organization_id: str | None, conversation_id: str | None, messages: list[dict[str, Any]],
) -> None:
    if not organization_id or not conversation_id:
        return
    try:
        redis_client = _client()
        async with redis_client:
            await redis_client.set(
                _key(organization_id, conversation_id),
                json.dumps(build_conversation_payload(
                    organization_id=organization_id,
                    conversation_id=conversation_id,
                    messages=messages,
                ), default=str),
                ex=TTL_SECONDS,
            )
    except Exception as exc:
        logger.warning("[context_cache.conversation] set_failed conversation_id=%s error=%s", conversation_id, exc)


async def append_message(
    *, organization_id: str | None, conversation_id: str | None, message: dict[str, Any],
) -> None:
    """Best-effort write-through append after DB commit; DB remains authoritative."""
    if not organization_id or not conversation_id or not isinstance(message, dict):
        return
    cache_key = _key(organization_id, conversation_id)
    try:
        redis_client = _client()
        async with redis_client:
            payload = _loads(await redis_client.get(cache_key))
            if payload is None:
                return
            messages = [m for m in payload["messages"] if isinstance(m, dict)]
            new_id = _message_id(message)
            if new_id:
                messages = [m for m in messages if _message_id(m) != new_id]
            messages.append(message)
            await redis_client.set(
                cache_key,
                json.dumps(build_conversation_payload(
                    organization_id=organization_id,
                    conversation_id=conversation_id,
                    messages=messages,
                ), default=str),
                ex=TTL_SECONDS,
            )
    except Exception as exc:
        logger.warning("[context_cache.conversation] append_failed conversation_id=%s error=%s", conversation_id, exc)
