from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from api.auth_middleware import AuthContext
from api.routes import apps as apps_routes


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
async def test_trigger_app_workflow_runs_as_logged_in_user(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("00000000-0000-0000-0000-000000000002")
    app_id = UUID("00000000-0000-0000-0000-000000000003")
    workflow_id = UUID("00000000-0000-0000-0000-000000000004")

    app_obj = SimpleNamespace(id=app_id, organization_id=org_id)
    workflow_obj = SimpleNamespace(id=workflow_id, organization_id=org_id, archived_at=None, is_enabled=True)

    @asynccontextmanager
    async def _fake_session(**_kwargs):
        yield _FakeSession(app_obj, workflow_obj)

    captured: dict[str, str | None] = {}

    class _FakeExecuteWorkflow:
        @staticmethod
        def delay(**kwargs):
            captured.update(kwargs)
            return _FakeTask("task-123")

    async def _no_pause():
        return None

    monkeypatch.setattr(apps_routes, "get_session", _fake_session)
    monkeypatch.setattr(apps_routes, "get_workflow_execution_pause_until", _no_pause)
    monkeypatch.setitem(__import__("sys").modules, "workers.tasks.workflows", SimpleNamespace(execute_workflow=_FakeExecuteWorkflow))

    auth = AuthContext(
        user_id=user_id,
        organization_id=org_id,
        email="user@example.com",
        role="member",
        is_global_admin=False,
    )

    response = await apps_routes.trigger_app_workflow(
        app_id=str(app_id),
        workflow_id=str(workflow_id),
        body=apps_routes.TriggerAppWorkflowRequest(trigger_data={"source": "app"}),
        auth=auth,
    )

    assert response.status == "queued"
    assert response.triggered_by_user_id == str(user_id)
    assert captured["triggered_by_user_id"] == str(user_id)
    assert captured["triggered_by"] == "app"
