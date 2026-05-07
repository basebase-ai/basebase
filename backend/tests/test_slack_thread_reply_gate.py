"""Regression tests for the thread-reply gate in WorkspaceMessenger.

The :meth:`_has_existing_conversation` gate decides whether a plain Slack
thread reply (no ``@``-mention) should wake the bot. It runs *before* the
inbound user has been resolved, so we cannot populate ``app.current_user_id``
on a tenant DB session. Conversations have a per-user RLS visibility policy
(private conversations are only visible to their owner / participants), so
the gate must use an admin (RLS-bypassing) session. Otherwise it silently
returns False for private-scope threads — even ones the bot is actively
participating in — and the reply is dropped with reason
``no_existing_thread_conversation``.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from messengers import _workspace as workspace_module
from messengers.base import InboundMessage, MessageType
from messengers.slack import SlackMessenger


class _FakeExecuteResult:
    def __init__(self, row: Any) -> None:
        self._row: Any = row

    def first(self) -> Any:
        return self._row


class _FakeSession:
    def __init__(self, *, row: Any) -> None:
        self._row: Any = row
        self.executed: list[Any] = []

    async def execute(self, query: Any) -> _FakeExecuteResult:
        self.executed.append(query)
        return _FakeExecuteResult(self._row)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session: _FakeSession = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _build_thread_reply(workspace_id: str, channel_id: str, thread_id: str) -> InboundMessage:
    return InboundMessage(
        external_user_id="U123",
        text="follow-up reply",
        message_type=MessageType.THREAD_REPLY,
        messenger_context={
            "workspace_id": workspace_id,
            "channel_id": channel_id,
            "thread_ts": thread_id,
        },
        message_id="mid-1",
    )


@pytest.mark.asyncio
async def test_has_existing_conversation_uses_admin_session_to_bypass_per_user_rls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Private-scope conversations must still be findable at the routing gate.

    Before the fix, the gate opened a tenant session with only
    ``organization_id`` — RLS then hid private conversations from the
    "system" current_user (the all-zero UUID) and the gate erroneously
    returned False, causing thread replies in active private threads to
    be silently dropped.
    """
    org_id: str = str(uuid4())
    messenger: SlackMessenger = SlackMessenger()

    async def _fake_resolve_org(_self: Any, _workspace_id: str) -> str:
        return org_id

    monkeypatch.setattr(
        workspace_module.WorkspaceMessenger,
        "_resolve_org_from_workspace",
        _fake_resolve_org,
    )

    admin_session: _FakeSession = _FakeSession(row=(uuid4(),))
    admin_calls: int = 0

    def _fake_get_admin_session() -> _FakeSessionContext:
        nonlocal admin_calls
        admin_calls += 1
        return _FakeSessionContext(admin_session)

    def _fail_get_session(**_kwargs: Any) -> _FakeSessionContext:
        raise AssertionError(
            "tenant get_session must not be used for the routing gate; "
            "RLS would hide private-scope conversations"
        )

    monkeypatch.setattr(workspace_module, "get_admin_session", _fake_get_admin_session)
    monkeypatch.setattr(workspace_module, "get_session", _fail_get_session)

    message: InboundMessage = _build_thread_reply(
        workspace_id="T_TEST",
        channel_id="C_TEST",
        thread_id="1234567890.000100",
    )

    has_conversation: bool = await messenger._has_existing_conversation(message)

    assert has_conversation is True
    assert admin_calls == 1
    assert len(admin_session.executed) == 1


@pytest.mark.asyncio
async def test_has_existing_conversation_returns_false_when_no_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no conversation exists, the gate must still report False so plain
    thread replies in unrelated threads continue to be ignored."""
    org_id: str = str(uuid4())
    messenger: SlackMessenger = SlackMessenger()

    async def _fake_resolve_org(_self: Any, _workspace_id: str) -> str:
        return org_id

    monkeypatch.setattr(
        workspace_module.WorkspaceMessenger,
        "_resolve_org_from_workspace",
        _fake_resolve_org,
    )

    admin_session: _FakeSession = _FakeSession(row=None)
    monkeypatch.setattr(
        workspace_module,
        "get_admin_session",
        lambda: _FakeSessionContext(admin_session),
    )

    message: InboundMessage = _build_thread_reply(
        workspace_id="T_TEST",
        channel_id="C_TEST",
        thread_id="1234567890.000200",
    )

    has_conversation: bool = await messenger._has_existing_conversation(message)

    assert has_conversation is False


@pytest.mark.asyncio
async def test_has_existing_conversation_returns_false_without_thread_or_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing thread_id or workspace_id should short-circuit before any DB call."""
    messenger: SlackMessenger = SlackMessenger()

    def _fail_admin_session() -> _FakeSessionContext:
        raise AssertionError("admin session should not be opened when context is incomplete")

    monkeypatch.setattr(workspace_module, "get_admin_session", _fail_admin_session)

    no_thread: InboundMessage = InboundMessage(
        external_user_id="U123",
        text="hi",
        message_type=MessageType.THREAD_REPLY,
        messenger_context={"workspace_id": "T_TEST", "channel_id": "C_TEST"},
        message_id="mid-1",
    )
    no_workspace: InboundMessage = InboundMessage(
        external_user_id="U123",
        text="hi",
        message_type=MessageType.THREAD_REPLY,
        messenger_context={"channel_id": "C_TEST", "thread_ts": "1234567890.000300"},
        message_id="mid-2",
    )

    assert await messenger._has_existing_conversation(no_thread) is False
    assert await messenger._has_existing_conversation(no_workspace) is False
