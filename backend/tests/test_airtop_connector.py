"""Tests for Airtop connector (per-site integration row)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.airtop import AirtopConnector, PROFILE_STATUS_SAVED


def _connector() -> AirtopConnector:
    c = AirtopConnector(
        "00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )
    mock_int = MagicMock()
    mock_int.id = "00000000-0000-0000-0000-000000000099"
    mock_int.extra_data = {
        "api_key": "secret",
        "profile_name": "prof1",
        "target_url": "https://example.com/start",
        "profile_status": PROFILE_STATUS_SAVED,
    }
    c._integration = mock_int
    return c


def test_airtop_meta_actions() -> None:
    names = {a.name for a in AirtopConnector.meta.actions}
    assert names == {"run_task", "extract_structured", "re_authenticate"}


@pytest.mark.asyncio
async def test_run_task_errors_when_not_saved() -> None:
    c = _connector()
    c._integration.extra_data = {"api_key": "x", "profile_status": "pending"}
    out = await c.execute_action("run_task", {"url": "https://a.com/", "instructions": "x"})
    assert "error" in out


@pytest.mark.asyncio
async def test_run_task_calls_page_query() -> None:
    c = _connector()
    with patch("connectors.airtop.run_page_query", new_callable=AsyncMock) as mock_rq:
        mock_rq.return_value = {"model_response": "ok", "meta": None}
        out = await c.execute_action(
            "run_task",
            {"url": "https://a.com/", "instructions": "click", "timeout_seconds": 120},
        )
    assert out.get("status") == "completed"
    assert out.get("model_response") == "ok"
    mock_rq.assert_awaited_once()
    kwargs: dict[str, Any] = mock_rq.await_args.kwargs
    assert kwargs["url"] == "https://a.com/"
    assert kwargs["profile_name"] == "prof1"


@pytest.mark.asyncio
async def test_resolve_action_integration_single_row() -> None:
    from agents.tools import _resolve_connector_action_integration_id

    row = MagicMock()
    row.id = "00000000-0000-0000-0000-0000000000aa"

    class _FakeResult:
        def scalars(self) -> MagicMock:
            m = MagicMock()
            m.all.return_value = [row]
            return m

    class _FakeSession:
        async def execute(self, _stmt: Any) -> _FakeResult:
            return _FakeResult()

    @asynccontextmanager
    async def _fake_get_session(**_kwargs: Any):
        yield _FakeSession()

    with patch("agents.tools.get_session", _fake_get_session):
        iid, err = await _resolve_connector_action_integration_id(
            connector="airtop",
            organization_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
            account_param="",
        )
    assert err is None
    assert iid == "00000000-0000-0000-0000-0000000000aa"
