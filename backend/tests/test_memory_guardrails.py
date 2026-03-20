from pathlib import Path

from agents.memory_guardrails import (
    ORG_LEVEL_MEMORY_ERROR,
    normalize_memory_entity_type,
    validate_memory_entity_type,
)


def test_validate_memory_entity_type_rejects_org_level_scope() -> None:
    assert validate_memory_entity_type("organization") == ORG_LEVEL_MEMORY_ERROR
    assert validate_memory_entity_type("workspace") == ORG_LEVEL_MEMORY_ERROR


def test_normalize_memory_entity_type_defaults_to_user() -> None:
    assert normalize_memory_entity_type(None) == "user"
    assert normalize_memory_entity_type(" Organization_Member ") == "organization_member"


def test_tools_module_uses_memory_entity_type_guardrail() -> None:
    tools_source = Path("backend/agents/tools.py").read_text()

    assert "validate_memory_entity_type(entity_type)" in tools_source
    assert "normalize_memory_entity_type(params.get(\"entity_type\", \"user\"))" in tools_source
