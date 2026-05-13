"""Multi-account integration behavior (query fan-out, Gmail send account filter)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from agents import tools as tools_mod


@pytest.mark.asyncio
async def test_query_on_connector_fanout_tags_accounts(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a user has two active rows for a connector, query runs per row and tags results."""
    org: str = "00000000-0000-0000-0000-0000000000bb"
    uid: str = "00000000-0000-0000-0000-0000000000aa"
    id1: UUID = uuid4()
    id2: UUID = uuid4()
    row1 = SimpleNamespace(id=id1, account_label="Work", account_identifier="w@w.com")
    row2 = SimpleNamespace(id=id2, account_label="Home", account_identifier="h@h.com")

    class _FakeResult:
        def scalars(self) -> "_FakeResult":
            return self

        def all(self) -> list[SimpleNamespace]:
            return [row1, row2]

    class _FakeSession:
        async def execute(self, _stmt: Any) -> _FakeResult:
            return _FakeResult()

    @asynccontextmanager
    async def _fake_get_session(*_a: Any, **_kw: Any):
        yield _FakeSession()

    async def _fake_check_connector_call(*_a: Any, **_kw: Any) -> SimpleNamespace:
        return SimpleNamespace(allowed=True, deny_reason=None)

    integration_ids: list[str | None] = []

    async def _fake_get_connector_instance(
        _connector: str,
        _organization_id: str,
        _user_id: str | None,
        *,
        required_capability: str | None = None,
        integration_id: str | None = None,
        account_identifier: str | None = None,
    ) -> tuple[Any, str | None]:
        integration_ids.append(integration_id)

        class _FakeInst:
            user_id: str | None = _user_id

            async def query(self, q: str) -> dict[str, Any]:
                return {"ok": True, "integration_id": integration_id, "q": q}

        return _FakeInst(), None

    monkeypatch.setattr(tools_mod, "get_session", _fake_get_session)
    monkeypatch.setattr(tools_mod, "check_connector_call", _fake_check_connector_call)
    monkeypatch.setattr(tools_mod, "_get_connector_instance", _fake_get_connector_instance)

    out: dict[str, Any] = await tools_mod._query_on_connector(
        {"connector": "gmail", "query": "in:inbox"},
        organization_id=org,
        user_id=uid,
    )
    assert out.get("multi_account") is True
    items: list[dict[str, Any]] = out.get("items", [])
    assert len(items) == 2
    labels: set[str] = {str(i.get("account")) for i in items}
    assert labels == {"Work", "Home"}
    seen_ids: set[str] = {str(i.get("integration_id")) for i in items if i.get("integration_id")}
    assert seen_ids == {str(id1), str(id2)}
    assert str(id1) in integration_ids and str(id2) in integration_ids


@pytest.mark.asyncio
async def test_gmail_send_email_restores_account_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    from connectors.gmail import GmailConnector

    c = GmailConnector(
        organization_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )
    c._account_identifier_filter = "keep@example.com"

    monkeypatch.setattr(c, "get_oauth_token", AsyncMock(return_value=("tok", "")))
    monkeypatch.setattr(c, "_get_headers", AsyncMock(return_value={"Authorization": "Bearer tok"}))

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"id": "m1", "threadId": "t1", "labelIds": []}

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def post(self, *_a: Any, **_kw: Any) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setattr("connectors.gmail.httpx.AsyncClient", _FakeClient)

    await c.send_email(to="t@t.com", subject="s", body="body", account="other@o.com")
    assert c._account_identifier_filter == "keep@example.com"
