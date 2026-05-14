"""Tests for Airtop connector (per-site integration row)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.airtop import AirtopConnector, PROFILE_STATUS_SAVED
from services.airtop_session_cache import AirtopBrowserReuseRecord


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
    assert names == {
        "run_task",
        "extract_structured",
        "re_authenticate",
        "open_browser",
        "run_in_session",
        "close_browser",
    }


def test_resolve_airtop_api_key_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import resolve_airtop_api_key, settings

    monkeypatch.setattr(settings, "AIRTOP_KEY", "env-airtop-key-12345678")
    assert resolve_airtop_api_key({"api_key": "row-key-12345678"}) == "env-airtop-key-12345678"


def test_resolve_airtop_api_key_falls_back_to_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import resolve_airtop_api_key, settings

    monkeypatch.setattr(settings, "AIRTOP_KEY", None)
    assert resolve_airtop_api_key({"api_key": "  row-key-12345678  "}) == "row-key-12345678"


def test_resolve_airtop_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import resolve_airtop_api_key, settings

    monkeypatch.setattr(settings, "AIRTOP_KEY", "")
    with pytest.raises(ValueError, match="not configured"):
        resolve_airtop_api_key({})


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
async def test_run_task_loads_integration_before_saved_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """execute_action must load DB row before reading profile_status (was empty {} if _integration unset)."""
    from config import settings

    monkeypatch.setattr(settings, "AIRTOP_KEY", None)
    int_id = "00000000-0000-0000-0000-000000000099"
    c = AirtopConnector(
        "00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        integration_id=int_id,
    )
    assert c._integration is None
    mock_int = MagicMock()
    mock_int.extra_data = {
        "api_key": "secret",
        "profile_status": PROFILE_STATUS_SAVED,
        "profile_name": "prof1",
        "target_url": "https://example.com/",
    }

    async def _fake_load() -> None:
        c._integration = mock_int

    with patch.object(AirtopConnector, "_load_integration", side_effect=_fake_load), patch(
        "connectors.airtop.run_page_query", new_callable=AsyncMock
    ) as mock_rq:
        mock_rq.return_value = {"model_response": "ok", "meta": None}
        out = await c.execute_action(
            "run_task",
            {"url": "https://a.com/", "instructions": "go"},
        )
    assert out.get("status") == "completed"
    mock_rq.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_browser_creates_session_and_saves_handle() -> None:
    c = _connector()
    with (
        patch("connectors.airtop.get_active_handle", new_callable=AsyncMock) as mock_ah,
        patch("connectors.airtop.delete_record_and_active", new_callable=AsyncMock),
        patch(
            "connectors.airtop.create_session_window_live_view",
            new_callable=AsyncMock,
        ) as mock_create,
        patch("connectors.airtop.new_reuse_handle", return_value="reuse-handle-1"),
        patch("connectors.airtop.save_record", new_callable=AsyncMock) as mock_save,
    ):
        mock_ah.return_value = None
        mock_create.return_value = ("sess-1", "win-1", "https://live.example/view")
        out = await c.execute_action("open_browser", {})
    assert out.get("status") == "opened"
    assert out.get("session_handle") == "reuse-handle-1"
    assert out.get("live_view_url") == "https://live.example/view"
    mock_create.assert_awaited_once()
    mock_save.assert_awaited_once()
    saved_handle: str = mock_save.await_args.args[0]
    saved_rec: AirtopBrowserReuseRecord = mock_save.await_args.args[1]
    assert saved_handle == "reuse-handle-1"
    assert saved_rec.session_id == "sess-1" and saved_rec.window_id == "win-1"


@pytest.mark.asyncio
async def test_run_in_session_calls_page_query_on_window() -> None:
    c = _connector()
    rec = AirtopBrowserReuseRecord(
        organization_id="00000000-0000-0000-0000-000000000001",
        owner_user_id="00000000-0000-0000-0000-000000000002",
        integration_id="00000000-0000-0000-0000-000000000099",
        session_id="sess-x",
        window_id="win-x",
    )
    with (
        patch("connectors.airtop.get_record", new_callable=AsyncMock) as mock_gr,
        patch("connectors.airtop.page_query_on_window", new_callable=AsyncMock) as mock_pq,
    ):
        mock_gr.return_value = rec
        mock_pq.return_value = {"model_response": "done", "meta": None}
        out = await c.execute_action(
            "run_in_session",
            {"session_handle": "h", "instructions": "click ok"},
        )
    assert out.get("status") == "completed"
    assert out.get("model_response") == "done"
    mock_pq.assert_awaited_once()
    pq_kw: dict[str, Any] = mock_pq.await_args.kwargs
    assert pq_kw["session_id"] == "sess-x" and pq_kw["window_id"] == "win-x"


@pytest.mark.asyncio
async def test_close_browser_terminates_and_cleans_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "AIRTOP_KEY", None)
    c = _connector()
    rec = AirtopBrowserReuseRecord(
        organization_id="00000000-0000-0000-0000-000000000001",
        owner_user_id="00000000-0000-0000-0000-000000000002",
        integration_id="00000000-0000-0000-0000-000000000099",
        session_id="sess-z",
        window_id="win-z",
    )
    with (
        patch("connectors.airtop.get_record", new_callable=AsyncMock) as mock_gr,
        patch("connectors.airtop.terminate_session", new_callable=AsyncMock) as mock_term,
        patch("connectors.airtop.delete_record_and_active", new_callable=AsyncMock) as mock_del,
    ):
        mock_gr.return_value = rec
        out = await c.execute_action("close_browser", {"session_handle": "hz"})
    assert out.get("status") == "closed"
    mock_term.assert_awaited_once_with("secret", "sess-z")
    mock_del.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_action_integration_single_row() -> None:
    from agents.tools import _resolve_connector_action_integration_id

    row = MagicMock()
    row.id = "00000000-0000-0000-0000-0000000000aa"
    row.account_label = None
    row.account_identifier = None

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
