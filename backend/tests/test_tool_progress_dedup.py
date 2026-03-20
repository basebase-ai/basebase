import asyncio
import sys
import types
from types import SimpleNamespace
from uuid import uuid4

_fake_websockets = types.ModuleType("api.websockets")

async def _noop_broadcast_sync_progress(**_kwargs: object) -> None:
    return None

async def _noop_broadcast_tool_progress(**_kwargs: object) -> None:
    return None

_fake_websockets.broadcast_sync_progress = _noop_broadcast_sync_progress
_fake_websockets.broadcast_tool_progress = _noop_broadcast_tool_progress
sys.modules.setdefault("api.websockets", _fake_websockets)

from agents import orchestrator


class _FakeExecuteResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _FakeSession:
    def __init__(self, message: object) -> None:
        self._message = message
        self.commit_calls = 0

    async def execute(self, _query: object) -> _FakeExecuteResult:
        return _FakeExecuteResult(self._message)

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def test_update_tool_result_skips_duplicate_progress_updates(monkeypatch) -> None:
    conversation_id = str(uuid4())
    tool_id = "tool-123"
    message = SimpleNamespace(
        content_blocks=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": "write_on_connector",
                "status": "running",
                "result": {"message": "Writing to Linear"},
            }
        ]
    )
    fake_session = _FakeSession(message)
    broadcasts: list[dict[str, object]] = []

    async def _fake_broadcast_tool_progress(**kwargs: object) -> None:
        broadcasts.append(kwargs)

    monkeypatch.setattr(
        orchestrator,
        "get_session",
        lambda **_kwargs: _FakeSessionContext(fake_session),
    )
    monkeypatch.setattr(
        sys.modules["api.websockets"],
        "broadcast_tool_progress",
        _fake_broadcast_tool_progress,
    )

    updated = asyncio.run(
        orchestrator.update_tool_result(
            conversation_id=conversation_id,
            tool_id=tool_id,
            result={"message": "Writing to Linear"},
            status="running",
            organization_id=str(uuid4()),
        )
    )

    assert updated is False
    assert fake_session.commit_calls == 0
    assert broadcasts == []
    assert message.content_blocks[0]["result"] == {"message": "Writing to Linear"}


def test_update_tool_result_allows_status_change_with_same_result(monkeypatch) -> None:
    conversation_id = str(uuid4())
    tool_id = "tool-456"
    organization_id = str(uuid4())
    message = SimpleNamespace(
        content_blocks=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": "write_on_connector",
                "status": "running",
                "result": {"message": "Writing to Linear"},
            }
        ]
    )
    fake_session = _FakeSession(message)
    broadcasts: list[dict[str, object]] = []

    async def _fake_broadcast_tool_progress(**kwargs: object) -> None:
        broadcasts.append(kwargs)

    monkeypatch.setattr(
        orchestrator,
        "get_session",
        lambda **_kwargs: _FakeSessionContext(fake_session),
    )
    monkeypatch.setattr(
        sys.modules["api.websockets"],
        "broadcast_tool_progress",
        _fake_broadcast_tool_progress,
    )

    updated = asyncio.run(
        orchestrator.update_tool_result(
            conversation_id=conversation_id,
            tool_id=tool_id,
            result={"message": "Writing to Linear"},
            status="complete",
            organization_id=organization_id,
        )
    )

    assert updated is True
    assert fake_session.commit_calls == 1
    assert message.content_blocks[0]["status"] == "complete"
    assert broadcasts == [
        {
            "organization_id": organization_id,
            "conversation_id": conversation_id,
            "tool_id": tool_id,
            "tool_name": "write_on_connector",
            "result": {"message": "Writing to Linear"},
            "status": "complete",
        }
    ]
