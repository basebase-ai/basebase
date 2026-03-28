"""
Local integration test for external_notes.

Simulates the real connector flow against local Postgres:
1. Granola creates a meeting with notes via find_or_create_meeting
2. Fireflies adds notes to the same meeting (dedup match by title)
3. Gemini adds notes directly via set_notes
4. Verify all three coexist, summary priority is correct, DB round-trips work

Usage:
    cd backend
    DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/revenue_copilot" \
      venv/bin/python scripts/test_external_notes_local.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text

from models.database import get_admin_session
from models.meeting import Meeting
from services.meeting_dedup import find_or_create_meeting


# We need an org to satisfy the foreign key. Create one if needed.
ORG_ID = uuid4()
MEETING_TIME = datetime(2026, 3, 14, 15, 0, tzinfo=timezone.utc)


async def setup_org():
    """Create a test organization in the local DB."""
    async with get_admin_session() as session:
        await session.execute(text(
            "INSERT INTO organizations (id, name, created_at, updated_at, handle) "
            "VALUES (:id, :name, now(), now(), :handle) "
            "ON CONFLICT (id) DO NOTHING"
        ), {"id": ORG_ID, "name": "Test Org", "handle": "test-org-" + str(ORG_ID)[:8]})
        await session.commit()
    print(f"  org_id: {ORG_ID}")


async def step1_granola_creates_meeting():
    """Simulate Granola connector creating a meeting with notes."""
    print("\n── Step 1: Granola creates meeting with notes ──")

    meeting = await find_or_create_meeting(
        organization_id=ORG_ID,
        scheduled_start=MEETING_TIME,
        title="Weekly Standup",
        participants=[
            {"email": "alice@test.com", "name": "Alice"},
            {"email": "bob@test.com", "name": "Bob"},
        ],
        duration_minutes=30,
        organizer_email="alice@test.com",
        notes_source="granola",
        notes_text="Granola captured: Alice discussed Q1 goals, Bob gave sprint update.",
        status="completed",
    )

    print(f"  meeting_id: {meeting.id}")
    print(f"  summary: {meeting.summary!r}")
    print(f"  has granola notes: {meeting.has_notes_from('granola')}")
    print(f"  has gemini notes: {meeting.has_notes_from('gemini')}")
    assert meeting.has_notes_from("granola"), "Should have granola notes"
    assert meeting.summary == "Granola captured: Alice discussed Q1 goals, Bob gave sprint update."
    print("  PASS")
    return meeting.id


async def step2_fireflies_matches_same_meeting(expected_id):
    """Simulate Fireflies connector finding and updating the same meeting."""
    print("\n── Step 2: Fireflies matches same meeting by title, adds notes ──")

    meeting = await find_or_create_meeting(
        organization_id=ORG_ID,
        scheduled_start=MEETING_TIME,
        title="Weekly Standup",  # same title → should match
        participants=[
            {"email": "alice@test.com", "name": "Alice"},
            {"email": "bob@test.com", "name": "Bob"},
        ],
        notes_source="fireflies",
        notes_text="Fireflies transcript summary: Sprint velocity is on track.",
        status="completed",
    )

    print(f"  meeting_id: {meeting.id} (should match: {expected_id})")
    assert str(meeting.id) == str(expected_id), f"Should have matched existing meeting! Got {meeting.id}"
    print(f"  has granola notes: {meeting.has_notes_from('granola')}")
    print(f"  has fireflies notes: {meeting.has_notes_from('fireflies')}")
    print(f"  summary (granola > fireflies): {meeting.summary!r}")
    assert meeting.has_notes_from("granola"), "Granola notes should still be there"
    assert meeting.has_notes_from("fireflies"), "Should have fireflies notes now"
    # Granola is higher priority than fireflies
    assert "Granola" in meeting.summary, "Summary should be from granola (higher priority)"
    print("  PASS")


async def step3_gemini_adds_notes(meeting_id):
    """Simulate Gemini summary fetch writing directly via set_notes."""
    print("\n── Step 3: Gemini adds notes (highest priority) ──")

    async with get_admin_session() as session:
        meeting = await session.get(Meeting, meeting_id)
        meeting.set_notes(
            "gemini",
            "Gemini Notes: Weekly standup covering Q1 planning and sprint review.",
            doc_id="1drR_fake_doc_id",
        )
        await session.commit()
        await session.refresh(meeting)

    print(f"  has granola: {meeting.has_notes_from('granola')}")
    print(f"  has fireflies: {meeting.has_notes_from('fireflies')}")
    print(f"  has gemini: {meeting.has_notes_from('gemini')}")
    print(f"  summary (gemini wins): {meeting.summary!r}")
    assert meeting.has_notes_from("gemini"), "Should have gemini notes"
    assert "Gemini" in meeting.summary, "Summary should now be from gemini (highest priority)"
    print("  PASS")


async def step4_second_gemini_doc(meeting_id):
    """Simulate a second Gemini doc being found for the same meeting."""
    print("\n── Step 4: Second Gemini doc appends (doesn't overwrite) ──")

    async with get_admin_session() as session:
        meeting = await session.get(Meeting, meeting_id)
        meeting.set_notes(
            "gemini",
            "Gemini Notes v2: Updated summary with action items.",
            doc_id="1v53_second_doc_id",
        )
        await session.commit()
        await session.refresh(meeting)

    print(f"  gemini entries: {len(meeting.external_notes['gemini'])}")
    print(f"  summary (latest gemini): {meeting.summary!r}")
    assert len(meeting.external_notes["gemini"]) == 2, "Should have 2 gemini entries"
    assert "v2" in meeting.summary, "Summary should be from latest gemini entry"
    print("  PASS")


async def step5_verify_db_roundtrip(meeting_id):
    """Fresh read from DB to verify everything persisted correctly."""
    print("\n── Step 5: Fresh DB read — verify persistence ──")

    async with get_admin_session() as session:
        meeting = await session.get(Meeting, meeting_id)

    print(f"  sources: {list(meeting.external_notes.keys())}")
    print(f"  granola entries: {len(meeting.external_notes['granola'])}")
    print(f"  fireflies entries: {len(meeting.external_notes['fireflies'])}")
    print(f"  gemini entries: {len(meeting.external_notes['gemini'])}")
    print(f"  summary: {meeting.summary!r}")

    assert set(meeting.external_notes.keys()) == {"granola", "fireflies", "gemini"}
    assert len(meeting.external_notes["granola"]) == 1
    assert len(meeting.external_notes["fireflies"]) == 1
    assert len(meeting.external_notes["gemini"]) == 2
    assert "v2" in meeting.summary

    # Verify to_dict includes external_notes
    d = meeting.to_dict()
    assert "external_notes" in d
    assert d["external_notes"] is not None

    # Verify missing_notes_filter works against real DB
    result = await session.execute(
        select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.missing_notes_filter("copilot"),  # no copilot notes
        )
    )
    assert result.scalar_one_or_none() is not None, "Should match missing_notes_filter for copilot"

    result = await session.execute(
        select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.missing_notes_filter("gemini"),  # has gemini notes
        )
    )
    assert result.scalar_one_or_none() is None, "Should NOT match missing_notes_filter for gemini"

    print("  PASS")


async def step6_duplicate_skip(meeting_id):
    """Verify duplicate content is skipped (no-op on repeated sync)."""
    print("\n── Step 6: Duplicate content skip ──")

    async with get_admin_session() as session:
        meeting = await session.get(Meeting, meeting_id)
        before_count = len(meeting.external_notes["granola"])
        meeting.set_notes("granola", "Granola captured: Alice discussed Q1 goals, Bob gave sprint update.")
        await session.commit()
        await session.refresh(meeting)

    assert len(meeting.external_notes["granola"]) == before_count, "Should not add duplicate"
    print(f"  granola entries still: {len(meeting.external_notes['granola'])}")
    print("  PASS")


async def cleanup(meeting_id):
    """Remove test data."""
    async with get_admin_session() as session:
        meeting = await session.get(Meeting, meeting_id)
        if meeting:
            await session.delete(meeting)
        await session.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": ORG_ID})
        await session.commit()
    print("\n  Cleaned up test data.")


async def main():
    print("=" * 60)
    print("External Notes — Local Integration Test")
    print("=" * 60)

    await setup_org()

    meeting_id = await step1_granola_creates_meeting()
    await step2_fireflies_matches_same_meeting(meeting_id)
    await step3_gemini_adds_notes(meeting_id)
    await step4_second_gemini_doc(meeting_id)
    await step5_verify_db_roundtrip(meeting_id)
    await step6_duplicate_skip(meeting_id)

    await cleanup(meeting_id)

    print("\n" + "=" * 60)
    print("ALL STEPS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
