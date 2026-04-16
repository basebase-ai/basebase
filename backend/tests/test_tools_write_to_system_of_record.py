import asyncio

from agents import tools
from services import credits


def test_write_on_connector_routes_to_dispatcher(monkeypatch) -> None:
    """write_on_connector is the generic connector write tool; test that it routes and approval is applied."""
    called: dict[str, object] = {}

    async def _fake_should_skip_approval(
        tool_name: str,
        user_id: str | None,
        context: dict[str, object] | None,
    ) -> bool:
        called["skip_tool_name"] = tool_name
        called["skip_user_id"] = user_id
        called["skip_context"] = context
        return True

    async def _fake_write_on_connector(
        params: dict[str, object],
        organization_id: str,
        user_id: str | None,
        skip_approval: bool,
        context: dict[str, object] | None,
    ) -> dict[str, object]:
        called["params"] = params
        called["organization_id"] = organization_id
        called["user_id"] = user_id
        called["skip_approval"] = skip_approval
        called["context"] = context
        return {"status": "created", "message": "ok"}

    async def _fake_deduct_with_grace(*args, **kwargs):
        return True, False

    monkeypatch.setattr(tools, "_should_skip_approval", _fake_should_skip_approval)
    monkeypatch.setattr(tools, "_write_on_connector", _fake_write_on_connector)
    monkeypatch.setattr(credits, "deduct_with_grace", _fake_deduct_with_grace)

    result = asyncio.run(
        tools.execute_tool(
            tool_name="write_on_connector",
            tool_input={
                "connector": "hubspot",
                "operation": "create_contact",
                "data": {"email": "a@b.com"},
            },
            organization_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
            context={"conversation_id": "00000000-0000-0000-0000-000000000003"},
        )
    )

    assert result.get("status") == "created"
    assert called["skip_tool_name"] == "write_on_connector"
    assert called["organization_id"] == "00000000-0000-0000-0000-000000000001"
    assert called["user_id"] == "00000000-0000-0000-0000-000000000002"
    assert called["skip_approval"] is True
    assert called["context"] == {"conversation_id": "00000000-0000-0000-0000-000000000003"}


def test_write_on_connector_apps_create_passes_conversation_owner_as_override(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeConnector:
        async def write(self, operation: str, data: dict[str, object]) -> dict[str, object]:
            captured["operation"] = operation
            captured["data"] = data
            return {"status": "success"}

    async def _fake_check_connector_call(*_args, **_kwargs):
        class _Allowed:
            allowed = True
            deny_reason = None
        return _Allowed()

    async def _fake_get_connector_instance(*_args, **_kwargs):
        return _FakeConnector(), None

    async def _fake_record_intent(*_args, **_kwargs):
        return "change-1"

    async def _fake_record_outcome(*_args, **_kwargs):
        return None

    async def _fake_resolve_conversation_owner_user_id(*_args, **_kwargs):
        return "00000000-0000-0000-0000-000000000099"

    monkeypatch.setattr(tools, "check_connector_call", _fake_check_connector_call)
    monkeypatch.setattr(tools, "_get_connector_instance", _fake_get_connector_instance)
    monkeypatch.setattr(tools, "_resolve_conversation_owner_user_id", _fake_resolve_conversation_owner_user_id)
    monkeypatch.setattr("services.action_ledger.record_intent", _fake_record_intent)
    monkeypatch.setattr("services.action_ledger.record_outcome", _fake_record_outcome)

    result = asyncio.run(
        tools._write_on_connector(
            params={
                "connector": "apps",
                "operation": "create",
                "data": {"title": "Demo", "queries": {"q": {"sql": "SELECT 1", "params": {}}}, "frontend_code": "x"},
            },
            organization_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000002",
            skip_approval=True,
            context={"conversation_id": "00000000-0000-0000-0000-000000000003"},
        )
    )

    assert result["status"] == "success"
    assert captured["operation"] == "create"
    assert isinstance(captured["data"], dict)
    assert captured["data"][" app created by"] == "00000000-0000-0000-0000-000000000099"  # type: ignore[index]
