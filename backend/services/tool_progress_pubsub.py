"""Redis pub/sub helpers for cross-process tool progress updates."""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from config import get_redis_connection_kwargs, settings

logger = logging.getLogger(__name__)

TOOL_PROGRESS_CHANNEL_PREFIX = "tool_progress"
TOOL_PROGRESS_TERMINAL_STATUSES = {
    "complete",
    "completed",
    "failed",
    "error",
    "cancelled",
    "canceled",
}

_redis_client: aioredis.Redis | None = None


def tool_progress_channel(organization_id: str) -> str:
    """Return the Redis channel used for an organization's tool progress."""
    return f"{TOOL_PROGRESS_CHANNEL_PREFIX}:{organization_id}"


def build_tool_progress_event(
    *,
    conversation_id: str,
    tool_id: str,
    tool_name: str,
    result: dict[str, Any],
    status: str = "running",
) -> dict[str, Any]:
    """Build a websocket-compatible tool progress event payload."""
    return {
        "type": "tool_progress",
        "conversation_id": conversation_id,
        "tool_id": tool_id,
        "tool_name": tool_name,
        "result": result,
        "status": status,
    }


async def get_tool_progress_redis() -> aioredis.Redis:
    """Lazy-initialize a module-level async Redis client for tool progress."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            **get_redis_connection_kwargs(decode_responses=True),
        )
    return _redis_client


async def publish_tool_progress(
    *,
    organization_id: str,
    conversation_id: str,
    tool_id: str,
    tool_name: str,
    result: dict[str, Any],
    status: str = "running",
) -> bool:
    """Publish a tool progress event to Redis for API websocket workers."""
    event = build_tool_progress_event(
        conversation_id=conversation_id,
        tool_id=tool_id,
        tool_name=tool_name,
        result=result,
        status=status,
    )
    channel = tool_progress_channel(organization_id)
    try:
        redis = await get_tool_progress_redis()
        await redis.publish(channel, json.dumps(event, default=str))
        logger.debug(
            "[ToolProgressPubSub] Published tool progress channel=%s conv=%s tool=%s status=%s",
            channel,
            conversation_id[:8] if conversation_id else None,
            tool_id[:8] if tool_id else None,
            status,
        )
        return True
    except Exception as exc:
        logger.warning(
            "[ToolProgressPubSub] Failed to publish tool progress conv=%s tool=%s status=%s: %s",
            conversation_id[:8] if conversation_id else None,
            tool_id[:8] if tool_id else None,
            status,
            exc,
        )
        return False
