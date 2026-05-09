"""Small Redis hot cache for public Slack channel context."""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from config import get_redis_connection_kwargs, settings
from messengers.base import MessageType

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TTL_SECONDS = 60 * 60 * 24
MAX_MESSAGES = 250
_FILE_KEYS = ("id", "name", "title", "url_private_download", "url_private", "permalink", "mimetype")
_BLOCKED_TYPES = {"im", "mpim", "direct", "direct_message", "dm", "group", "groupchat", "private_channel"}


def is_public_slack_channel_context_eligible(
    *, channel_id: str | None, channel_type: str | None,
    conversation_type: str | None = None, message_type: MessageType | str | None = None,
) -> bool:
    channel = str(channel_id or "").strip().upper()
    kind = str(channel_type or "").strip().lower()
    conv_kind = str(conversation_type or "").strip().lower()
    msg_kind = (message_type.value if isinstance(message_type, MessageType) else str(message_type or "")).lower()
    return bool(
        channel
        and not channel.startswith(("D", "G"))
        and kind not in _BLOCKED_TYPES
        and conv_kind not in _BLOCKED_TYPES
        and msg_kind not in {"direct", "dm"}
    )


def _key(org_id: str, workspace_id: str, channel_id: str) -> str:
    return f"ctx:v{SCHEMA_VERSION}:slack_channel:{org_id}:{workspace_id}:{channel_id}"


def _client() -> aioredis.Redis:
    return aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )


def _loads(raw: Any) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw)) if raw else None
    except Exception:
        logger.warning("[context_cache.slack_channel] invalid_json")
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    return payload if isinstance(payload.get("messages"), list) else None


def _ts(message: dict[str, Any]) -> float:
    try:
        return float(str(message.get("ts") or "0"))
    except Exception:
        return 0.0


def _compact_file(file_data: dict[str, Any]) -> dict[str, Any]:
    return {key: file_data[key] for key in _FILE_KEYS if file_data.get(key)}


def compact_slack_message(message: dict[str, Any]) -> dict[str, Any] | None:
    ts = str(message.get("ts") or "").strip()
    if not ts:
        return None
    thread_ts = str(message.get("thread_ts") or ts).strip()
    raw_files = message.get("files") if isinstance(message.get("files"), list) else []
    return {
        "ts": ts,
        "thread_ts": thread_ts,
        "is_thread_message": bool(message.get("is_thread_message")) or thread_ts != ts,
        "user": str(message.get("user") or message.get("user_id") or message.get("sender_slack_id") or "unknown"),
        "bot_id": str(message.get("bot_id") or "") or None,
        "text": str(message.get("text") or ""),
        "files": [_compact_file(f) for f in raw_files if isinstance(f, dict)],
    }


def _trim(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = [m for m in (compact_slack_message(m) for m in messages) if m]
    return sorted(compact, key=_ts)[-MAX_MESSAGES:]


def flatten_channel_payload(
    *, channel_messages: list[dict[str, Any]], thread_expansions: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_ts: dict[str, dict[str, Any]] = {}
    for message in channel_messages:
        if compact := compact_slack_message(message):
            by_ts[compact["ts"]] = compact
    for replies in (thread_expansions or {}).values():
        for reply in replies or []:
            if compact := compact_slack_message(reply):
                by_ts[compact["ts"]] = compact
    return _trim(list(by_ts.values()))


def build_payload(
    *, org_id: str | None = None, organization_id: str | None = None,
    workspace_id: str, channel_id: str, messages: list[dict[str, Any]],
    formatted_context: str = "", rendered_second: int | None = None, dirty: bool = False,
) -> dict[str, Any]:
    org = organization_id or org_id or ""
    trimmed = _trim(messages)
    latest_ts = str(trimmed[-1].get("ts") or "") if trimmed else ""
    latest_second = int(_ts({"ts": latest_ts})) if latest_ts else 0
    return {
        "schema_version": SCHEMA_VERSION,
        "organization_id": org,
        "workspace_id": workspace_id,
        "channel_id": channel_id,
        "latest_ts": latest_ts,
        "latest_second": latest_second,
        "rendered_second": int(rendered_second or 0),
        "dirty": dirty,
        "messages": trimmed,
        "formatted_context": formatted_context,
        "message_count": len(trimmed),
        "updated_at": datetime.now(UTC).isoformat(),
    }


async def get_cached_channel_context(
    *, organization_id: str | None, workspace_id: str | None, channel_id: str | None,
) -> dict[str, Any] | None:
    if not organization_id or not workspace_id or not channel_id:
        return None
    cache_key = _key(organization_id, workspace_id, channel_id)
    try:
        redis_client = _client()
        async with redis_client:
            payload = _loads(await redis_client.get(cache_key))
            if payload is not None:
                await redis_client.expire(cache_key, TTL_SECONDS)
                logger.info(
                    "[context_cache.slack_channel] hit channel_id=%s messages=%d dirty=%s",
                    channel_id,
                    len(payload.get("messages") or []),
                    payload.get("dirty"),
                )
            return payload
    except Exception as exc:
        logger.warning("[context_cache.slack_channel] read_failed channel_id=%s error=%s", channel_id, exc)
        return None


async def set_channel_context(
    *, organization_id: str | None, workspace_id: str | None, channel_id: str | None,
    messages: list[dict[str, Any]], formatted_context: str, rendered_second: int | None = None,
) -> None:
    if not organization_id or not workspace_id or not channel_id:
        return
    payload = build_payload(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
        messages=messages,
        formatted_context=formatted_context,
        rendered_second=rendered_second or int(time.time()),
    )
    try:
        redis_client = _client()
        async with redis_client:
            await redis_client.set(_key(organization_id, workspace_id, channel_id), json.dumps(payload, default=str), ex=TTL_SECONDS)
    except Exception as exc:
        logger.warning("[context_cache.slack_channel] set_failed channel_id=%s error=%s", channel_id, exc)


async def update_rendered_context(
    *, organization_id: str | None, workspace_id: str | None, channel_id: str | None,
    formatted_context: str, rendered_second: int | None = None,
) -> None:
    payload = await get_cached_channel_context(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
    )
    if payload:
        await set_channel_context(
            organization_id=organization_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            messages=[m for m in payload["messages"] if isinstance(m, dict)],
            formatted_context=formatted_context,
            rendered_second=rendered_second,
        )


async def append_slack_message(
    *, organization_id: str | None, workspace_id: str | None, channel_id: str | None,
    channel_type: str | None, conversation_type: str | None = None,
    message_type: MessageType | str | None = None, message: dict[str, Any],
) -> None:
    if not is_public_slack_channel_context_eligible(
        channel_id=channel_id,
        channel_type=channel_type,
        conversation_type=conversation_type,
        message_type=message_type,
    ) or not organization_id or not workspace_id or not channel_id:
        return
    compact = compact_slack_message(message)
    if compact is None:
        return
    cache_key = _key(organization_id, workspace_id, channel_id)
    try:
        redis_client = _client()
        async with redis_client:
            payload = _loads(await redis_client.get(cache_key)) or build_payload(
                organization_id=organization_id,
                workspace_id=workspace_id,
                channel_id=channel_id,
                messages=[],
                dirty=True,
            )
            messages = [m for m in payload["messages"] if isinstance(m, dict) and m.get("ts") != compact["ts"]]
            messages.append(compact)
            payload = build_payload(
                organization_id=organization_id,
                workspace_id=workspace_id,
                channel_id=channel_id,
                messages=messages,
                formatted_context=str(payload.get("formatted_context") or ""),
                rendered_second=int(payload.get("rendered_second") or 0),
                dirty=True,
            )
            await redis_client.set(cache_key, json.dumps(payload, default=str), ex=TTL_SECONDS)
    except Exception as exc:
        logger.warning("[context_cache.slack_channel] append_failed channel_id=%s error=%s", channel_id, exc)
