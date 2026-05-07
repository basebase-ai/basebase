"""Execute named SELECT queries from an App's server-side spec (shared by API routes)."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.app import App
from services.sql_safety import prepare_safe_sql_query, validate_sql_query

logger = logging.getLogger(__name__)


class AppQueryResponse(BaseModel):
    data: list[dict[str, Any]]
    columns: list[str]


def validate_sql_is_select(sql: str) -> None:
    """Raise if the SQL is not a safe read query."""
    is_valid, error = validate_sql_query(sql)
    if not is_valid:
        raise ValueError(error or "Only SELECT queries are allowed")


def json_serial(obj: Any) -> Any:
    """JSON serializer for types not handled by default."""
    if isinstance(obj, dict):
        return {str(k): json_serial(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_serial(item) for item in obj]
    if isinstance(obj, set):
        return [json_serial(item) for item in sorted(obj, key=str)]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, datetime):
        if obj.tzinfo is not None:
            return obj.isoformat()
        return f"{obj.isoformat()}Z"
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


async def run_named_app_query(
    *,
    app: App,
    organization_id: str,
    query_name: str,
    params: dict[str, Any],
    session: AsyncSession,
) -> AppQueryResponse:
    """Run a named query from `app.queries` with rights checks and RLS session."""
    queries: dict[str, Any] = app.queries or {}
    query_spec: dict[str, Any] | None = queries.get(query_name)

    if query_spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"Query '{query_name}' not found in app spec",
        )

    sql: str = query_spec.get("sql", "")
    try:
        validate_sql_is_select(sql)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    param_defs: dict[str, Any] = query_spec.get("params", {})
    bound_params: dict[str, Any] = {"org_id": organization_id}
    for pname, pdef in param_defs.items():
        value: Any = params.get(pname)
        if value is None and pdef.get("required", False):
            raise HTTPException(
                status_code=400,
                detail=f"Missing required parameter: {pname}",
            )
        if value is not None:
            bound_params[pname] = value

    safe_query, safety_error = await prepare_safe_sql_query(
        query=sql,
        organization_id=organization_id,
        user_id=None,
        params=bound_params,
        log_prefix="AppQueryRunner.run_named_app_query",
    )
    if safety_error is not None or safe_query is None:
        raise HTTPException(status_code=403, detail=safety_error or "Query not allowed")

    query_to_run: str = safe_query.query
    params_to_use: dict[str, Any] = safe_query.params or {}

    sql_upper: str = query_to_run.upper()
    if "LIMIT" not in sql_upper:
        query_to_run = f"{query_to_run.rstrip().rstrip(';')} LIMIT 5000"

    try:
        raw_result = await session.execute(text(query_to_run), params_to_use)
        rows = raw_result.mappings().all()
        columns: list[str] = list(raw_result.keys()) if rows else []

        data: list[dict[str, Any]] = [
            {
                k: json_serial(v)
                if not isinstance(v, (str, int, float, bool, type(None)))
                else v
                for k, v in dict(row).items()
            }
            for row in rows
        ]

        return AppQueryResponse(data=data, columns=columns)
    except Exception as exc:
        logger.error("App query execution failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Query error: {exc}") from exc
