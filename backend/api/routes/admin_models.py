"""
Admin CRUD for the models registry (pricing and capabilities).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.auth_middleware import AuthContext, require_global_admin
from models.database import get_admin_session
from models.llm_model import LlmModel
from services.llm_pricing import invalidate_model_price_cache

router = APIRouter()
logger = logging.getLogger(__name__)


class ModelResponse(BaseModel):
    id: str
    model_name: str
    provider: str
    input_cost_per_m: float
    output_cost_per_m: float
    is_enabled: bool
    supports_images: bool
    supports_tools: bool
    max_context_tokens: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ModelUpdateRequest(BaseModel):
    provider: Optional[str] = None
    input_cost_per_m: Optional[float] = Field(None, ge=0)
    output_cost_per_m: Optional[float] = Field(None, ge=0)
    is_enabled: Optional[bool] = None
    supports_images: Optional[bool] = None
    supports_tools: Optional[bool] = None
    max_context_tokens: Optional[int] = Field(None, ge=1)


def _to_response(row: LlmModel) -> ModelResponse:
    return ModelResponse(
        id=str(row.id),
        model_name=row.model_name,
        provider=row.provider,
        input_cost_per_m=float(row.input_cost_per_m),
        output_cost_per_m=float(row.output_cost_per_m),
        is_enabled=row.is_enabled,
        supports_images=row.supports_images,
        supports_tools=row.supports_tools,
        max_context_tokens=row.max_context_tokens,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[ModelResponse])
async def list_models(
    auth: AuthContext = Depends(require_global_admin),
) -> list[ModelResponse]:
    """List all models in the registry."""
    _ = auth
    async with get_admin_session() as session:
        result = await session.execute(
            select(LlmModel).order_by(LlmModel.provider, LlmModel.model_name)
        )
        rows: list[LlmModel] = list(result.scalars().all())
    return [_to_response(row) for row in rows]


@router.put("/{model_name}", response_model=ModelResponse)
async def update_model(
    model_name: str,
    body: ModelUpdateRequest,
    auth: AuthContext = Depends(require_global_admin),
) -> ModelResponse:
    """Update pricing or capability flags for a model."""
    _ = auth
    async with get_admin_session() as session:
        result = await session.execute(
            select(LlmModel).where(LlmModel.model_name == model_name)
        )
        row: LlmModel | None = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Model not found")

        if body.provider is not None:
            row.provider = body.provider.strip()
        if body.input_cost_per_m is not None:
            row.input_cost_per_m = Decimal(str(body.input_cost_per_m))
        if body.output_cost_per_m is not None:
            row.output_cost_per_m = Decimal(str(body.output_cost_per_m))
        if body.is_enabled is not None:
            row.is_enabled = body.is_enabled
        if body.supports_images is not None:
            row.supports_images = body.supports_images
        if body.supports_tools is not None:
            row.supports_tools = body.supports_tools
        if body.max_context_tokens is not None:
            row.max_context_tokens = body.max_context_tokens
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)

    invalidate_model_price_cache()
    logger.info("[AdminModels] updated model=%s", model_name)
    return _to_response(row)
