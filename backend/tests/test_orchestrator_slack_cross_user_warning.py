import asyncio
import json
from types import SimpleNamespace

from agents.orchestrator import ChatOrchestrator
from services.llm_adapter import StreamEvent


class _FakeAdapter:
    def __init__(self) -> None:
        self._calls = 0
        self.calls: list[dict[str, object]] = []

    async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
        self._calls += 1
        self.calls.append(kwargs)
        if self._calls == 1:
            yield StreamEvent(type="tool_use_start", tool_id="tool-1", tool_name="query_on_connector")
            yield StreamEvent(type="tool_input_delta", tool_input_json='{"connector":"hubspot","query":"x"}')
            yield StreamEvent(type="tool_use_stop")
            return

        yield StreamEvent(type="text_delta", text="Final response")


async def _collect_stream(orchestrator: ChatOrchestrator) -> list[str]:
    messages = [{"role": "user", "content": "hi"}]
    content_blocks: list[dict[str, object]] = []
    out: list[str] = []
    async for chunk in orchestrator._stream_with_tools(messages, "sys", content_blocks, "fake-model"):
        out.append(chunk)
    return out


def test_stream_with_tools_emits_cross_user_warning_for_slack_sources(monkeypatch) -> None:
    orchestrator = ChatOrchestrator(
        user_id="u1",
        organization_id="org1",
        source="slack_thread",
    )
    orchestrator._adapter = _FakeAdapter()
    orchestrator._llm_config = SimpleNamespace(provider="openai")

    async def _fake_execute_tool(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"warning": "Used teammate connector", "status": "success"}

    monkeypatch.setattr("agents.orchestrator.execute_tool", _fake_execute_tool)

    chunks = asyncio.run(_collect_stream(orchestrator))
    joined = "".join(chunks)

    assert "⚠️ Used teammate connector" in joined
    assert "Final response" in joined
    second_call_messages = orchestrator._adapter.calls[1]["messages"]
    assert second_call_messages[-1]["role"] == "user"
    assert second_call_messages[-1]["content"][0]["type"] == "tool_result"


def test_stream_with_tools_does_not_emit_warning_for_web(monkeypatch) -> None:
    orchestrator = ChatOrchestrator(
        user_id="u1",
        organization_id="org1",
        source="web",
    )
    orchestrator._adapter = _FakeAdapter()
    orchestrator._llm_config = SimpleNamespace(provider="openai")

    async def _fake_execute_tool(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"warning": "Used teammate connector", "status": "success"}

    monkeypatch.setattr("agents.orchestrator.execute_tool", _fake_execute_tool)

    chunks = asyncio.run(_collect_stream(orchestrator))
    joined = "".join(chunks)

    assert "⚠️ Used teammate connector" not in joined
    assert "Final response" in joined


class _ThinkingThenToolAdapter:
    def __init__(self) -> None:
        self._calls = 0
        self.calls: list[dict[str, object]] = []

    async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
        self._calls += 1
        self.calls.append(kwargs)
        if self._calls == 1:
            yield StreamEvent(type="thinking_start")
            yield StreamEvent(type="thinking_delta", text="need a tool")
            yield StreamEvent(type="thinking_stop")
            yield StreamEvent(
                type="tool_use_start",
                tool_id="tool-1",
                tool_name="query_on_connector",
            )
            yield StreamEvent(
                type="tool_input_delta",
                tool_input_json='{"connector":"hubspot","query":"x"}',
            )
            yield StreamEvent(type="tool_use_stop")
            return

        yield StreamEvent(type="text_delta", text="Final response")


async def _collect_stream_for_model(
    orchestrator: ChatOrchestrator,
    model_name: str,
) -> tuple[list[str], list[dict[str, object]]]:
    messages = [{"role": "user", "content": "hi"}]
    content_blocks: list[dict[str, object]] = []
    out: list[str] = []
    async for chunk in orchestrator._stream_with_tools(
        messages,
        "sys",
        content_blocks,
        model_name,
    ):
        out.append(chunk)
    return out, content_blocks


def test_stream_with_tools_replays_thinking_only_for_deepseek_models(monkeypatch) -> None:
    async def _fake_execute_tool(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"status": "success", "result": "ok"}

    monkeypatch.setattr("agents.orchestrator.execute_tool", _fake_execute_tool)

    non_deepseek_orchestrator = ChatOrchestrator(
        user_id="u1",
        organization_id="org1",
        source="web",
    )
    non_deepseek_adapter = _ThinkingThenToolAdapter()
    non_deepseek_orchestrator._adapter = non_deepseek_adapter
    non_deepseek_orchestrator._llm_config = SimpleNamespace(provider="anthropic")

    _, non_deepseek_content_blocks = asyncio.run(
        _collect_stream_for_model(non_deepseek_orchestrator, "claude-opus-4-6")
    )

    non_deepseek_messages = non_deepseek_adapter.calls[1]["messages"]
    non_deepseek_assistant_content = non_deepseek_messages[1]["content"]
    assert all(block["type"] != "thinking" for block in non_deepseek_assistant_content)
    assert all(block["type"] != "thinking" for block in non_deepseek_content_blocks)

    deepseek_orchestrator = ChatOrchestrator(
        user_id="u1",
        organization_id="org1",
        source="web",
    )
    deepseek_adapter = _ThinkingThenToolAdapter()
    deepseek_orchestrator._adapter = deepseek_adapter
    deepseek_orchestrator._llm_config = SimpleNamespace(provider="deepseek")

    _, deepseek_content_blocks = asyncio.run(
        _collect_stream_for_model(deepseek_orchestrator, "deepseek-v4-pro")
    )

    deepseek_messages = deepseek_adapter.calls[1]["messages"]
    deepseek_assistant_content = deepseek_messages[1]["content"]
    assert deepseek_assistant_content[0] == {"type": "thinking", "thinking": "need a tool"}
    assert deepseek_content_blocks[0] == {"type": "thinking", "thinking": "need a tool"}


class _FakeScalarResult:
    def __init__(self, messages):  # type: ignore[no-untyped-def]
        self._messages = messages

    def all(self):  # type: ignore[no-untyped-def]
        return self._messages


class _FakeExecuteResult:
    def __init__(self, messages):  # type: ignore[no-untyped-def]
        self._messages = messages

    def scalars(self):  # type: ignore[no-untyped-def]
        return _FakeScalarResult(self._messages)


class _FakeSession:
    def __init__(self, messages):  # type: ignore[no-untyped-def]
        self._messages = messages

    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _FakeExecuteResult(self._messages)


class _FakeSessionManager:
    def __init__(self, messages):  # type: ignore[no-untyped-def]
        self._messages = messages

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return _FakeSession(self._messages)

    async def __aexit__(self, *_args):  # type: ignore[no-untyped-def]
        return False


def test_load_history_replays_persisted_thinking_only_when_enabled(monkeypatch) -> None:
    saved_messages = [
        SimpleNamespace(
            role="assistant",
            content_blocks=[
                {"type": "thinking", "thinking": "need a tool"},
                {"type": "text", "text": "I'll check."},
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "query_on_connector",
                    "input": {"connector": "hubspot", "query": "x"},
                    "result": {"status": "success"},
                },
            ],
            _legacy_to_blocks=lambda: [],
        )
    ]

    monkeypatch.setattr(
        "agents.orchestrator.get_session",
        lambda **_kwargs: _FakeSessionManager(saved_messages),
    )

    orchestrator = ChatOrchestrator(
        user_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        conversation_id="00000000-0000-0000-0000-000000000003",
        source="web",
    )

    deepseek_history = asyncio.run(
        orchestrator._load_history(limit=20, include_thinking_blocks=True)
    )
    assert deepseek_history[0]["content"][0] == {
        "type": "thinking",
        "thinking": "need a tool",
    }

    non_deepseek_history = asyncio.run(
        orchestrator._load_history(limit=20, include_thinking_blocks=False)
    )
    assert all(
        block["type"] != "thinking"
        for message in non_deepseek_history
        if isinstance(message["content"], list)
        for block in message["content"]
    )


class _ThinkingToolThenFinalThinkingAdapter:
    def __init__(self) -> None:
        self._calls = 0
        self.calls: list[dict[str, object]] = []

    async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
        self._calls += 1
        self.calls.append(kwargs)
        if self._calls == 1:
            yield StreamEvent(type="thinking_start")
            yield StreamEvent(type="thinking_delta", text="first reasoning")
            yield StreamEvent(type="thinking_stop")
            yield StreamEvent(
                type="tool_use_start",
                tool_id="tool-1",
                tool_name="query_on_connector",
            )
            yield StreamEvent(
                type="tool_input_delta",
                tool_input_json='{"connector":"hubspot","query":"x"}',
            )
            yield StreamEvent(type="tool_use_stop")
            return

        yield StreamEvent(type="thinking_start")
        yield StreamEvent(type="thinking_delta", text="final reasoning")
        yield StreamEvent(type="thinking_stop")
        yield StreamEvent(type="text_delta", text="Final response")


def test_stream_with_tools_persists_final_deepseek_thinking_after_tool(monkeypatch) -> None:
    async def _fake_execute_tool(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"status": "success", "result": "ok"}

    monkeypatch.setattr("agents.orchestrator.execute_tool", _fake_execute_tool)

    orchestrator = ChatOrchestrator(
        user_id="u1",
        organization_id="org1",
        source="web",
    )
    adapter = _ThinkingToolThenFinalThinkingAdapter()
    orchestrator._adapter = adapter
    orchestrator._llm_config = SimpleNamespace(provider="deepseek")

    _, content_blocks = asyncio.run(_collect_stream_for_model(orchestrator, "deepseek-v4-pro"))

    thinking_blocks = [block for block in content_blocks if block["type"] == "thinking"]
    assert thinking_blocks == [
        {"type": "thinking", "thinking": "first reasoning"},
        {"type": "thinking", "thinking": "final reasoning"},
    ]
    assert content_blocks[-1] == {"type": "text", "text": "Final response"}


def test_load_history_replays_thinking_before_each_deepseek_tool_subturn(monkeypatch) -> None:
    saved_messages = [
        SimpleNamespace(
            role="assistant",
            content_blocks=[
                {"type": "thinking", "thinking": "reason for tool one"},
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "query_on_connector",
                    "input": {"connector": "hubspot", "query": "one"},
                    "result": {"status": "success", "rows": [1]},
                },
                {"type": "thinking", "thinking": "reason for tool two"},
                {
                    "type": "tool_use",
                    "id": "tool-2",
                    "name": "query_on_connector",
                    "input": {"connector": "hubspot", "query": "two"},
                    "result": {"status": "success", "rows": [2]},
                },
                {"type": "thinking", "thinking": "final reasoning"},
                {"type": "text", "text": "Final response"},
            ],
            _legacy_to_blocks=lambda: [],
        )
    ]

    monkeypatch.setattr(
        "agents.orchestrator.get_session",
        lambda **_kwargs: _FakeSessionManager(saved_messages),
    )

    orchestrator = ChatOrchestrator(
        user_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        conversation_id="00000000-0000-0000-0000-000000000003",
        source="web",
    )

    history = asyncio.run(orchestrator._load_history(limit=20, include_thinking_blocks=True))

    assert history[0]["role"] == "assistant"
    assert history[0]["content"][0] == {"type": "thinking", "thinking": "reason for tool one"}
    assert history[0]["content"][1]["id"] == "tool-1"
    assert history[1]["role"] == "user"
    assert history[1]["content"][0]["tool_use_id"] == "tool-1"
    assert history[2]["role"] == "assistant"
    assert history[2]["content"][0] == {"type": "thinking", "thinking": "reason for tool two"}
    assert history[2]["content"][1]["id"] == "tool-2"
    assert history[3]["role"] == "user"
    assert history[3]["content"][0]["tool_use_id"] == "tool-2"
    assert history[4] == {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "final reasoning"},
            {"type": "text", "text": "Final response"},
        ],
    }
