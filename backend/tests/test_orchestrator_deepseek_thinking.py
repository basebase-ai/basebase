import asyncio
from types import SimpleNamespace

from agents.orchestrator import ChatOrchestrator
from services.llm_adapter import StreamEvent


class _DeepSeekThinkingToolAdapter:
    def __init__(self) -> None:
        self._calls = 0
        self.calls: list[dict[str, object]] = []

    async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
        self._calls += 1
        self.calls.append(kwargs)
        if self._calls == 1:
            yield StreamEvent(type="thinking_start")
            yield StreamEvent(type="thinking_delta", text="I should look this up.")
            yield StreamEvent(type="thinking_stop")
            yield StreamEvent(type="text_delta", text="Let me check.")
            yield StreamEvent(type="tool_use_start", tool_id="tool-1", tool_name="query_on_connector")
            yield StreamEvent(type="tool_input_delta", tool_input_json='{"connector":"hubspot","query":"x"}')
            yield StreamEvent(type="tool_use_stop")
            return

        yield StreamEvent(type="text_delta", text="Final response")
        yield StreamEvent(type="text_stop")


async def _collect_deepseek_stream(orchestrator: ChatOrchestrator):  # type: ignore[no-untyped-def]
    messages = [{"role": "user", "content": "hi"}]
    content_blocks: list[dict[str, object]] = []
    chunks: list[str] = []
    async for chunk in orchestrator._stream_with_tools(
        messages,
        "sys",
        content_blocks,
        "deepseek-v4-pro",
    ):
        chunks.append(chunk)
    return chunks, content_blocks, messages


def test_stream_with_tools_persists_deepseek_thinking_for_tool_turns(monkeypatch) -> None:
    orchestrator = ChatOrchestrator(
        user_id="u1",
        organization_id="org1",
        source="web",
    )
    adapter = _DeepSeekThinkingToolAdapter()
    orchestrator._adapter = adapter
    orchestrator._llm_config = SimpleNamespace(provider="deepseek")

    async def _fake_execute_tool(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {"status": "success", "rows": []}

    monkeypatch.setattr("agents.orchestrator.execute_tool", _fake_execute_tool)

    _chunks, content_blocks, messages = asyncio.run(_collect_deepseek_stream(orchestrator))

    assert content_blocks[:3] == [
        {"type": "thinking", "thinking": "I should look this up."},
        {"type": "text", "text": "Let me check."},
        {
            "type": "tool_use",
            "id": "tool-1",
            "name": "query_on_connector",
            "input": {"connector": "hubspot", "query": "x"},
            "result": {"status": "success", "rows": []},
            "status": "complete",
        },
    ]
    assert {"type": "text", "text": "Final response"} in content_blocks

    assistant_message = messages[1]
    assert assistant_message == {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "I should look this up."},
            {"type": "text", "text": "Let me check."},
            {
                "type": "tool_use",
                "id": "tool-1",
                "name": "query_on_connector",
                "input": {"connector": "hubspot", "query": "x"},
            },
        ],
    }
    second_call_messages = adapter.calls[1]["messages"]
    assert second_call_messages[1] == assistant_message
