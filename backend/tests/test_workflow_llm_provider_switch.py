from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.llm_adapter import LLMConfig
from workers.tasks import workflows


@pytest.mark.asyncio
async def test_action_llm_switches_provider_for_cross_family_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.llm_provider.resolve_llm_config",
        AsyncMock(
            return_value=LLMConfig(
                provider="anthropic",
                primary_model="claude-opus-4-6",
                cheap_model="claude-haiku-4-5-20251001",
                workflow_model="claude-opus-4-6",
                api_key="anthropic-key",
            )
        ),
        raising=False,
    )

    monkeypatch.setattr(
        "services.llm_provider.provider_for_model",
        lambda model: "openai" if model == "gpt-5.5" else None,
    )
    monkeypatch.setattr(
        "services.llm_provider.resolve_api_key_for_provider",
        AsyncMock(return_value="openai-key"),
    )

    monkeypatch.setattr(
        "access_control.check_external_api",
        AsyncMock(return_value=SimpleNamespace(allowed=True, deny_reason=None)),
    )

    captured = {}

    class _Adapter:
        async def complete(self, **kwargs):
            captured["model"] = kwargs["model"]
            return SimpleNamespace(content_blocks=[])

    def _get_adapter(cfg: LLMConfig) -> _Adapter:
        captured["provider"] = cfg.provider
        return _Adapter()

    monkeypatch.setattr("services.llm_provider.get_adapter", _get_adapter)
    monkeypatch.setattr(workflows, "report_anthropic_call_success", AsyncMock())

    result = await workflows._action_llm(
        params={"prompt": "Hello", "model": "gpt-5.5"},
        context={"organization_id": "org-1", "user_id": "user-1"},
    )

    assert result["status"] == "completed"
    assert captured["provider"] == "openai"
    assert captured["model"] == "gpt-5.5"


@pytest.mark.asyncio
async def test_action_llm_switches_provider_for_approximate_allowlisted_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.llm_provider.resolve_llm_config",
        AsyncMock(
            return_value=LLMConfig(
                provider="anthropic",
                primary_model="claude-opus-4-6",
                cheap_model="claude-haiku-4-5-20251001",
                workflow_model="claude-opus-4-6",
                api_key="anthropic-key",
            )
        ),
        raising=False,
    )
    monkeypatch.setattr("services.llm_provider.provider_for_model", lambda _model: None)
    monkeypatch.setattr(
        "services.llm_provider.get_model_provider_map",
        lambda: {"gpt-5.5-mini": "openai"},
    )
    monkeypatch.setattr(
        "services.llm_provider.resolve_api_key_for_provider",
        AsyncMock(return_value="openai-key"),
    )
    monkeypatch.setattr(
        "access_control.check_external_api",
        AsyncMock(return_value=SimpleNamespace(allowed=True, deny_reason=None)),
    )

    captured = {}

    class _Adapter:
        async def complete(self, **kwargs):
            captured["model"] = kwargs["model"]
            return SimpleNamespace(content_blocks=[])

    def _get_adapter(cfg: LLMConfig) -> _Adapter:
        captured["provider"] = cfg.provider
        return _Adapter()

    monkeypatch.setattr("services.llm_provider.get_adapter", _get_adapter)
    monkeypatch.setattr(workflows, "report_anthropic_call_success", AsyncMock())

    result = await workflows._action_llm(
        params={"prompt": "Hello", "model": "gpt-5.5-mini-2026-04-14"},
        context={"organization_id": "org-1", "user_id": "user-1"},
    )

    assert result["status"] == "completed"
    assert captured["provider"] == "openai"
    assert captured["model"] == "gpt-5.5-mini-2026-04-14"


@pytest.mark.asyncio
async def test_action_llm_does_not_switch_provider_for_truncated_model_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.llm_provider.resolve_llm_config",
        AsyncMock(
            return_value=LLMConfig(
                provider="anthropic",
                primary_model="claude-opus-4-6",
                cheap_model="claude-haiku-4-5-20251001",
                workflow_model="claude-opus-4-6",
                api_key="anthropic-key",
            )
        ),
        raising=False,
    )
    monkeypatch.setattr("services.llm_provider.provider_for_model", lambda _model: None)
    monkeypatch.setattr(
        "services.llm_provider.get_model_provider_map",
        lambda: {"gpt-5.5-mini": "openai"},
    )
    monkeypatch.setattr(
        "services.llm_provider.resolve_api_key_for_provider",
        AsyncMock(return_value="openai-key"),
    )
    monkeypatch.setattr(
        "access_control.check_external_api",
        AsyncMock(return_value=SimpleNamespace(allowed=True, deny_reason=None)),
    )

    captured = {}

    class _Adapter:
        async def complete(self, **kwargs):
            captured["model"] = kwargs["model"]
            return SimpleNamespace(content_blocks=[])

    def _get_adapter(cfg: LLMConfig) -> _Adapter:
        captured["provider"] = cfg.provider
        return _Adapter()

    monkeypatch.setattr("services.llm_provider.get_adapter", _get_adapter)
    monkeypatch.setattr(workflows, "report_anthropic_call_success", AsyncMock())

    result = await workflows._action_llm(
        params={"prompt": "Hello", "model": "gpt-5"},
        context={"organization_id": "org-1", "user_id": "user-1"},
    )

    assert result["status"] == "completed"
    assert captured["provider"] == "anthropic"
    assert captured["model"] == "gpt-5"
