"""Tests for the chat_messages.semantic_word_count denormalization.

Covers:
  - The pure helper that counts text-block words (excludes tool_use, attachment, etc.)
  - The before_insert / before_update event listener that keeps the column in sync
  - The SUM-based ``count_semantic_words_for_conversation`` query path
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from models.chat_message import (
    ChatMessage,
    _sync_semantic_word_count,
    semantic_word_count_from_blocks,
)
from services.conversation_summary import count_semantic_words_for_conversation


# ---------- semantic_word_count_from_blocks (pure helper) -------------------


def test_word_count_handles_none_and_empty() -> None:
    assert semantic_word_count_from_blocks(None) == 0
    assert semantic_word_count_from_blocks([]) == 0


def test_word_count_only_counts_text_blocks() -> None:
    blocks = [
        {"type": "text", "text": "hello world from the user"},
        {"type": "tool_use", "id": "t1", "name": "search", "input": {"q": "ignored"}, "result": {"a": "ignored too"}},
        {"type": "attachment", "id": "att-1"},
        {"type": "text", "text": "and a follow up"},
    ]
    # 5 + 4 = 9 words; tool_use input/result and attachment are excluded.
    assert semantic_word_count_from_blocks(blocks) == 9


def test_word_count_skips_non_dict_entries_and_blank_text() -> None:
    blocks = [
        "not a dict",
        {"type": "text"},                # missing text key
        {"type": "text", "text": ""},    # empty
        {"type": "text", "text": "   "}, # whitespace only
        {"type": "text", "text": "three real words"},
    ]
    assert semantic_word_count_from_blocks(blocks) == 3


def test_word_count_collapses_runs_of_whitespace_via_split() -> None:
    blocks = [{"type": "text", "text": "   one\t two\nthree    four "}]
    assert semantic_word_count_from_blocks(blocks) == 4


# ---------- ChatMessage event listener --------------------------------------


def test_event_listener_sets_count_on_insert() -> None:
    msg = ChatMessage(
        id=uuid.uuid4(),
        role="user",
        content_blocks=[{"type": "text", "text": "hi there friend"}],
    )
    # before_insert fires this synchronously; simulate it directly so the test
    # doesn't need a DB.
    _sync_semantic_word_count(None, None, msg)
    assert msg.semantic_word_count == 3


def test_event_listener_recomputes_on_update() -> None:
    msg = ChatMessage(
        id=uuid.uuid4(),
        role="assistant",
        content_blocks=[{"type": "text", "text": "first reply with five words"}],
        semantic_word_count=5,
    )
    msg.content_blocks = [
        {"type": "text", "text": "first reply with five words"},
        {"type": "tool_use", "id": "t1", "name": "noop", "input": {}, "result": {}},
        {"type": "text", "text": "and one more"},
    ]
    _sync_semantic_word_count(None, None, msg)
    # Tool use ignored; 5 + 3 = 8.
    assert msg.semantic_word_count == 8


def test_event_listener_drops_to_zero_when_blocks_cleared() -> None:
    msg = ChatMessage(id=uuid.uuid4(), role="user", semantic_word_count=42)
    msg.content_blocks = None
    _sync_semantic_word_count(None, None, msg)
    assert msg.semantic_word_count == 0


def test_event_listener_handles_tool_only_message() -> None:
    """A tool-only message has no semantic words and must store 0 — important
    so that a foreach over thousands of records doesn't push a conversation
    over the summary-regeneration threshold."""
    msg = ChatMessage(
        id=uuid.uuid4(),
        role="assistant",
        content_blocks=[
            {"type": "tool_use", "id": "t1", "name": "foreach", "input": {"items": list(range(1000))}, "result": {}}
            for _ in range(20)
        ],
    )
    _sync_semantic_word_count(None, None, msg)
    assert msg.semantic_word_count == 0


# ---------- count_semantic_words_for_conversation (SUM path) ----------------


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _CapturingSession:
    """Minimal fake that records the executed statement and returns a scalar."""

    def __init__(self, return_value: int) -> None:
        self.return_value = return_value
        self.executed: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(self.return_value)


def test_count_semantic_words_uses_sum_query_not_content_blocks() -> None:
    """Smoke-test that the SUM path is used.

    Critical: this function used to ``select(content_blocks)`` with no LIMIT,
    streaming every row's JSONB back to Python on every assistant reply
    (~14 TB scanned in the prod pg_stat_statements snapshot). It now must SUM
    a denormalized integer column.
    """
    session = _CapturingSession(return_value=137)
    conv_id = uuid.uuid4()

    result = asyncio.run(count_semantic_words_for_conversation(session, conv_id))

    assert result == 137
    assert len(session.executed) == 1
    rendered = str(session.executed[0]).lower()
    # The new query must SUM the denormalized column, not stream content_blocks.
    assert "sum" in rendered
    assert "semantic_word_count" in rendered
    assert "content_blocks" not in rendered


def test_count_semantic_words_returns_zero_when_sum_is_null() -> None:
    """A conversation with no rows yields SUM=NULL; helper must return 0."""
    session = _CapturingSession(return_value=0)
    result = asyncio.run(count_semantic_words_for_conversation(session, uuid.uuid4()))
    assert result == 0
