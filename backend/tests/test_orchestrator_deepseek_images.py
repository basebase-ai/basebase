from __future__ import annotations

from typing import Any

import pytest

from agents import orchestrator as orchestrator_module
from agents.orchestrator import ChatOrchestrator
from services.llm_adapter import (
    DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE,
    DeepSeekImageUnsupportedError,
    LLMConfig,
)


class _RejectingAdapter:
    async def stream(self, *_args: Any, **_kwargs: Any):
        if False:
            yield None
        raise DeepSeekImageUnsupportedError(DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE)


@pytest.mark.asyncio
async def test_orchestrator_streams_friendly_deepseek_image_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator_module, "get_tool_defs_for_context", lambda _ctx: [])

    orchestrator = ChatOrchestrator(
        user_id="00000000-0000-0000-0000-000000000001",
        organization_id="00000000-0000-0000-0000-000000000002",
        conversation_id="00000000-0000-0000-0000-000000000003",
    )
    orchestrator._adapter = _RejectingAdapter()  # noqa: SLF001
    orchestrator._llm_config = LLMConfig(  # noqa: SLF001
        provider="deepseek",
        primary_model="deepseek-v4-pro",
        cheap_model="deepseek-v4-pro",
        workflow_model="deepseek-v4-pro",
        api_key="test-key",
        base_url="https://api.deepseek.com",
    )

    content_blocks: list[dict[str, Any]] = []
    chunks = [
        chunk
        async for chunk in orchestrator._stream_with_tools(  # noqa: SLF001
            messages=[{"role": "user", "content": [{"type": "image", "source": {}}]}],
            system_prompt="system",
            content_blocks=content_blocks,
            model_name="deepseek-v4-pro",
        )
    ]

    assert chunks == [DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE]
    assert content_blocks == [
        {"type": "text", "text": DEEPSEEK_V4_IMAGE_UNSUPPORTED_MESSAGE}
    ]
