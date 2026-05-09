"""Redis-backed hot cache for public Slack channel context."""
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
SLACK_CHANNEL_CONTEXT_TTL_SECONDS = 60 * 60 * 24
SLACK_CHANNEL_CONTEXT_MAX_MESSAGES = 250
_REDIS_RETRY_COUNT = 2


def is_public_slack_channel_context_eligible(
    *,
    channel_id: str | None,
    channel_type: str | None,
    conversation_type: str | None = None,
    message_type: MessageType | str | None = None,
) -> bool:
    """Return True only for public Slack channels eligible for hot channel context."""
    normalized_channel_id = str(channel_id or "").strip().upper()
    normalized_channel_type = str(channel_type or "").strip().lower()
    normalized_conversation_type = str(conversation_type or "").strip().lower()
    normalized_message_type = (
        message_type.value if isinstance(message_type, MessageType) else str(message_type or "")
    ).strip().lower()

    if not normalized_channel_id:
        return False
    if normalized_channel_id.startswith(("D", "G")):
        return False
    disallowed_types = {
        "im",
        "mpim",
        "direct",
        "direct_message",
        "dm",
        "group",
        "groupchat",
        "private_channel",
    }
    if normalized_channel_type in disallowed_types:
        return False
    if normalized_conversation_type in disallowed_types:
        return False
    if normalized_message_type in {"direct", "dm"}:
        return False
    return True


def _slack_channel_key(*, organization_id: str, workspace_id: str, channel_id: str) -> str:
    return f"ctx:v{SCHEMA_VERSION}:slack_channel:{organization_id}:{workspace_id}:{channel_id}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> str:
    return str(value)


def _ts_float(message: dict[str, Any]) -> float:
    try:
        return float(str(message.get("ts") or "0"))
    except Exception:
        return 0.0


def _ts_second(ts: str | None) -> int:
    try:
        return int(float(str(ts or "0")))
    except Exception:
        return 0


def _message_key(message: dict[str, Any]) -> str:
    return str(message.get("ts") or "").strip()


def _compact_file(file_data: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "id",
        "name",
        "title",
        "url_private_download",
        "url_private",
        "permalink",
        "mimetype",
    }
    return {key: file_data.get(key) for key in allowed_keys if file_data.get(key)}


def compact_slack_message(message: dict[str, Any]) -> dict[str, Any] | None:
    ts_value = str(message.get("ts") or "").strip()
    if not ts_value:
        return None
    thread_ts = str(message.get("thread_ts") or ts_value).strip()
    raw_files = message.get("files") or []
    files = [
        _compact_file(file_data)
        for file_data in raw_files
        if isinstance(file_data, dict)
    ] if isinstance(raw_files, list) else []
    return {
        "ts": ts_value,
        "thread_ts": thread_ts,
        "is_thread_message": bool(message.get("is_thread_message")) or (bool(thread_ts) and thread_ts != ts_value),
        "user": str(message.get("user") or message.get("user_id") or message.get("sender_slack_id") or "unknown"),
        "bot_id": str(message.get("bot_id") or "") or None,
        "text": str(message.get("text") or ""),
        "files": files,
    }


def flatten_channel_payload(
    *,
    channel_messages: list[dict[str, Any]],
    thread_expansions: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_ts: dict[str, dict[str, Any]] = {}
    for message in channel_messages:
        compact = compact_slack_message(message)
        if compact:
            by_ts[_message_key(compact)] = compact
    for replies in (thread_expansions or {}).values():
        for reply in replies or []:
            compact = compact_slack_message(reply)
            if compact:
                by_ts[_message_key(compact)] = compact
    return _trim_messages(list(by_ts.values()))


def _trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_messages: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        compact = compact_slack_message(msg)
        if compact is not None:
            compact_messages.append(compact)
    sorted_messages = sorted(
        compact_messages,
        key=_ts_float,
    )
    if len(sorted_messages) <= SLACK_CHANNEL_CONTEXT_MAX_MESSAGES:
        return sorted_messages
    return sorted_messages[-SLACK_CHANNEL_CONTEXT_MAX_MESSAGES:]


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        payload = json.loads(str(raw))
    except Exception:
        logger.warning("[context_cache.slack_channel] invalid_json")
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return None
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return None
    return payload


def build_payload(
    *,
    organization_id: str,
    workspace_id: str,
    channel_id: str,
    messages: list[dict[str, Any]],
    formatted_context: str = "",
    rendered_second: int | None = None,
    dirty: bool = False,
) -> dict[str, Any]:
    trimmed_messages = _trim_messages(messages)
    latest_ts = ""
    if trimmed_messages:
        latest_ts = str(trimmed_messages[-1].get("ts") or "")
    latest_second = _ts_second(latest_ts)
    return {
        "schema_version": SCHEMA_VERSION,
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "channel_id": channel_id,
        "latest_ts": latest_ts,
        "latest_second": latest_second,
        "rendered_second": int(rendered_second or 0),
        "dirty": bool(dirty),
        "messages": trimmed_messages,
        "formatted_context": formatted_context,
        "message_count": len(trimmed_messages),
        "updated_at": _utc_now_iso(),
    }


async def _redis_client() -> aioredis.Redis:
    return aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )


async def get_cached_channel_context(
    *,
    organization_id: str | None,
    workspace_id: str | None,
    channel_id: str | None,
) -> dict[str, Any] | None:
    if not organization_id or not workspace_id or not channel_id:
        return None
    key = _slack_channel_key(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
    )
    try:
        redis_client = await _redis_client()
        async with redis_client:
            payload = _parse_payload(await redis_client.get(key))
            if payload is None:
                logger.info(
                    "[context_cache.slack_channel] miss organization_id=%s workspace_id=%s channel_id=%s",
                    organization_id,
                    workspace_id,
                    channel_id,
                )
                return None
            await redis_client.expire(key, SLACK_CHANNEL_CONTEXT_TTL_SECONDS)
            logger.info(
                "[context_cache.slack_channel] hit organization_id=%s workspace_id=%s channel_id=%s messages=%d dirty=%s",
                organization_id,
                workspace_id,
                channel_id,
                len(payload.get("messages") or []),
                payload.get("dirty"),
            )
            return payload
    except Exception as exc:
        logger.warning(
            "[context_cache.slack_channel] read_failed organization_id=%s workspace_id=%s channel_id=%s error=%s",
            organization_id,
            workspace_id,
            channel_id,
            exc,
        )
        return None


async def set_channel_context(
    *,
    organization_id: str | None,
    workspace_id: str | None,
    channel_id: str | None,
    messages: list[dict[str, Any]],
    formatted_context: str,
    rendered_second: int | None = None,
) -> None:
    if not organization_id or not workspace_id or not channel_id:
        return
    key = _slack_channel_key(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
    )
    if rendered_second is None:
        rendered_second = int(time.time())
    payload = build_payload(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
        messages=messages,
        formatted_context=formatted_context,
        rendered_second=rendered_second,
        dirty=False,
    )
    try:
        redis_client = await _redis_client()
        async with redis_client:
            await redis_client.set(
                key,
                json.dumps(payload, default=_json_default),
                ex=SLACK_CHANNEL_CONTEXT_TTL_SECONDS,
            )
        logger.info(
            "[context_cache.slack_channel] set organization_id=%s workspace_id=%s channel_id=%s messages=%d ttl=%d",
            organization_id,
            workspace_id,
            channel_id,
            len(payload["messages"]),
            SLACK_CHANNEL_CONTEXT_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "[context_cache.slack_channel] set_failed organization_id=%s workspace_id=%s channel_id=%s error=%s",
            organization_id,
            workspace_id,
            channel_id,
            exc,
        )


async def update_rendered_context(
    *,
    organization_id: str | None,
    workspace_id: str | None,
    channel_id: str | None,
    formatted_context: str,
    rendered_second: int | None = None,
) -> None:
    if not organization_id or not workspace_id or not channel_id:
        return
    payload = await get_cached_channel_context(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
    )
    if payload is None:
        return
    await set_channel_context(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
        messages=[msg for msg in payload.get("messages", []) if isinstance(msg, dict)],
        formatted_context=formatted_context,
        rendered_second=rendered_second,
    )


async def append_slack_message(
    *,
    organization_id: str | None,
    workspace_id: str | None,
    channel_id: str | None,
    channel_type: str | None,
    conversation_type: str | None = None,
    message_type: MessageType | str | None = None,
    message: dict[str, Any],
) -> None:
    if not is_public_slack_channel_context_eligible(
        channel_id=channel_id,
        channel_type=channel_type,
        conversation_type=conversation_type,
        message_type=message_type,
    ):
        return
    if not organization_id or not workspace_id or not channel_id:
        return
    compact = compact_slack_message(message)
    if compact is None:
        return
    key = _slack_channel_key(
        organization_id=organization_id,
        workspace_id=workspace_id,
        channel_id=channel_id,
    )
    for attempt in range(_REDIS_RETRY_COUNT + 1):
        try:
            redis_client = await _redis_client()
            async with redis_client:
                async with redis_client.pipeline() as pipe:
                    try:
                        await pipe.watch(key)
                        raw = await pipe.get(key)
                        payload = _parse_payload(raw)
                        if payload is None:
                            payload = build_payload(
                                organization_id=organization_id,
                                workspace_id=workspace_id,
                                channel_id=channel_id,
                                messages=[],
                                dirty=True,
                            )
                        messages = [dict(msg) for msg in payload.get("messages", []) if isinstance(msg, dict)]
                        new_key = _message_key(compact)
                        messages = [msg for msg in messages if _message_key(msg) != new_key]
                        messages.append(compact)
                        updated_payload = build_payload(
                            organization_id=organization_id,
                            workspace_id=workspace_id,
                            channel_id=channel_id,
                            messages=messages,
                            formatted_context=str(payload.get("formatted_context") or ""),
                            rendered_second=int(payload.get("rendered_second") or 0),
                            dirty=True,
                        )
                        pipe.multi()
                        pipe.set(
                            key,
                            json.dumps(updated_payload, default=_json_default),
                            ex=SLACK_CHANNEL_CONTEXT_TTL_SECONDS,
                        )
                        await pipe.execute()
                        logger.info(
                            "[context_cache.slack_channel] append organization_id=%s workspace_id=%s channel_id=%s ts=%s messages=%d",
                            organization_id,
                            workspace_id,
                            channel_id,
                            compact.get("ts"),
                            len(updated_payload["messages"]),
                        )
                        return
                    except aioredis.WatchError:
                        logger.info(
                            "[context_cache.slack_channel] append_conflict organization_id=%s workspace_id=%s channel_id=%s attempt=%d",
                            organization_id,
                            workspace_id,
                            channel_id,
                            attempt + 1,
                        )
                        continue
        except Exception as exc:
            logger.warning(
                "[context_cache.slack_channel] append_failed organization_id=%s workspace_id=%s channel_id=%s error=%s",
                organization_id,
                workspace_id,
                channel_id,
                exc,
            )
            return
