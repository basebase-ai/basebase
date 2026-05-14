"""
Shared Airtop (Async SDK) helpers for the Airtop connector and HTTP routes.

All functions assume a valid API key; callers validate org/user and persist Integration rows.
"""

from __future__ import annotations

import logging
from typing import Any

from airtop import AsyncAirtop
from airtop.wrapper.sessions_client import SessionConfig
from airtop.wrapper.windows_client import PageQueryConfig, convert_page_query_output_schema_to_str

logger = logging.getLogger(__name__)


def airtop_client(api_key: str, *, timeout_seconds: float = 300.0) -> AsyncAirtop:
    return AsyncAirtop(api_key=api_key.strip(), timeout=timeout_seconds)


async def create_session_window_live_view(
    api_key: str,
    *,
    initial_url: str,
    profile_name: str | None,
    timeout_minutes: int,
    client_timeout: float = 180.0,
) -> tuple[str, str, str]:
    """Create session, open window at ``initial_url``, return (session_id, window_id, live_view_url)."""
    client: AsyncAirtop = airtop_client(api_key, timeout_seconds=client_timeout)
    cfg_kwargs: dict[str, Any] = {
        "timeout_minutes": max(5, min(timeout_minutes, 120)),
        "skip_wait_session_ready": True,
    }
    if profile_name and profile_name.strip():
        cfg = SessionConfig(profile_name=profile_name.strip(), **cfg_kwargs)
    else:
        cfg = SessionConfig(**cfg_kwargs)

    session_res = await client.sessions.create(configuration=cfg)
    session_id: str = session_res.data.id

    win_res = await client.windows.create(session_id=session_id, url=initial_url.strip())
    window_id: str = win_res.data.window_id

    info = await client.windows.get_window_info(
        session_id, window_id, include_navigation_bar=True
    )
    live_url: str = str(info.data.live_view_url).strip()
    if not live_url:
        raise ValueError("Airtop did not return a live_view_url")
    return session_id, window_id, live_url


async def save_profile_and_terminate(api_key: str, session_id: str, profile_name: str) -> None:
    client: AsyncAirtop = airtop_client(api_key, timeout_seconds=120.0)
    await client.sessions.save_profile_on_termination(session_id, profile_name.strip())
    await client.sessions.terminate(session_id)


async def terminate_session(api_key: str, session_id: str) -> None:
    client: AsyncAirtop = airtop_client(api_key, timeout_seconds=60.0)
    await client.sessions.terminate(session_id)


async def run_page_query(
    api_key: str,
    *,
    profile_name: str,
    url: str,
    prompt: str,
    output_schema: str | dict[str, Any] | None,
    time_threshold_seconds: int | None,
    request_timeout_seconds: float,
    session_timeout_minutes: int,
) -> dict[str, Any]:
    """Load ``profile_name``, open ``url``, run page_query with ``prompt``, always terminate session."""
    client: AsyncAirtop = airtop_client(api_key, timeout_seconds=max(request_timeout_seconds, 120.0))
    cfg = SessionConfig(
        profile_name=profile_name.strip(),
        timeout_minutes=max(5, min(session_timeout_minutes, 120)),
        skip_wait_session_ready=True,
    )
    session_res = await client.sessions.create(configuration=cfg)
    session_id: str = session_res.data.id
    try:
        win_res = await client.windows.create(session_id=session_id, url=url.strip())
        window_id: str = win_res.data.window_id

        pq_cfg: PageQueryConfig | None = None
        if output_schema is not None:
            if isinstance(output_schema, str) and output_schema.strip():
                pq_cfg = PageQueryConfig(output_schema=output_schema.strip())
            elif isinstance(output_schema, dict) and output_schema:
                pq_cfg = PageQueryConfig(output_schema=output_schema)
            if pq_cfg is not None:
                pq_cfg = convert_page_query_output_schema_to_str(pq_cfg)  # type: ignore[assignment]

        pq_kwargs: dict[str, Any] = {"prompt": prompt.strip()}
        if pq_cfg is not None:
            pq_kwargs["configuration"] = pq_cfg
        if time_threshold_seconds is not None:
            pq_kwargs["time_threshold_seconds"] = int(time_threshold_seconds)

        result = await client.windows.page_query(session_id, window_id, **pq_kwargs)
        meta_dump: dict[str, Any] | None = None
        if result.meta is not None and hasattr(result.meta, "model_dump"):
            meta_dump = result.meta.model_dump()
        out: dict[str, Any] = {
            "model_response": result.data.model_response if result.data else None,
            "meta": meta_dump,
        }
        return out
    finally:
        try:
            await client.sessions.terminate(session_id)
        except Exception as exc:
            logger.warning("Airtop terminate after page_query failed session=%s: %s", session_id, exc)
