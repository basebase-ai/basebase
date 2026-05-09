"""Redis-backed hot cache for conversation model context."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from config import get_redis_connection_kwargs, settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
CONVERSATION_CONTEXT_TTL_SECONDS = 60 * 60 * 24
CONVERSATION_CONTEXT_MAX_MESSAGES = 40
_REDIS_RETRY_COUNT = 2


def _conversation_key(*, organization_id: str, conversation_id: str) -> str:
    return f"ctx:v{SCHEMA_VERSION}:conversation:{organization_id}:{conversation_id}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> str:
    return str(value)


def _sanitize_content(content: Any) -> Any:
    """Keep cached context JSON-safe and avoid storing raw attachment bytes/base64."""
    if isinstance(content, list):
        sanitized: list[Any] = []
        for block in content:
            if not isinstance(block, dict):
                sanitized.append(block)
                continue
            block_type = block.get("type")
            source = block.get("source")
            if block_type in {"image", "document"} and isinstance(source, dict) and source.get("data"):
                label = block.get("title") or block_type or "attachment"
                sanitized.append({
                    "type": "text",
                    "text": f"[Cached attachment reference: {label}; raw bytes omitted from hot cache]",
                })
                continue
            sanitized.append({key: _sanitize_content(value) for key, value in block.items()})
        return sanitized
    if isinstance(content, dict):
        return {key: _sanitize_content(value) for key, value in content.items()}
    return content


def _sanitize_message(message: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(message)
    if "content" in sanitized:
        sanitized["content"] = _sanitize_content(sanitized["content"])
    return sanitized


def _message_id(entry: dict[str, Any]) -> str:
    value = entry.get("message_id") or entry.get("id") or ""
    return str(value)


def _trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(messages) <= CONVERSATION_CONTEXT_MAX_MESSAGES:
        return messages
    return messages[-CONVERSATION_CONTEXT_MAX_MESSAGES:]


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(str(raw))
    except Exception:
        logger.warning("[context_cache.conversation] invalid_json")
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    return payload


def build_conversation_payload(
    *,
    organization_id: str,
    conversation_id: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    trimmed_messages = _trim_messages(
        [_sanitize_message(msg) for msg in messages if isinstance(msg, dict)]
    )
    latest_message_id = ""
    for entry in reversed(trimmed_messages):
        latest_message_id = _message_id(entry)
        if latest_message_id:
            break
    return {
        "schema_version": SCHEMA_VERSION,
        "organization_id": organization_id,
        "conversation_id": conversation_id,
        "latest_message_id": latest_message_id,
        "messages": trimmed_messages,
        "message_count": len(trimmed_messages),
        "updated_at": _utc_now_iso(),
    }


async def _redis_client() -> aioredis.Redis:
    return aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )


async def get_cached_history(
    *,
    organization_id: str | None,
    conversation_id: str | None,
) -> list[dict[str, Any]] | None:
    if not organization_id or not conversation_id:
        return None
    key = _conversation_key(organization_id=organization_id, conversation_id=conversation_id)
    try:
        redis_client = await _redis_client()
        async with redis_client:
            raw = await redis_client.get(key)
            payload = _parse_payload(raw)
            if payload is None:
                logger.info(
                    "[context_cache.conversation] miss organization_id=%s conversation_id=%s",
                    organization_id,
                    conversation_id,
                )
                return None
            await redis_client.expire(key, CONVERSATION_CONTEXT_TTL_SECONDS)
            messages = [dict(msg) for msg in payload.get("messages", []) if isinstance(msg, dict)]
            logger.info(
                "[context_cache.conversation] hit organization_id=%s conversation_id=%s messages=%d",
                organization_id,
                conversation_id,
                len(messages),
            )
            return messages
    except Exception as exc:
        logger.warning(
            "[context_cache.conversation] read_failed organization_id=%s conversation_id=%s error=%s",
            organization_id,
            conversation_id,
            exc,
        )
        return None


async def set_cached_history(
    *,
    organization_id: str | None,
    conversation_id: str | None,
    messages: list[dict[str, Any]],
) -> None:
    if not organization_id or not conversation_id:
        return
    key = _conversation_key(organization_id=organization_id, conversation_id=conversation_id)
    payload = build_conversation_payload(
        organization_id=organization_id,
        conversation_id=conversation_id,
        messages=messages,
    )
    try:
        redis_client = await _redis_client()
        async with redis_client:
            await redis_client.set(
                key,
                json.dumps(payload, default=_json_default),
                ex=CONVERSATION_CONTEXT_TTL_SECONDS,
            )
        logger.info(
            "[context_cache.conversation] set organization_id=%s conversation_id=%s messages=%d ttl=%d",
            organization_id,
            conversation_id,
            len(payload["messages"]),
            CONVERSATION_CONTEXT_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "[context_cache.conversation] set_failed organization_id=%s conversation_id=%s error=%s",
            organization_id,
            conversation_id,
            exc,
        )


async def get_or_rebuild_history(
    *,
    organization_id: str | None,
    conversation_id: str | None,
    rebuild: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    cached = await get_cached_history(
        organization_id=organization_id,
        conversation_id=conversation_id,
    )
    if cached is not None:
        return cached

    history = await rebuild()
    await set_cached_history(
        organization_id=organization_id,
        conversation_id=conversation_id,
        messages=history,
    )
    return history


async def append_message(
    *,
    organization_id: str | None,
    conversation_id: str | None,
    message: dict[str, Any],
) -> None:
    if not organization_id or not conversation_id or not isinstance(message, dict):
        return
    key = _conversation_key(organization_id=organization_id, conversation_id=conversation_id)
    message_id = _message_id(message)
    for attempt in range(_REDIS_RETRY_COUNT + 1):
        try:
            redis_client = await _redis_client()
            async with redis_client:
                async with redis_client.pipeline() as pipe:
                    try:
                        await pipe.watch(key)
                        payload = _parse_payload(await pipe.get(key))
                        if payload is None:
                            await pipe.reset()
                            logger.info(
                                "[context_cache.conversation] append_skip_missing organization_id=%s conversation_id=%s message_id=%s",
                                organization_id,
                                conversation_id,
                                message_id,
                            )
                            return
                        messages = [dict(msg) for msg in payload.get("messages", []) if isinstance(msg, dict)]
                        if message_id:
                            messages = [entry for entry in messages if _message_id(entry) != message_id]
                        messages.append(_sanitize_message(message))
                        payload = build_conversation_payload(
                            organization_id=organization_id,
                            conversation_id=conversation_id,
                            messages=messages,
                        )
                        pipe.multi()
                        pipe.set(
                            key,
                            json.dumps(payload, default=_json_default),
                            ex=CONVERSATION_CONTEXT_TTL_SECONDS,
                        )
                        await pipe.execute()
                        logger.info(
                            "[context_cache.conversation] append organization_id=%s conversation_id=%s message_id=%s messages=%d",
                            organization_id,
                            conversation_id,
                            message_id,
                            len(payload["messages"]),
                        )
                        return
                    except aioredis.WatchError:
                        logger.info(
                            "[context_cache.conversation] append_conflict organization_id=%s conversation_id=%s attempt=%d",
                            organization_id,
                            conversation_id,
                            attempt + 1,
                        )
                        continue
        except Exception as exc:
            logger.warning(
                "[context_cache.conversation] append_failed organization_id=%s conversation_id=%s message_id=%s error=%s",
                organization_id,
                conversation_id,
                message_id,
                exc,
            )
            return
