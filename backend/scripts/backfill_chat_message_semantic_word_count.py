#!/usr/bin/env python3
"""
Backfill ``chat_messages.semantic_word_count`` for rows written before the
denormalization landed (migration 142).

The column was added with ``DEFAULT 0`` so existing rows have a wrong (always
zero) value until this script runs. New writes are kept correct by the
``before_insert`` / ``before_update`` event listener on the ChatMessage model.

Strategy: batched, online, idempotent. Picks rows with
``semantic_word_count = 0 AND content_blocks IS NOT NULL`` and recomputes from
``content_blocks``. Idle rows that genuinely have zero text words (tool-only
messages, attachment-only messages) get re-checked each pass and stay at 0,
which is correct — they just incur a bit of extra work on each run. Use
``--once`` to do a single pass and exit; default loops until no rows match.

Usage:
    cd backend && python scripts/backfill_chat_message_semantic_word_count.py
    cd backend && python scripts/backfill_chat_message_semantic_word_count.py --batch 5000 --delay 0.5 --once
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from models.chat_message import semantic_word_count_from_blocks
from models.database import get_admin_session


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


async def _backfill_batch(batch: int) -> int:
    """Update one batch. Returns the number of rows updated."""
    # Pick the oldest un-backfilled rows that actually have content_blocks. We
    # filter on ``semantic_word_count = 0`` and ``content_blocks IS NOT NULL``
    # so we never reread a row whose backfill produced a non-zero value.
    select_sql = text(
        """
        SELECT id, content_blocks
        FROM chat_messages
        WHERE semantic_word_count = 0
          AND content_blocks IS NOT NULL
        ORDER BY created_at ASC NULLS LAST
        LIMIT :batch
        FOR UPDATE SKIP LOCKED
        """
    )

    async with get_admin_session() as session:
        rows = (await session.execute(select_sql, {"batch": batch})).all()
        if not rows:
            return 0

        # Compute new values in Python (cheap; saves a server-side jsonb walk).
        # Group rows by computed count so the UPDATE fires once per distinct
        # value rather than once per row — most messages share the count of 0
        # (tool-only / attachment-only) so this collapses dramatically.
        by_count: dict[int, list[Any]] = {}
        for row_id, blocks in rows:
            count = semantic_word_count_from_blocks(blocks)
            by_count.setdefault(count, []).append(row_id)

        updated = 0
        for count, ids in by_count.items():
            # Skip the all-zero bucket — column already 0, no-op write would
            # just churn the row and trigger our own event listener.
            if count == 0:
                continue
            res = await session.execute(
                text(
                    """
                    UPDATE chat_messages
                    SET semantic_word_count = :count
                    WHERE id = ANY(:ids)
                    """
                ),
                {"count": count, "ids": ids},
            )
            updated += int(res.rowcount or 0)

        await session.commit()
        return updated


async def backfill(batch: int, delay: float, once: bool) -> None:
    total_updated = 0
    started = time.monotonic()
    pass_index = 0

    while True:
        pass_index += 1
        try:
            updated = await _backfill_batch(batch)
        except Exception as exc:
            _log(f"ERROR in batch {pass_index}: {exc}")
            await asyncio.sleep(max(delay * 5, 2.0))
            continue

        total_updated += updated
        elapsed = time.monotonic() - started
        rate = total_updated / elapsed if elapsed > 0 else 0.0
        _log(
            f"batch {pass_index}: updated={updated} total={total_updated} "
            f"elapsed={elapsed:.1f}s rate={rate:.0f}/s"
        )

        if updated == 0:
            _log("no more rows to backfill — done")
            return
        if once:
            return
        await asyncio.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=2000, help="Rows per batch (default: 2000)")
    parser.add_argument("--delay", type=float, default=0.25, help="Sleep between batches in seconds (default: 0.25)")
    parser.add_argument("--once", action="store_true", help="Run a single batch and exit")
    args = parser.parse_args()

    asyncio.run(backfill(args.batch, args.delay, args.once))


if __name__ == "__main__":
    main()
