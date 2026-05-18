from decimal import Decimal

from services.llm_pricing import compute_credit_cost


def test_compute_credit_cost_minimum_one() -> None:
    credits = compute_credit_cost(
        input_tokens=0,
        output_tokens=0,
        input_cost_per_m=Decimal("15"),
        output_cost_per_m=Decimal("75"),
    )
    assert credits == 1


def test_compute_credit_cost_scales_with_tokens() -> None:
    # 1M input tokens at $2.5/M => $2.5 => 2500 credits
    credits = compute_credit_cost(
        input_tokens=1_000_000,
        output_tokens=0,
        input_cost_per_m=Decimal("2.5"),
        output_cost_per_m=Decimal("10"),
    )
    assert credits == 2500


def test_compute_credit_cost_mixed_io() -> None:
    # 1000 in @ $15/M + 500 out @ $75/M
    credits = compute_credit_cost(
        input_tokens=1000,
        output_tokens=500,
        input_cost_per_m=Decimal("15"),
        output_cost_per_m=Decimal("75"),
    )
    # $0.015 + $0.0375 = $0.0525 => 53 credits (ceil)
    assert credits == 53
