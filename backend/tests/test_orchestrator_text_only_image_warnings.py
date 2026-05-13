from __future__ import annotations

from typing import Any

import pytest

from agents import orchestrator as orchestrator_module
from agents.orchestrator import ChatOrchestrator
from services.llm_adapter import (
    DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE,
    MINIMAX_IMAGE_UNSUPPORTED_MESSAGE,
    DeepSeekImageUnsupportedError,
    LLMConfig,
)


class _RejectingAdapter:
    def __init__(self, message: str) -> None:
        self._message = message

    async def stream(self, *_args: Any, **_kwargs: Any):
        if False:
            yield None
        raise DeepSeekImageUnsupportedError(self._message)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "message"),
    [
        ("deepseek", "deepseek-v4-pro", DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE),
        ("minimax", "MiniMax-M2.7", MINIMAX_IMAGE_UNSUPPORTED_MESSAGE),
    ],
)
async def test_orchestrator_streams_friendly_text_only_image_error(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
    message: str,
) -> None:
    monkeypatch.setattr(orchestrator_module, "get_tool_defs_for_context", lambda _ctx: [])

    orchestrator = ChatOrchestrator(
        user_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        conversation_id="00000000-0000-0000-0000-000000000003",
    )
    orchestrator._adapter = _RejectingAdapter(message)  # noqa: SLF001
    orchestrator._llm_config = LLMConfig(  # noqa: SLF001
        provider=provider,  # type: ignore[arg-type]
        primary_model=model,
        cheap_model=model,
        workflow_model=model,
        api_key="test-key",
        base_url="https://example.invalid",
    )

    content_blocks: list[dict[str, Any]] = []
    chunks = [
        chunk
        async for chunk in orchestrator._stream_with_tools(  # noqa: SLF001
            messages=[{"role": "user", "content": [{"type": "image", "source": {}}]}],
            system_prompt="system",
            content_blocks=content_blocks,
            model_name=model,
        )
    ]

    assert chunks == [message]
    assert content_blocks == [{"type": "text", "text": message}]
