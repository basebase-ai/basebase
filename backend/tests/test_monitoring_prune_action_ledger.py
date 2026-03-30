from unittest.mock import AsyncMock, patch

from workers.tasks import monitoring

def test_prune_action_ledger_deletes_old_rows_and_stops_when_under_target() -> None:
    # First loop (retention): delete 3, then 0.
    # Size loop: starts above max, delete 2 rows, drops below target.
    delete_side_effects = [3, 0, 2]
    size_side_effects = [
        monitoring._ACTION_LEDGER_MAX_BYTES + 10,
        monitoring._ACTION_LEDGER_TARGET_BYTES - 10,
        monitoring._ACTION_LEDGER_TARGET_BYTES - 10,
    ]

    with patch("workers.tasks.monitoring._delete_action_ledger_batch", new=AsyncMock(side_effect=delete_side_effects)), \
         patch("workers.tasks.monitoring._action_ledger_total_bytes", new=AsyncMock(side_effect=size_side_effects)):
        result = monitoring.prune_action_ledger.run()

    assert result["status"] == "ok"
    assert result["deleted_for_age"] == 3
    assert result["deleted_for_size"] == 2
    assert result["final_size_bytes"] == monitoring._ACTION_LEDGER_TARGET_BYTES - 10


def test_prune_action_ledger_stops_size_loop_when_nothing_deleted() -> None:
    with patch("workers.tasks.monitoring._delete_action_ledger_batch", new=AsyncMock(side_effect=[0, 0])), \
         patch("workers.tasks.monitoring._action_ledger_total_bytes", new=AsyncMock(side_effect=[
             monitoring._ACTION_LEDGER_MAX_BYTES + 1,
             monitoring._ACTION_LEDGER_MAX_BYTES + 1,
         ])):
        result = monitoring.prune_action_ledger.run()

    assert result["status"] == "ok"
    assert result["deleted_for_age"] == 0
    assert result["deleted_for_size"] == 0
