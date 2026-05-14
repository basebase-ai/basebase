import asyncio
from types import SimpleNamespace
from uuid import uuid4

from agents import orchestrator
from services import tool_progress_pubsub


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

    async def _fake_publish_tool_progress(**kwargs: object) -> bool:
        broadcasts.append(kwargs)
        return True

    monkeypatch.setattr(
        orchestrator,
        "get_session",
        lambda **_kwargs: _FakeSessionContext(fake_session),
    )
    monkeypatch.setattr(
        tool_progress_pubsub,
        "publish_tool_progress",
        _fake_publish_tool_progress,
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

    async def _fake_publish_tool_progress(**kwargs: object) -> bool:
        broadcasts.append(kwargs)
        return True

    monkeypatch.setattr(
        orchestrator,
        "get_session",
        lambda **_kwargs: _FakeSessionContext(fake_session),
    )
    monkeypatch.setattr(
        tool_progress_pubsub,
        "publish_tool_progress",
        _fake_publish_tool_progress,
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


def test_json_safe_coerces_decimal_uuid_dates_and_null_bytes() -> None:
    import json
    from datetime import date, datetime, timezone
    from decimal import Decimal

    value_id = uuid4()
    payload = {
        "amount": Decimal("123.45"),
        "whole": Decimal("42.00"),
        "id": value_id,
        "created_at": datetime(2026, 5, 13, 12, 30, tzinfo=timezone.utc),
        "day": date(2026, 5, 13),
        "bad_text": "hello\x00world",
    }

    safe = orchestrator.ChatOrchestrator._json_safe(payload)

    json.dumps(safe)
    assert safe["amount"] == 123.45
    assert safe["whole"] == 42
    assert safe["id"] == str(value_id)
    assert safe["created_at"] == "2026-05-13T12:30:00+00:00"
    assert safe["day"] == "2026-05-13"
    assert safe["bad_text"] == "helloworld"


def test_update_tool_result_sanitizes_decimal_result_before_save_and_publish(monkeypatch) -> None:
    from decimal import Decimal

    conversation_id = str(uuid4())
    tool_id = "tool-decimal"
    organization_id = str(uuid4())
    message = SimpleNamespace(
        content_blocks=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": "query_on_connector",
                "status": "running",
                "result": None,
            }
        ]
    )
    fake_session = _FakeSession(message)
    broadcasts: list[dict[str, object]] = []

    async def _fake_publish_tool_progress(**kwargs: object) -> bool:
        broadcasts.append(kwargs)
        return True

    monkeypatch.setattr(
        orchestrator,
        "get_session",
        lambda **_kwargs: _FakeSessionContext(fake_session),
    )
    monkeypatch.setattr(
        tool_progress_pubsub,
        "publish_tool_progress",
        _fake_publish_tool_progress,
    )

    updated = asyncio.run(
        orchestrator.update_tool_result(
            conversation_id=conversation_id,
            tool_id=tool_id,
            result={"rows": [{"amount": Decimal("10.50"), "count": Decimal("3")}]},
            status="complete",
            organization_id=organization_id,
        )
    )

    expected_result = {"rows": [{"amount": 10.5, "count": 3}]}
    assert updated is True
    assert fake_session.commit_calls == 1
    assert message.content_blocks[0]["result"] == expected_result
    assert broadcasts[0]["result"] == expected_result
