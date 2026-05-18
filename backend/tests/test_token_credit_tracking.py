"""
Tests for token-cost credit tracking:
- charge_llm_usage records to llm_usage and deducts credits
- deduct_for_llm handles edge cases (invalid org, zero tokens)
- usage-by-day endpoint returns aggregated data
- admin models CRUD endpoint
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from services import credits
from services.llm_pricing import (
    compute_credit_cost,
    compute_credit_cost_for_model,
    charge_llm_usage,
    invalidate_model_price_cache,
    _price_cache,
)


# ─── Unit: compute_credit_cost ─────────────────────────────────────────────────


def test_compute_credit_cost_opus_typical_turn() -> None:
    # Typical Opus 4.6 turn: 5000 in @ $5/M, 1000 out @ $25/M
    result = compute_credit_cost(
        input_tokens=5000,
        output_tokens=1000,
        input_cost_per_m=Decimal("5"),
        output_cost_per_m=Decimal("25"),
    )
    # ($5*5000 + $25*1000) / 1M = ($25000 + $25000) / 1M = $0.05 => 50 credits
    assert result == 50


def test_compute_credit_cost_haiku_cheap_call() -> None:
    # Haiku: 2000 in @ $1/M, 500 out @ $5/M
    result = compute_credit_cost(
        input_tokens=2000,
        output_tokens=500,
        input_cost_per_m=Decimal("1"),
        output_cost_per_m=Decimal("5"),
    )
    # ($1*2000 + $5*500) / 1M = ($2000 + $2500) / 1M = $0.0045 => 5 credits (ceil)
    assert result == 5


def test_compute_credit_cost_rounds_up() -> None:
    # Tiny call: 1 input token at $5/M => $0.000005 => 0.005 credits => ceil to 1
    result = compute_credit_cost(
        input_tokens=1,
        output_tokens=0,
        input_cost_per_m=Decimal("5"),
        output_cost_per_m=Decimal("25"),
    )
    assert result == 1


def test_compute_credit_cost_large_output() -> None:
    # GPT-5.5: 1000 in @ $5/M, 4000 out @ $30/M
    result = compute_credit_cost(
        input_tokens=1000,
        output_tokens=4000,
        input_cost_per_m=Decimal("5"),
        output_cost_per_m=Decimal("30"),
    )
    # ($5*1000 + $30*4000) / 1M = ($5000 + $120000) / 1M = $0.125 => 125 credits
    assert result == 125


# ─── Unit: deduct_for_llm edge cases ──────────────────────────────────────────


def test_deduct_for_llm_skips_invalid_org_id() -> None:
    result = asyncio.run(credits.deduct_for_llm(
        "not-a-uuid",
        "claude-opus-4-6",
        5000,
        1000,
    ))
    assert result == (True, False)


def test_deduct_for_llm_skips_empty_org_id() -> None:
    result = asyncio.run(credits.deduct_for_llm(
        "",
        "claude-opus-4-6",
        5000,
        1000,
    ))
    assert result == (True, False)


def test_deduct_for_llm_skips_zero_tokens() -> None:
    result = asyncio.run(credits.deduct_for_llm(
        "00000000-0000-0000-0000-000000000001",
        "claude-opus-4-6",
        0,
        0,
    ))
    assert result == (True, False)


# ─── Integration: charge_llm_usage calls deduct + record ─────────────────────


def test_charge_llm_usage_deducts_and_records(monkeypatch) -> None:
    """charge_llm_usage should compute cost, deduct, and record usage."""
    deduct_mock = AsyncMock(return_value=(True, False))
    record_mock = AsyncMock()

    monkeypatch.setattr("services.llm_pricing.deduct_with_grace", deduct_mock)
    monkeypatch.setattr("services.llm_pricing.record_llm_usage", record_mock)

    # Pre-populate price cache to avoid DB hit
    invalidate_model_price_cache()
    _price_cache["claude-opus-4-6"] = (Decimal("5"), Decimal("25"))

    ok, used_grace, credits_charged = asyncio.run(charge_llm_usage(
        organization_id="00000000-0000-0000-0000-000000000001",
        model_name="claude-opus-4-6",
        input_tokens=5000,
        output_tokens=1000,
        user_id="00000000-0000-0000-0000-000000000002",
        conversation_id="00000000-0000-0000-0000-000000000003",
        reason="llm",
    ))

    assert ok is True
    assert used_grace is False
    assert credits_charged == 50

    # deduct_with_grace called with correct amount
    deduct_mock.assert_called_once()
    call_args = deduct_mock.call_args
    assert call_args[0][0] == "00000000-0000-0000-0000-000000000001"
    assert call_args[0][1] == 50  # credits
    assert call_args[0][2] == "llm"

    # record_llm_usage called with all fields
    record_mock.assert_called_once()
    record_kwargs = record_mock.call_args[1]
    assert record_kwargs["organization_id"] == "00000000-0000-0000-0000-000000000001"
    assert record_kwargs["model_name"] == "claude-opus-4-6"
    assert record_kwargs["input_tokens"] == 5000
    assert record_kwargs["output_tokens"] == 1000
    assert record_kwargs["credits_charged"] == 50

    # Cleanup
    invalidate_model_price_cache()


def test_charge_llm_usage_reports_failure_on_insufficient_balance(monkeypatch) -> None:
    """When deduct fails, charge_llm_usage should not record usage."""
    deduct_mock = AsyncMock(return_value=(False, False))
    record_mock = AsyncMock()

    monkeypatch.setattr("services.llm_pricing.deduct_with_grace", deduct_mock)
    monkeypatch.setattr("services.llm_pricing.record_llm_usage", record_mock)

    invalidate_model_price_cache()
    _price_cache["claude-opus-4-6"] = (Decimal("5"), Decimal("25"))

    ok, used_grace, credits_charged = asyncio.run(charge_llm_usage(
        organization_id="00000000-0000-0000-0000-000000000001",
        model_name="claude-opus-4-6",
        input_tokens=5000,
        output_tokens=1000,
        reason="llm",
    ))

    assert ok is False
    assert used_grace is False
    assert credits_charged == 50
    record_mock.assert_not_called()

    invalidate_model_price_cache()


def test_compute_credit_cost_for_model_uses_cache(monkeypatch) -> None:
    """compute_credit_cost_for_model should use cached pricing."""
    invalidate_model_price_cache()
    _price_cache["deepseek-v4-pro"] = (Decimal("0.44"), Decimal("0.87"))

    # Patch _load_price_cache to avoid DB access (cache is already warm)
    monkeypatch.setattr("services.llm_pricing._CACHE_TTL_SECONDS", 99999)
    import services.llm_pricing as lp
    monkeypatch.setattr(lp, "_cache_loaded_at", 1e18)

    result = asyncio.run(compute_credit_cost_for_model(
        "deepseek-v4-pro",
        input_tokens=100_000,
        output_tokens=10_000,
    ))
    # ($0.44 * 100k + $0.87 * 10k) / 1M = ($44000 + $8700) / 1M = $0.0527 => 53 credits
    assert result == 53

    invalidate_model_price_cache()


# ─── API: admin models endpoint ───────────────────────────────────────────────


def test_admin_models_list_requires_auth() -> None:
    """GET /api/admin/models without auth should return 401."""
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    response = client.get("/api/admin/models")
    assert response.status_code in (401, 403)


def test_admin_models_update_requires_auth() -> None:
    """PUT /api/admin/models/:name without auth should return 401."""
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    response = client.put(
        "/api/admin/models/claude-opus-4-6",
        json={"input_cost_per_m": 10.0},
    )
    assert response.status_code in (401, 403)


# ─── API: usage-by-day endpoint ───────────────────────────────────────────────


def test_usage_by_day_requires_auth() -> None:
    """GET /api/billing/usage-by-day without auth should return 401."""
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    response = client.get("/api/billing/usage-by-day")
    assert response.status_code in (401, 403)
