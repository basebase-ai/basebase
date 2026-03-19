import importlib
import sys
import types
from uuid import uuid4

import pytest


@pytest.fixture
def tools_module():
    fake_websockets = types.ModuleType("api.websockets")
    fake_websockets.broadcast_sync_progress = lambda *args, **kwargs: None
    sys.modules.setdefault("api.websockets", fake_websockets)
    return importlib.import_module("agents.tools")


@pytest.fixture
def workflows_module():
    return importlib.import_module("workers.tasks.workflows")


class _AllowedResult:
    allowed = True
    deny_reason = None
    transformed_query = None


class _FakeExecuteResult:
    rowcount = 1


class _FakeSession:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        self.queries.append(str(stmt))
        return _FakeExecuteResult()

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_run_sql_write_injects_slack_delivery_defaults_for_workflows(monkeypatch, tools_module):
    fake_session = _FakeSession()

    async def _fake_check_sql(*args, **kwargs):
        return _AllowedResult()

    def _fake_get_session(*args, **kwargs):
        return fake_session

    monkeypatch.setattr(tools_module, "check_sql", _fake_check_sql)
    monkeypatch.setattr(tools_module, "get_session", _fake_get_session)

    organization_id = str(uuid4())
    user_id = str(uuid4())
    query = (
        "INSERT INTO workflows (name, prompt, trigger_type, trigger_config) "
        "VALUES ('Reminder', 'Remind me later', 'schedule', '{\"cron\":\"15 9 * * *\"}'::jsonb)"
    )

    result = await tools_module._run_sql_write(
        {"query": query},
        organization_id=organization_id,
        user_id=user_id,
        context={
            "source": "slack",
            "slack_channel_id": "C123456",
            "slack_thread_ts": "1740000000.123456",
        },
    )

    assert result["success"] is True
    assert fake_session.queries, "expected the workflow INSERT to be executed"
    final_query = fake_session.queries[-1]
    assert 'output_config' in final_query
    assert '"platform": "slack"' in final_query
    assert '"channel_id": "C123456"' in final_query
    assert '"thread_ts": "1740000000.123456"' in final_query
    assert "auto_approve_tools" in final_query
    assert '["send_slack"]' in final_query


def test_build_slack_workflow_output_config_requires_slack_channel(tools_module):
    assert tools_module._build_slack_workflow_output_config(None) is None
    assert tools_module._build_slack_workflow_output_config({"source": "web"}) is None
    assert tools_module._build_slack_workflow_output_config({"source": "slack"}) is None

    assert tools_module._build_slack_workflow_output_config(
        {
            "source": "slack",
            "slack_channel_id": "C999",
            "slack_thread_ts": "123.456",
        }
    ) == {
        "platform": "slack",
        "channel_id": "C999",
        "thread_ts": "123.456",
    }


def test_get_slack_delivery_context_normalizes_supported_shapes(workflows_module):
    assert workflows_module._get_slack_delivery_context(None) is None
    assert workflows_module._get_slack_delivery_context({"platform": "email", "channel_id": "C1"}) is None

    assert workflows_module._get_slack_delivery_context(
        {"platform": "slack", "channel_id": "C1", "thread_ts": "100.2"}
    ) == {
        "channel_id": "C1",
        "thread_ts": "100.2",
    }

    assert workflows_module._get_slack_delivery_context(
        {"provider": "slack", "channel": "C2", "thread_id": "200.3"}
    ) == {
        "channel_id": "C2",
        "thread_ts": "200.3",
    }
