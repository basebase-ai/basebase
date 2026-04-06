#!/usr/bin/env python3
"""
Backfill: generate LLM summaries and titles for recent conversations.

Iterates across all orgs, finds agent conversations updated within --since-days,
and runs the same summary + title generators used in post-completion.
Conversations that already have a summary / upgraded title are skipped
automatically by the generators' internal checks.

Usage:
    cd backend && python scripts/backfill_conversation_summaries.py [--since-days 14] [--limit 500] [--delay 0.35] [--org ORG_ID]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, desc, update

from models.conversation import Conversation
from models.database import get_admin_session
from services.conversation_summary import (
    generate_conversation_summary,
    generate_conversation_title,
)


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


async def backfill(
    since_days: int,
    limit: int,
    delay: float,
    org_id: str | None,
    force_titles: bool = False,
) -> None:
    cutoff: datetime = datetime.utcnow() - timedelta(days=since_days)

    if force_titles:
        async with get_admin_session() as session:
            where_clause = [
                Conversation.type == "agent",
                Conversation.organization_id.isnot(None),
                Conversation.updated_at >= cutoff,
                Conversation.title_llm_upgraded == True,  # noqa: E712
            ]
            if org_id:
                where_clause.append(Conversation.organization_id == org_id)
            result = await session.execute(
                update(Conversation)
                .where(*where_clause)
                .values(title_llm_upgraded=False)
            )
            await session.commit()
            _log(f"Reset title_llm_upgraded for {result.rowcount} conversations (--force-titles)")

    async with get_admin_session() as session:
        q = (
            select(
                Conversation.id,
                Conversation.organization_id,
                Conversation.title,
                Conversation.message_count,
                Conversation.summary_word_count,
                Conversation.title_llm_upgraded,
            )
            .where(
                Conversation.type == "agent",
                Conversation.organization_id.isnot(None),
                Conversation.updated_at >= cutoff,
            )
            .order_by(desc(Conversation.updated_at))
            .limit(limit)
        )
        if org_id:
            q = q.where(Conversation.organization_id == org_id)
        rows = (await session.execute(q)).all()

    total: int = len(rows)
    already_done: int = sum(1 for r in rows if r.title_llm_upgraded and r.summary_word_count)
    _log(f"Found {total} conversations (last {since_days}d). {already_done} already have both title+summary.")

    summaries_done: int = 0
    titles_done: int = 0
    skipped: int = 0
    errors: int = 0
    t0: float = time.monotonic()

    for i, row in enumerate(rows, 1):
        conv_id: str = str(row.id)
        oid: str = str(row.organization_id)
        title_short: str = (row.title or "Untitled")[:40]

        s: str | None = None
        t: str | None = None
        try:
            s = await generate_conversation_summary(conv_id, oid)
            if s:
                summaries_done += 1
            t = await generate_conversation_title(conv_id, oid)
            if t:
                titles_done += 1
        except Exception as exc:
            errors += 1
            _log(f"  ERROR #{i} \"{title_short}\": {exc}")

        if not s and not t:
            skipped += 1

        elapsed: float = time.monotonic() - t0
        rate: float = i / elapsed if elapsed > 0 else 0
        eta: float = (total - i) / rate if rate > 0 else 0

        if s or t:
            parts: list[str] = []
            if s:
                parts.append(f"summary={len(s)}ch")
            if t:
                parts.append(f"title=\"{t[:50]}\"")
            _log(f"  {i}/{total} ✓ \"{title_short}\" → {', '.join(parts)}")
        elif i % 25 == 0 or i == total:
            _log(
                f"  {i}/{total} — "
                f"generated: {summaries_done}S {titles_done}T, "
                f"skipped: {skipped}, errors: {errors} "
                f"({rate:.1f}/s, ~{eta:.0f}s left)"
            )

        if delay > 0 and i < total:
            await asyncio.sleep(delay)

    elapsed_total: float = time.monotonic() - t0
    _log(
        f"\nDone in {elapsed_total:.1f}s. "
        f"Processed: {total}, "
        f"summaries: {summaries_done}, titles: {titles_done}, "
        f"skipped: {skipped}, errors: {errors}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill conversation summaries and titles")
    parser.add_argument("--since-days", type=int, default=14, help="Only conversations updated within this many days (default: 14)")
    parser.add_argument("--limit", type=int, default=500, help="Max conversations to process (default: 500)")
    parser.add_argument("--delay", type=float, default=0.35, help="Seconds between API calls (default: 0.35)")
    parser.add_argument("--org", type=str, default=None, help="Only this organization ID")
    parser.add_argument("--force-titles", action="store_true", help="Reset title_llm_upgraded and regenerate all titles")
    args = parser.parse_args()
    asyncio.run(backfill(since_days=args.since_days, limit=args.limit, delay=args.delay, org_id=args.org, force_titles=args.force_titles))


if __name__ == "__main__":
    main()
