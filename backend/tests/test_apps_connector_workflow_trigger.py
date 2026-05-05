from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from connectors.apps import AppsConnector, _decode_apps_auth_envelope


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, app_obj, workflow_obj) -> None:
        self._responses = [app_obj, workflow_obj]

    async def execute(self, _query):
        return _ScalarResult(self._responses.pop(0))


class _FakeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


@pytest.mark.asyncio
async def test_apps_connector_trigger_workflow_uses_envelope_user_not_connector_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    app_id = "00000000-0000-0000-0000-000000000003"
    workflow_id = "00000000-0000-0000-0000-000000000004"

    app_obj = SimpleNamespace(id=UUID(app_id), organization_id=UUID(org_id))
    workflow_obj = SimpleNamespace(id=UUID(workflow_id), organization_id=UUID(org_id), archived_at=None, is_enabled=True)

    session_kwargs: dict[str, str] = {}

    @asynccontextmanager
    async def _fake_session(**_kwargs):
        session_kwargs.update(_kwargs)
        yield _FakeSession(app_obj, workflow_obj)

    async def _no_pause():
        return None

    captured: dict[str, str | None] = {}

    class _FakeExecuteWorkflow:
        @staticmethod
        def delay(**kwargs):
            captured.update(kwargs)
            return _FakeTask("task-xyz")

    monkeypatch.setattr("connectors.apps.get_session", _fake_session)
    monkeypatch.setattr("connectors.apps.get_workflow_execution_pause_until", _no_pause)
    monkeypatch.setitem(__import__("sys").modules, "workers.tasks.workflows", SimpleNamespace(execute_workflow=_FakeExecuteWorkflow))
    monkeypatch.setattr("connectors.apps._decode_apps_auth_envelope", lambda _env, expected_org: ("00000000-0000-0000-0000-000000000005", None))

    connector = AppsConnector(organization_id=org_id, user_id=user_id)
    result = await connector.write(
        "trigger_workflow",
        {
            "app_id": app_id,
            "workflow_id": workflow_id,
            "_auth_envelope": {"token": "", "sig": ""},
            "trigger_data": {"from": "test"},
            "request_id": "req-123",
        },
    )

    assert result["status"] == "queued"
    assert result["task_id"] == "task-xyz"
    assert result["triggered_by_user_id"] == "00000000-0000-0000-0000-000000000005"
    assert captured["triggered_by"] == "app"
    assert captured["triggered_by_user_id"] == "00000000-0000-0000-0000-000000000005"
    assert captured["triggered_by_user_id"] != user_id
    assert session_kwargs["user_id"] == "00000000-0000-0000-0000-000000000005"
    assert result["request_id"] == "req-123"


@pytest.mark.asyncio
async def test_apps_connector_trigger_workflow_requires_auth_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = "00000000-0000-0000-0000-000000000001"
    connector = AppsConnector(organization_id=org_id, user_id="00000000-0000-0000-0000-000000000002")

    result = await connector.write(
        "trigger_workflow",
        {
            "app_id": "00000000-0000-0000-0000-000000000003",
            "workflow_id": "00000000-0000-0000-0000-000000000004",
        },
    )

    assert result == {"error": "Missing or invalid authenticated user context for trigger_workflow"}


def test_decode_apps_auth_envelope_rejects_missing() -> None:
    user_id, delegated = _decode_apps_auth_envelope(None, expected_org="00000000-0000-0000-0000-000000000001")
    assert user_id is None
    assert delegated == "Missing auth envelope"
