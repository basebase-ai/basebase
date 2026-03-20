from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ORG_LEVEL_MEMORY_ENTITY_TYPES = {
    "org",
    "org_level",
    "organization",
    "organization-level",
    "organization_level",
    "team",
    "workspace",
    "company",
}
ORG_LEVEL_MEMORY_ERROR = (
    "Organization-level memories are not allowed. "
    "I can only save memories for an individual user or their organization-member role."
)


def normalize_memory_entity_type(entity_type: Any) -> str:
    if entity_type is None:
        return "user"
    return str(entity_type).strip().lower()


def validate_memory_entity_type(entity_type: str) -> str | None:
    if entity_type in ORG_LEVEL_MEMORY_ENTITY_TYPES:
        logger.info("[MemoryGuardrails] Blocked org-level memory attempt for entity_type=%s", entity_type)
        return ORG_LEVEL_MEMORY_ERROR
    if entity_type not in ("user", "organization_member"):
        return (
            f"Invalid entity_type '{entity_type}'. "
            "Must be 'user' or 'organization_member'."
        )
    return None
