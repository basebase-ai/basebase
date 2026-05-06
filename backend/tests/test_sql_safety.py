from __future__ import annotations

from access_control import RightsResult
from services import sql_safety

import pytest


@pytest.mark.asyncio
async def test_prepare_safe_sql_query_rejects_disallowed_tables() -> None:
    safe_query, error = await sql_safety.prepare_safe_sql_query(
        query="SELECT * FROM pending_operations",
        organization_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )

    assert safe_query is None
    assert error == "Access to tables not allowed: {'pending_operations'}"


@pytest.mark.asyncio
async def test_prepare_safe_sql_query_applies_rights_transform(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_check_sql(context, query, params):
        assert context.organization_id == "org-1"
        assert context.user_id == "user-1"
        assert query == "SELECT * FROM contacts"
        assert params == {"limit": 10}
        return RightsResult(
            allowed=True,
            transformed_query="SELECT * FROM contacts LIMIT :limit",
            transformed_params={"limit": 5},
        )

    monkeypatch.setattr(sql_safety, "check_sql", _fake_check_sql)

    safe_query, error = await sql_safety.prepare_safe_sql_query(
        query="SELECT * FROM contacts",
        organization_id="org-1",
        user_id="user-1",
        params={"limit": 10},
    )

    assert error is None
    assert safe_query is not None
    assert safe_query.query == "SELECT * FROM contacts LIMIT :limit"
    assert safe_query.params == {"limit": 5}
    assert safe_query.tables == {"contacts"}
