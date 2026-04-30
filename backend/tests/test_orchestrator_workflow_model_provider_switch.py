from agents import orchestrator


def test_resolve_provider_for_workflow_selected_model_uses_exact_match(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "provider_for_model",
        lambda model: "openai" if model == "gpt-5.5" else None,
    )
    monkeypatch.setattr(orchestrator, "get_model_provider_map", lambda: {})

    resolved = orchestrator._resolve_provider_for_workflow_selected_model(
        model="gpt-5.5",
        configured_provider="anthropic",
    )

    assert resolved == "openai"


def test_resolve_provider_for_workflow_selected_model_uses_approximate_allowlist(
    monkeypatch,
) -> None:
    monkeypatch.setattr(orchestrator, "provider_for_model", lambda _model: None)
    monkeypatch.setattr(orchestrator, "get_model_provider_map", lambda: {"gpt-5.5-mini": "openai"})

    resolved = orchestrator._resolve_provider_for_workflow_selected_model(
        model="gpt-5.5-mini-2026-04-14",
        configured_provider="anthropic",
    )

    assert resolved == "openai"


def test_resolve_provider_for_workflow_selected_model_rejects_truncated_prefix(
    monkeypatch,
) -> None:
    monkeypatch.setattr(orchestrator, "provider_for_model", lambda _model: None)
    monkeypatch.setattr(orchestrator, "get_model_provider_map", lambda: {"gpt-5.5-mini": "openai"})

    resolved = orchestrator._resolve_provider_for_workflow_selected_model(
        model="gpt-5",
        configured_provider="anthropic",
    )

    assert resolved is None
