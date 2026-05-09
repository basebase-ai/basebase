"""Lean chat message projections for hot-path conversation reads.

The ``chat_messages`` row can contain very large JSONB tool inputs/results. Hot
paths that only need transcript text, tool names, or semantic counts should not
hydrate full ORM rows or return full ``content_blocks`` payloads to Python.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class PromptMessageProjection:
    """Minimal message shape needed for summary/title prompt formatting."""

    role: str
    content_blocks: list[dict[str, Any]]


@dataclass(frozen=True)
class RecentUserTextProjection:
    """Minimal user-message shape needed for embedding text construction."""

    block_text: str
    legacy_content: str | None


_PROMPT_MESSAGES_SQL = """
SELECT
    role,
    COALESCE(
        (
            SELECT jsonb_agg(projected.block ORDER BY projected.ordinality)
            FROM (
                SELECT
                    block_items.ordinality,
                    CASE
                        WHEN block_items.block ->> 'type' = 'text' THEN
                            jsonb_build_object(
                                'type', 'text',
                                'text', left(COALESCE(block_items.block ->> 'text', ''), :text_limit)
                            )
                        WHEN block_items.block ->> 'type' = 'tool_use' THEN
                            jsonb_build_object(
                                'type', 'tool_use',
                                'name', COALESCE(block_items.block ->> 'name', 'unknown')
                            )
                        ELSE NULL
                    END AS block
                FROM jsonb_array_elements(COALESCE(content_blocks, '[]'::jsonb))
                    WITH ORDINALITY AS block_items(block, ordinality)
                WHERE block_items.block ->> 'type' IN ('text', 'tool_use')
            ) AS projected
            WHERE projected.block IS NOT NULL
        ),
        '[]'::jsonb
    ) AS content_blocks
FROM chat_messages
WHERE conversation_id = :conversation_id
ORDER BY created_at DESC
LIMIT :limit
"""

_RECENT_USER_TEXT_SQL = """
SELECT
    COALESCE(
        (
            SELECT string_agg(projected.part, ' ' ORDER BY projected.ordinality)
            FROM (
                SELECT
                    block_items.ordinality,
                    CASE
                        WHEN block_items.block ->> 'type' = 'text' THEN
                            COALESCE(block_items.block ->> 'text', '')
                        WHEN block_items.block ->> 'type' = 'tool_use' THEN
                            '[' || COALESCE(block_items.block ->> 'name', 'unknown') || ']'
                        ELSE NULL
                    END AS part
                FROM jsonb_array_elements(COALESCE(content_blocks, '[]'::jsonb))
                    WITH ORDINALITY AS block_items(block, ordinality)
                WHERE block_items.block ->> 'type' IN ('text', 'tool_use')
            ) AS projected
            WHERE projected.part IS NOT NULL AND projected.part <> ''
        ),
        ''
    ) AS block_text,
    content AS legacy_content
FROM chat_messages
WHERE conversation_id = :conversation_id
  AND role = 'user'
ORDER BY created_at DESC
LIMIT :limit
"""

_SEMANTIC_WORD_COUNT_SQL = """
SELECT COALESCE(SUM(semantic_word_count), 0)::integer AS semantic_words
FROM chat_messages
WHERE conversation_id = :conversation_id
"""


def _coerce_blocks(value: Any) -> list[dict[str, Any]]:
    """Normalize driver-returned JSONB values into a list of block dicts."""
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return []
    return [block for block in value if isinstance(block, dict)]


async def fetch_prompt_message_projections(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int,
    text_limit: int = 2_000,
) -> list[PromptMessageProjection]:
    """Fetch recent messages without hydrating full ``chat_messages`` rows.

    The JSONB projection intentionally keeps only text and tool names. It omits
    tool inputs/results and unrelated blocks so summary/title generation avoids
    transferring large tool payloads.
    """
    result = await session.execute(
        text(_PROMPT_MESSAGES_SQL),
        {
            "conversation_id": conversation_id,
            "limit": limit,
            "text_limit": text_limit,
        },
    )
    return [
        PromptMessageProjection(
            role=str(row.role),
            content_blocks=_coerce_blocks(row.content_blocks),
        )
        for row in result
    ]


async def fetch_recent_user_text_projections(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    limit: int,
) -> list[RecentUserTextProjection]:
    """Fetch recent user text for embeddings without full message hydration."""
    result = await session.execute(
        text(_RECENT_USER_TEXT_SQL),
        {
            "conversation_id": conversation_id,
            "limit": limit,
        },
    )
    return [
        RecentUserTextProjection(
            block_text=str(row.block_text or ""),
            legacy_content=row.legacy_content,
        )
        for row in result
    ]


async def count_semantic_words_projection(
    session: AsyncSession,
    conversation_id: uuid.UUID,
) -> int:
    """Count semantic words via the denormalized integer column."""
    result = await session.execute(
        text(_SEMANTIC_WORD_COUNT_SQL),
        {"conversation_id": conversation_id},
    )
    return int(result.scalar_one() or 0)
