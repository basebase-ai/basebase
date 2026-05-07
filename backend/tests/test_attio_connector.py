"""Tests for AttioConnector sync normalization, write dispatch, actions, and schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from connectors.attio import AttioConnector
from connectors.models import AccountRecord, ActivityRecord, ContactRecord, DealRecord
from connectors.registry import Capability, ConnectorScope


async def _noop_ensure_sync_active(_self: AttioConnector, _stage: str) -> None:
    return None


def _connector() -> AttioConnector:
    return AttioConnector(
        "00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )


def test_meta_capabilities_and_slug() -> None:
    c = _connector()
    assert c.meta.slug == "attio"
    assert c.source_system == "attio"
    assert c.meta.scope == ConnectorScope.USER
    assert Capability.SYNC in c.meta.capabilities
    assert Capability.QUERY in c.meta.capabilities
    assert Capability.WRITE in c.meta.capabilities
    assert Capability.ACTION in c.meta.capabilities
    assert "record_permission:read-write" in c.meta.oauth_scopes
    assert c.meta.nango_integration_id == "attio"


@pytest.mark.asyncio
async def test_sync_contacts_normalizes_attio_values(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "POST"
        assert endpoint == "/v2/objects/people/records/query"
        return {
            "data": [
                {
                    "id": {
                        "workspace_id": "14beef7a-99f7-4534-a87e-70b564330a4c",
                        "object_id": "97052eb9-e65e-443f-a297-f2d9a4a7f795",
                        "record_id": "bf071e1f-6035-429d-b874-d83ea64ea13b",
                    },
                    "values": {
                        "name": [{"full_name": "Ada Lovelace", "first_name": "Ada", "last_name": "Lovelace"}],
                        "email_addresses": [{"email_address": "ada@example.com"}],
                        "job_title": [{"value": "Engineer"}],
                        "phone_numbers": [{"original_phone_number": "+15555550100"}],
                        "company": [{"target_object": "companies", "target_record_id": "99a03ff3-0435-47da-95cc-76b2caeb4dab"}],
                    },
                }
            ]
        }

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "ensure_sync_active", _noop_ensure_sync_active)

    rows: list[ContactRecord] = await c.sync_contacts()
    assert len(rows) == 1
    p: ContactRecord = rows[0]
    assert p.source_id == "bf071e1f-6035-429d-b874-d83ea64ea13b"
    assert p.email == "ada@example.com"
    assert p.name == "Ada Lovelace"
    assert p.title == "Engineer"
    assert p.phone == "+15555550100"
    assert p.account_source_id == "99a03ff3-0435-47da-95cc-76b2caeb4dab"


@pytest.mark.asyncio
async def test_sync_companies_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert endpoint == "/v2/objects/companies/records/query"
        return {
            "data": [
                {
                    "id": {"record_id": "comp-1"},
                    "values": {
                        "name": [{"value": "Acme Inc"}],
                        "domains": [{"domain": "acme.com"}],
                        "categories": [{"option": {"title": "Software"}}],
                        "employee_range": [{"option": {"title": "51-200"}}],
                    },
                }
            ]
        }

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "ensure_sync_active", _noop_ensure_sync_active)

    rows: list[AccountRecord] = await c.sync_accounts()
    assert len(rows) == 1
    a: AccountRecord = rows[0]
    assert a.source_id == "comp-1"
    assert a.name == "Acme Inc"
    assert a.domain == "acme.com"
    assert a.industry == "Software"
    assert a.employee_count == 125


@pytest.mark.asyncio
async def test_sync_deals_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert endpoint == "/v2/objects/deals/records/query"
        return {
            "data": [
                {
                    "id": {"record_id": "deal-1"},
                    "values": {
                        "name": [{"value": "Big opp"}],
                        "value": [{"currency_value": 50000, "currency_code": "USD"}],
                        "stage": [{"status": {"title": "Negotiation"}}],
                        "associated_company": [{"target_record_id": "comp-9"}],
                        "expected_close_date": [{"value": "2026-12-31"}],
                    },
                }
            ]
        }

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "ensure_sync_active", _noop_ensure_sync_active)

    rows: list[DealRecord] = await c.sync_deals()
    assert len(rows) == 1
    d: DealRecord = rows[0]
    assert d.source_id == "deal-1"
    assert d.name == "Big opp"
    assert d.amount == 50000.0
    assert d.stage == "Negotiation"
    assert d.account_source_id == "comp-9"
    assert d.close_date is not None and d.close_date.isoformat() == "2026-12-31"


@pytest.mark.asyncio
async def test_sync_activities_from_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    ts: str = "2026-01-15T12:00:00.000000000Z"

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert method == "GET"
        assert endpoint == "/v2/notes"
        return {
            "data": [
                {
                    "id": {"workspace_id": "w", "note_id": "note-uuid-1"},
                    "parent_object": "people",
                    "parent_record_id": "person-1",
                    "title": "Hello",
                    "content_plaintext": "Body text",
                    "created_at": ts,
                }
            ]
        }

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "ensure_sync_active", _noop_ensure_sync_active)

    rows: list[ActivityRecord] = await c.sync_activities()
    assert len(rows) == 1
    act: ActivityRecord = rows[0]
    assert act.source_id == "note-uuid-1"
    assert act.type == "note"
    assert act.subject == "Hello"
    assert act.description == "Body text"
    assert act.contact_source_id == "person-1"
    assert act.activity_date == datetime(2026, 1, 15, 12, 0, 0)


@pytest.mark.asyncio
async def test_write_create_person_uses_assert_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    recorded: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recorded.append((method, endpoint, params, json_body))
        return {"data": {"id": {"record_id": "new-id"}}}

    async def fake_token(self: AttioConnector) -> tuple[str, str]:
        return ("tok", "")

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "get_oauth_token", fake_token)

    await c.write(
        "create_person",
        {"email": "jane@acme.com", "first_name": "Jane", "last_name": "Doe"},
    )
    assert len(recorded) == 1
    method, endpoint, params, body = recorded[0]
    assert method == "PUT"
    assert endpoint == "/v2/objects/people/records"
    assert params == {"matching_attribute": "email_addresses"}
    assert body is not None
    vals: dict[str, Any] = body["data"]["values"]
    assert vals["email_addresses"] == ["jane@acme.com"]
    assert vals["name"][0]["first_name"] == "Jane"


@pytest.mark.asyncio
async def test_write_create_deal_sends_stage_and_owner_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    recorded: list[dict[str, Any] | None] = []

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recorded.append(json_body)
        return {"data": {"id": {"record_id": "deal-new"}}}

    async def fake_token(self: AttioConnector) -> tuple[str, str]:
        return ("tok", "")

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "get_oauth_token", fake_token)

    await c.write(
        "create_deal",
        {
            "name": "GAIA",
            "stage": "Lead",
            "owner_email": "founder@example.com",
            "company_id": "146ddd6c-c2c4-4246-b10f-10c942b53671",
        },
    )
    assert len(recorded) == 1
    body = recorded[0]
    assert body is not None
    vals: dict[str, Any] = body["data"]["values"]
    assert vals["name"] == [{"value": "GAIA"}]
    assert vals["stage"] == [{"status": "Lead"}]
    assert vals["owner"] == [{"workspace_member_email_address": "founder@example.com"}]
    assert vals["associated_company"] == [
        {
            "target_object": "companies",
            "target_record_id": "146ddd6c-c2c4-4246-b10f-10c942b53671",
        },
    ]


@pytest.mark.asyncio
async def test_execute_action_search_records(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    recorded: list[tuple[str, str, dict[str, Any] | None]] = []

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recorded.append((method, endpoint, json_body))
        return {"data": []}

    async def fake_token(self: AttioConnector) -> tuple[str, str]:
        return ("tok", "")

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "get_oauth_token", fake_token)

    await c.execute_action(
        "search_records",
        {"object": "people", "filter": {"name": "Ada"}, "limit": 10, "offset": 0},
    )
    assert recorded == [
        (
            "POST",
            "/v2/objects/people/records/query",
            {"limit": 10, "offset": 0, "filter": {"name": "Ada"}},
        ),
    ]


@pytest.mark.asyncio
async def test_execute_action_list_statuses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    recorded: list[tuple[str, str]] = []

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        recorded.append((method, endpoint))
        return {"data": [{"title": "Lead", "id": {"status_id": "s1"}}]}

    async def fake_token(self: AttioConnector) -> tuple[str, str]:
        return ("tok", "")

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "get_oauth_token", fake_token)

    out: dict[str, Any] = await c.execute_action("list_statuses", {})
    assert recorded == [("GET", "/v2/objects/deals/attributes/stage/statuses")]
    assert out["data"][0]["title"] == "Lead"


@pytest.mark.asyncio
async def test_get_schema_builds_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    calls: list[tuple[str, str]] = []

    async def fake_make_request(
        self: AttioConnector,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calls.append((method, endpoint))
        if endpoint == "/v2/objects":
            return {
                "data": [
                    {"api_slug": "people", "singular_noun": "Person", "plural_noun": "People"},
                ]
            }
        if endpoint == "/v2/objects/people/attributes":
            return {
                "data": [
                    {"api_slug": "email_addresses", "title": "Email addresses"},
                    {"api_slug": "name", "title": "Name"},
                ]
            }
        raise AssertionError(f"unexpected {endpoint}")

    async def fake_token(self: AttioConnector) -> tuple[str, str]:
        return ("tok", "")

    monkeypatch.setattr(AttioConnector, "_make_request", fake_make_request)
    monkeypatch.setattr(AttioConnector, "get_oauth_token", fake_token)

    schema: list[dict[str, Any]] = await c.get_schema()
    assert len(schema) == 1
    assert schema[0]["entity"] == "people"
    assert "email_addresses" in schema[0]["fields"]
    assert "name" in schema[0]["fields"]
    assert any(ep == ("GET", "/v2/objects") for ep in calls)
    assert any(ep == ("GET", "/v2/objects/people/attributes") for ep in calls)


@pytest.mark.asyncio
async def test_execute_action_unknown_raises() -> None:
    c = _connector()
    with pytest.raises(ValueError, match="Unknown Attio action"):
        await c.execute_action("not_real", {})
