"""
LLM token pricing and usage metering.

1 credit = $0.001 of estimated LLM spend (1000 credits per dollar).
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal, ROUND_CEILING
from typing import Final
from uuid import UUID

from sqlalchemy import select

from models.database import get_admin_session
from models.llm_model import LlmModel
from models.llm_usage import LlmUsage
from services.credits import deduct_with_grace

logger = logging.getLogger(__name__)

CREDITS_PER_DOLLAR: Final[int] = 1000
MIN_CREDITS_PER_CALL: Final[int] = 1
DEFAULT_INPUT_COST_PER_M: Final[Decimal] = Decimal("2.500000")
DEFAULT_OUTPUT_COST_PER_M: Final[Decimal] = Decimal("10.000000")
_CACHE_TTL_SECONDS: Final[float] = 300.0

_price_cache: dict[str, tuple[Decimal, Decimal]] = {}
_cache_loaded_at: float = 0.0


def _invalidate_price_cache() -> None:
    global _cache_loaded_at
    _price_cache.clear()
    _cache_loaded_at = 0.0


async def _load_price_cache() -> None:
    global _cache_loaded_at
    now: float = time.monotonic()
    if _price_cache and (now - _cache_loaded_at) < _CACHE_TTL_SECONDS:
        return
    async with get_admin_session() as session:
        result = await session.execute(
            select(
                LlmModel.model_name,
                LlmModel.input_cost_per_m,
                LlmModel.output_cost_per_m,
            )
        )
        rows = result.all()
    _price_cache.clear()
    for model_name, input_cost, output_cost in rows:
        _price_cache[str(model_name)] = (Decimal(input_cost), Decimal(output_cost))
    _cache_loaded_at = now


async def get_model_price(model_name: str) -> tuple[Decimal, Decimal]:
    """Return (input_cost_per_m, output_cost_per_m) in dollars."""
    await _load_price_cache()
    key: str = model_name.strip()
    cached = _price_cache.get(key)
    if cached is not None:
        return cached
    return DEFAULT_INPUT_COST_PER_M, DEFAULT_OUTPUT_COST_PER_M


def compute_credit_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    input_cost_per_m: Decimal,
    output_cost_per_m: Decimal,
) -> int:
    """Convert token counts and $/M rates to integer credits (min 1)."""
    safe_input: int = max(0, int(input_tokens))
    safe_output: int = max(0, int(output_tokens))
    dollar_cost: Decimal = (
        Decimal(safe_input) * input_cost_per_m + Decimal(safe_output) * output_cost_per_m
    ) / Decimal(1_000_000)
    credits_decimal: Decimal = dollar_cost * Decimal(CREDITS_PER_DOLLAR)
    credits: int = int(credits_decimal.to_integral_value(rounding=ROUND_CEILING))
    return max(MIN_CREDITS_PER_CALL, credits)


async def compute_credit_cost_for_model(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Look up model pricing and compute credits."""
    input_rate, output_rate = await get_model_price(model_name)
    return compute_credit_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_per_m=input_rate,
        output_cost_per_m=output_rate,
    )


async def record_llm_usage(
    *,
    organization_id: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    credits_charged: int,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """Persist granular usage for reporting."""
    async with get_admin_session() as session:
        session.add(
            LlmUsage(
                organization_id=UUID(organization_id),
                user_id=UUID(user_id) if user_id else None,
                conversation_id=UUID(conversation_id) if conversation_id else None,
                model_name=model_name,
                input_tokens=max(0, int(input_tokens)),
                output_tokens=max(0, int(output_tokens)),
                credits_charged=max(0, int(credits_charged)),
            )
        )
        await session.commit()


async def charge_llm_usage(
    *,
    organization_id: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    user_id: str | None = None,
    conversation_id: str | None = None,
    reason: str = "llm",
) -> tuple[bool, bool, int]:
    """
    Compute cost, deduct credits, and record usage.

    Returns (ok, used_grace, credits_charged).
    """
    if not organization_id:
        return True, False, 0

    credits: int = await compute_credit_cost_for_model(
        model_name, input_tokens, output_tokens
    )
    if credits <= 0:
        return True, False, 0

    ok, used_grace = await deduct_with_grace(
        organization_id,
        credits,
        reason[:64],
        reference_type="conversation" if conversation_id else None,
        reference_id=conversation_id,
        user_id=user_id,
    )
    if ok:
        await record_llm_usage(
            organization_id=organization_id,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            credits_charged=credits,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        logger.info(
            "[LLMPricing] charged org=%s model=%s in=%d out=%d credits=%d grace=%s",
            organization_id,
            model_name,
            input_tokens,
            output_tokens,
            credits,
            used_grace,
        )
    else:
        logger.info(
            "[LLMPricing] charge failed org=%s model=%s credits=%d",
            organization_id,
            model_name,
            credits,
        )
    return ok, used_grace, credits


def invalidate_model_price_cache() -> None:
    """Call after admin updates to models table."""
    _invalidate_price_cache()
