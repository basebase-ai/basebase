import asyncio
import sys
import types

fake_websockets = types.ModuleType("api.websockets")


async def _broadcast_sync_progress(*_args: object, **_kwargs: object) -> None:
    return None


fake_websockets.broadcast_sync_progress = _broadcast_sync_progress
sys.modules.setdefault("api.websockets", fake_websockets)

from agents.tools import (
    ORG_LEVEL_MEMORY_ERROR,
    _save_memory,
    _validate_memory_entity_type,
    execute_save_memory,
)


def test_validate_memory_entity_type_rejects_org_scope() -> None:
    assert _validate_memory_entity_type("organization") == ORG_LEVEL_MEMORY_ERROR


def test_save_memory_rejects_org_scope_with_coherent_error() -> None:
    result = asyncio.run(
        _save_memory(
            params={
                "content": "Remember this for everyone in the org",
                "entity_type": "organization",
            },
            organization_id="00000000-0000-0000-0000-000000000010",
            user_id="00000000-0000-0000-0000-000000000001",
            skip_approval=False,
        )
    )

    assert result == {"error": ORG_LEVEL_MEMORY_ERROR}


def test_execute_save_memory_rejects_org_scope_before_db_work() -> None:
    result = asyncio.run(
        execute_save_memory(
            params={
                "content": "Remember this for everyone in the org",
                "entity_type": "organization",
            },
            organization_id="00000000-0000-0000-0000-000000000010",
            user_id="00000000-0000-0000-0000-000000000001",
        )
    )

    assert result == {
        "status": "failed",
        "error": ORG_LEVEL_MEMORY_ERROR,
    }
