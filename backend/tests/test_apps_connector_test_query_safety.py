from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from access_control import RightsResult
from connectors.apps import AppsConnector


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeRow:
    def __init__(self, mapping):
        self._mapping = mapping


class _FakeSession:
    def __init__(self, app):
        self._app = app
        self.executed_sql = []

    async def execute(self, query, params=None):
        query_text = str(query)
        self.executed_sql.append((query_text, params))
        if len(self.executed_sql) == 1:
            return _ScalarResult(self._app)
        return _RowsResult([_FakeRow({"name": "Ada"})])


@pytest.mark.asyncio
async def test_apps_test_query_rejects_disallowed_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = "00000000-0000-0000-0000-000000000001"
    app_id = "00000000-0000-0000-0000-000000000002"
    app = SimpleNamespace(
        id=UUID(app_id),
        organization_id=UUID(org_id),
        queries={"unsafe": {"sql": "SELECT * FROM pending_operations", "params": {}}},
    )
    fake_session = _FakeSession(app)

    @asynccontextmanager
    async def _fake_get_session(**_kwargs):
        yield fake_session

    monkeypatch.setattr("connectors.apps.get_session", _fake_get_session)

    connector = AppsConnector(organization_id=org_id, user_id="00000000-0000-0000-0000-000000000003")
    result = await connector.write("test_query", {"app_id": app_id, "query_name": "unsafe"})

    assert result == {"error": "Access to tables not allowed: {'pending_operations'}"}
    assert len(fake_session.executed_sql) == 1


@pytest.mark.asyncio
async def test_apps_test_query_applies_rights_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000003"
    app_id = "00000000-0000-0000-0000-000000000002"
    app = SimpleNamespace(
        id=UUID(app_id),
        organization_id=UUID(org_id),
        queries={"contacts": {"sql": "SELECT name FROM contacts WHERE status = :status", "params": {}}},
    )
    fake_session = _FakeSession(app)

    @asynccontextmanager
    async def _fake_get_session(**_kwargs):
        yield fake_session

    async def _deny_sql(context, query, params):
        assert context.organization_id == org_id
        assert context.user_id == user_id
        assert query == "SELECT name FROM contacts WHERE status = :status"
        assert params == {"org_id": org_id, "status": "active"}
        return RightsResult(allowed=False, deny_reason="No contact access")

    monkeypatch.setattr("connectors.apps.get_session", _fake_get_session)
    monkeypatch.setattr("services.sql_safety.check_sql", _deny_sql)

    connector = AppsConnector(organization_id=org_id, user_id=user_id)
    result = await connector.write(
        "test_query",
        {"app_id": app_id, "query_name": "contacts", "params": {"status": "active"}},
    )

    assert result == {"error": "No contact access"}
    assert len(fake_session.executed_sql) == 1
