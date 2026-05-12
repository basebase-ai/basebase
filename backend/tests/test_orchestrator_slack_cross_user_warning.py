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
) -> list[str]:
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
    return out


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

    asyncio.run(_collect_stream_for_model(non_deepseek_orchestrator, "claude-opus-4-6"))

    non_deepseek_messages = non_deepseek_adapter.calls[1]["messages"]
    non_deepseek_assistant_content = non_deepseek_messages[1]["content"]
    assert all(block["type"] != "thinking" for block in non_deepseek_assistant_content)

    deepseek_orchestrator = ChatOrchestrator(
        user_id="u1",
        organization_id="org1",
        source="web",
    )
    deepseek_adapter = _ThinkingThenToolAdapter()
    deepseek_orchestrator._adapter = deepseek_adapter
    deepseek_orchestrator._llm_config = SimpleNamespace(provider="deepseek")

    asyncio.run(_collect_stream_for_model(deepseek_orchestrator, "deepseek-v4-pro"))

    deepseek_messages = deepseek_adapter.calls[1]["messages"]
    deepseek_assistant_content = deepseek_messages[1]["content"]
    assert deepseek_assistant_content[0] == {"type": "thinking", "thinking": "need a tool"}
