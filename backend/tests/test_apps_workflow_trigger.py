from __future__ import annotations

import logging
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
        self.added = []

    async def execute(self, _query):
        return _ScalarResult(self._responses.pop(0))

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = UUID("00000000-0000-0000-0000-000000000005")
        self.added.append(value)

    async def commit(self):
        return None

    async def refresh(self, value):
        return None


class _FakeTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


@pytest.mark.asyncio
async def test_trigger_app_workflow_runs_as_logged_in_user(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    org_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("00000000-0000-0000-0000-000000000002")
    app_id = UUID("00000000-0000-0000-0000-000000000003")
    workflow_id = UUID("00000000-0000-0000-0000-000000000004")

    app_obj = SimpleNamespace(id=app_id, organization_id=org_id)
    workflow_obj = SimpleNamespace(id=workflow_id, organization_id=org_id, archived_at=None, is_enabled=True)

    fake_sessions: list[_FakeSession] = []

    @asynccontextmanager
    async def _fake_session(**_kwargs):
        fake_session = _FakeSession(app_obj, workflow_obj)
        fake_sessions.append(fake_session)
        yield fake_session

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
    monkeypatch.setitem(
        __import__("sys").modules,
        "workers.tasks.workflows",
        SimpleNamespace(execute_workflow=_FakeExecuteWorkflow),
    )

    auth = AuthContext(
        user_id=user_id,
        organization_id=org_id,
        email="user@example.com",
        role="member",
        is_global_admin=False,
    )

    caplog.set_level(logging.INFO, logger=apps_routes.logger.name)

    response = await apps_routes.trigger_app_workflow(
        app_id=str(app_id),
        workflow_id=str(workflow_id),
        body=apps_routes.TriggerAppWorkflowRequest(trigger_data={"source": "app"}, request_id="req-test-123"),
        auth=auth,
    )

    assert response.status == "queued"
    assert response.triggered_by_user_id == str(user_id)
    assert response.run_id == "00000000-0000-0000-0000-000000000005"
    assert response.request_id == "req-test-123"
    assert len(fake_sessions) == 1
    assert len(fake_sessions[0].added) == 1
    assert fake_sessions[0].added[0].status == "pending"
    assert fake_sessions[0].added[0].triggered_by == "app"
    assert fake_sessions[0].added[0].trigger_data == {"source": "app"}
    assert captured["triggered_by_user_id"] == str(user_id)
    assert captured["triggered_by"] == "app"
    assert captured["workflow_run_id"] == response.run_id
    assert "Received app workflow trigger request" in caplog.text
    assert "request_id=req-test-123" in caplog.text
    assert "task_id=task-123" in caplog.text
