"""Tests for services.credits.record_grant audit-row helper."""
from __future__ import annotations

import asyncio
from uuid import UUID

from services import credits as credits_service


class _FakeSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)


def test_record_grant_writes_positive_audit_row() -> None:
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    session = _FakeSession()

    asyncio.run(
        credits_service.record_grant(
            session,
            organization_id=org_id,
            amount=950,
            balance_after=1000,
            reason="subscription_renewal:pro",
            reference_type="stripe_invoice",
            reference_id="in_123",
            user_id=user_id,
        )
    )

    assert len(session.added) == 1
    tx = session.added[0]
    assert tx.organization_id == org_id
    assert tx.user_id == user_id
    assert tx.amount == 950
    assert tx.balance_after == 1000
    assert tx.reason == "subscription_renewal:pro"
    assert tx.reference_type == "stripe_invoice"
    assert tx.reference_id == "in_123"


def test_record_grant_skips_non_positive_amounts() -> None:
    """If a caller passes a zero/negative delta (e.g. balance was reset
    downward), we silently no-op rather than write a misleading audit row."""
    org_id = UUID("33333333-3333-3333-3333-333333333333")
    session = _FakeSession()

    asyncio.run(
        credits_service.record_grant(
            session,
            organization_id=org_id,
            amount=0,
            balance_after=100,
            reason="noop",
        )
    )
    asyncio.run(
        credits_service.record_grant(
            session,
            organization_id=org_id,
            amount=-50,
            balance_after=50,
            reason="noop",
        )
    )

    assert session.added == []


def test_record_grant_truncates_long_reason() -> None:
    """reason column is varchar(64); helper must truncate to fit."""
    org_id = UUID("44444444-4444-4444-4444-444444444444")
    session = _FakeSession()
    long_reason = "x" * 100

    asyncio.run(
        credits_service.record_grant(
            session,
            organization_id=org_id,
            amount=10,
            balance_after=10,
            reason=long_reason,
        )
    )

    assert len(session.added[0].reason) == 64
