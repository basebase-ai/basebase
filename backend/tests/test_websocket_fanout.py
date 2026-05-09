from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from api import websockets
from services import task_manager as task_manager_module
from services.task_manager import TaskManager


class _FakeSocket:
    def __init__(self, delay_seconds: float = 0.0, should_fail: bool = False) -> None:
        self.delay_seconds = delay_seconds
        self.should_fail = should_fail
        self.messages: list[str] = []

    async def send_text(self, message: str) -> None:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.should_fail:
            raise RuntimeError("socket closed")
        self.messages.append(message)


def test_fanout_message_sends_concurrently() -> None:
    fast = _FakeSocket()
    slow = _FakeSocket(delay_seconds=0.2)

    start = time.perf_counter()
    dead = asyncio.run(websockets._fanout_message({fast, slow}, '{"ok": true}'))
    elapsed = time.perf_counter() - start

    assert dead == set()
    assert len(fast.messages) == 1
    assert len(slow.messages) == 1
    assert elapsed < 0.35


def test_task_manager_broadcast_does_not_block_on_stalled_socket() -> None:
    manager = TaskManager()
    task_id = "task-for-fanout-test"
    fast = _FakeSocket()
    stalled = _FakeSocket(delay_seconds=5.0)

    async def _run() -> float:
        async with manager._lock:
            manager._subscriptions[task_id] = {fast, stalled}  # noqa: SLF001

        start = time.perf_counter()
        await manager._broadcast(task_id, {"event": "tick"})  # noqa: SLF001
        elapsed_inner = time.perf_counter() - start

        async with manager._lock:
            remaining = manager._subscriptions[task_id]  # noqa: SLF001

        assert fast in remaining
        assert stalled not in remaining
        return elapsed_inner

    elapsed = asyncio.run(_run())
    assert elapsed < 2.2
    assert len(fast.messages) == 1


def test_task_manager_broadcast_snapshots_message_before_session_close(monkeypatch: Any) -> None:
    manager = TaskManager()
    detached = {"value": False}
    captured_payloads: list[dict[str, Any]] = []

    class _FakeMessage:
        def to_dict(self) -> dict[str, Any]:
            if detached["value"]:
                raise RuntimeError("simulated detached instance access")
            return {"id": "assistant-msg-1", "role": "assistant", "content_blocks": []}

    class _FakeScalarResult:
        def __init__(self, value: Any) -> None:
            self._value = value

        def one_or_none(self) -> Any:
            return self._value

    class _FakeResult:
        def __init__(self, row: Any = None, scalar_value: Any = None) -> None:
            self._row = row
            self._scalar_value = scalar_value

        def one_or_none(self) -> Any:
            return self._row

        def scalars(self) -> _FakeScalarResult:
            return _FakeScalarResult(self._scalar_value)

    class _FakeSession:
        def __init__(self, result: _FakeResult) -> None:
            self._result = result

        async def execute(self, _query: Any) -> _FakeResult:
            return self._result

    class _FakeSessionCtx:
        def __init__(self, result: _FakeResult, mark_detached: bool = False) -> None:
            self._session = _FakeSession(result)
            self._mark_detached = mark_detached

        async def __aenter__(self) -> _FakeSession:
            return self._session

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            if self._mark_detached:
                detached["value"] = True
            return False

    contexts = [
        _FakeSessionCtx(_FakeResult(row=("shared", ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]))),
        _FakeSessionCtx(_FakeResult(scalar_value=_FakeMessage()), mark_detached=True),
    ]

    def _fake_get_session(*_args: Any, **_kwargs: Any) -> _FakeSessionCtx:
        return contexts.pop(0)

    async def _fake_broadcast(**kwargs: Any) -> None:
        captured_payloads.append(kwargs["message_data"])

    monkeypatch.setattr(task_manager_module, "get_session", _fake_get_session)
    monkeypatch.setattr(
        __import__("api.websockets", fromlist=["broadcast_conversation_message"]),
        "broadcast_conversation_message",
        _fake_broadcast,
    )

    async def _run() -> None:
        await manager._broadcast_assistant_message_to_participants(  # noqa: SLF001
            conversation_id="11111111-1111-1111-1111-111111111111",
            organization_id="22222222-2222-2222-2222-222222222222",
            exclude_user_id="33333333-3333-3333-3333-333333333333",
        )

    asyncio.run(_run())
    assert captured_payloads == [{"id": "assistant-msg-1", "role": "assistant", "content_blocks": []}]


def test_workflow_tool_progress_subscription_forwards_redis_events(monkeypatch: Any) -> None:
    socket = _FakeSocket()
    event = {
        "type": "tool_progress",
        "conversation_id": "conv-1",
        "tool_id": "tool-1",
        "tool_name": "query_on_connector",
        "result": {"message": "Still working"},
        "status": "running",
    }

    class _FakePubSub:
        def __init__(self) -> None:
            self.sent = False
            self.subscribed: list[str] = []

        async def subscribe(self, channel: str) -> None:
            self.subscribed.append(channel)

        async def get_message(self, **_kwargs: Any) -> dict[str, Any] | None:
            if not self.sent:
                self.sent = True
                return {"data": json.dumps(event)}
            await asyncio.sleep(10)
            return None

        async def unsubscribe(self, _channel: str) -> None:
            return None

        async def close(self) -> None:
            return None

    class _FakeRedis:
        def __init__(self) -> None:
            self.pubsub_instance = _FakePubSub()

        def pubsub(self) -> _FakePubSub:
            return self.pubsub_instance

    fake_redis = _FakeRedis()

    async def _fake_get_tool_progress_redis() -> _FakeRedis:
        return fake_redis

    monkeypatch.setattr(
        __import__("services.tool_progress_pubsub", fromlist=["get_tool_progress_redis"]),
        "get_tool_progress_redis",
        _fake_get_tool_progress_redis,
    )

    async def _run() -> None:
        task = asyncio.create_task(
            websockets._subscribe_workflow_tool_progress(socket, "org-1")  # noqa: SLF001
        )
        while not socket.messages:
            await asyncio.sleep(0.001)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    assert fake_redis.pubsub_instance.subscribed == ["tool_progress:org-1"]
    assert json.loads(socket.messages[0]) == event


def test_workflow_tool_progress_subscription_times_out_silent_worker(monkeypatch: Any) -> None:
    socket = _FakeSocket()
    running_event = {
        "type": "tool_progress",
        "conversation_id": "conv-timeout",
        "tool_id": "tool-timeout",
        "tool_name": "foreach",
        "result": {"message": "Still working"},
        "status": "running",
    }

    class _FakePubSub:
        def __init__(self) -> None:
            self.sent_running = False

        async def subscribe(self, _channel: str) -> None:
            return None

        async def get_message(self, **_kwargs: Any) -> dict[str, Any] | None:
            if not self.sent_running:
                self.sent_running = True
                return {"data": json.dumps(running_event)}
            await asyncio.sleep(0.002)
            return None

        async def unsubscribe(self, _channel: str) -> None:
            return None

        async def close(self) -> None:
            return None

    class _FakeRedis:
        def pubsub(self) -> _FakePubSub:
            return _FakePubSub()

    async def _fake_get_tool_progress_redis() -> _FakeRedis:
        return _FakeRedis()

    monkeypatch.setattr(websockets, "WORKFLOW_TOOL_PROGRESS_SANITY_TIMEOUT_SECONDS", 0.005)
    monkeypatch.setattr(websockets, "WORKFLOW_TOOL_PROGRESS_PUBSUB_POLL_SECONDS", 0.001)
    monkeypatch.setattr(
        __import__("services.tool_progress_pubsub", fromlist=["get_tool_progress_redis"]),
        "get_tool_progress_redis",
        _fake_get_tool_progress_redis,
    )

    async def _run() -> None:
        task = asyncio.create_task(
            websockets._subscribe_workflow_tool_progress(socket, "org-1")  # noqa: SLF001
        )
        while len(socket.messages) < 2:
            await asyncio.sleep(0.001)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())
    timeout_event = json.loads(socket.messages[1])
    assert timeout_event["conversation_id"] == "conv-timeout"
    assert timeout_event["tool_id"] == "tool-timeout"
    assert timeout_event["status"] == "complete"
    assert "timed out" in timeout_event["result"]["error"]


def test_workflow_tool_progress_rehydrate_sends_persisted_state(monkeypatch: Any) -> None:
    socket = _FakeSocket()
    persisted_event = {
        "type": "tool_progress",
        "conversation_id": "conv-rehydrate",
        "tool_id": "tool-rehydrate",
        "tool_name": "foreach",
        "result": {"message": "Still working", "completed": 1, "total": 3},
        "status": "running",
    }

    async def _fake_collect(_organization_id: str) -> list[dict[str, object]]:
        return [persisted_event]

    monkeypatch.setattr(
        websockets,
        "_collect_running_workflow_tool_updates",
        _fake_collect,
    )

    async def _run() -> dict[str, str]:
        last_sent: dict[str, str] = {}
        sent = await websockets._rehydrate_running_workflow_tool_status(  # noqa: SLF001
            socket,
            "org-1",
            last_sent,
        )
        assert sent is True
        # Same persisted payload should be de-duped on the next rehydrate pass.
        sent = await websockets._rehydrate_running_workflow_tool_status(  # noqa: SLF001
            socket,
            "org-1",
            last_sent,
        )
        assert sent is True
        return last_sent

    last_sent = asyncio.run(_run())
    assert len(socket.messages) == 1
    assert json.loads(socket.messages[0]) == persisted_event
    assert last_sent == {
        "conv-rehydrate:tool-rehydrate": websockets._tool_progress_signature(  # noqa: SLF001
            persisted_event
        )
    }


def test_workflow_tool_progress_polls_rehydrate_until_redis_recovers(monkeypatch: Any) -> None:
    socket = _FakeSocket()
    persisted_event = {
        "type": "tool_progress",
        "conversation_id": "conv-fallback",
        "tool_id": "tool-fallback",
        "tool_name": "foreach",
        "result": {"message": "Still working"},
        "status": "running",
    }
    redis_checks = 0

    async def _fake_collect(_organization_id: str) -> list[dict[str, object]]:
        return [persisted_event]

    async def _fake_redis_available() -> bool:
        nonlocal redis_checks
        redis_checks += 1
        return redis_checks >= 1

    monkeypatch.setattr(websockets, "WORKFLOW_TOOL_PROGRESS_PUBSUB_POLL_SECONDS", 0.001)
    monkeypatch.setattr(
        websockets,
        "_collect_running_workflow_tool_updates",
        _fake_collect,
    )
    monkeypatch.setattr(
        websockets,
        "_redis_tool_progress_available",
        _fake_redis_available,
    )

    async def _run() -> bool:
        return await websockets._poll_workflow_tool_status_until_redis_recovers(  # noqa: SLF001
            socket,
            "org-1",
            {},
        )

    assert asyncio.run(_run()) is True
    assert redis_checks == 1
    assert json.loads(socket.messages[0]) == persisted_event
