import logging
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from api.auth_middleware import AuthContext
from api.routes import topic_graph as topic_graph_routes


@pytest.mark.asyncio
async def test_get_graph_snapshot_logs_view_success(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    async def _fake_get_snapshot(_org_id: str, _date: date):
        return SimpleNamespace(status="completed", graph_payload={"nodes": []}, run_metadata={})

    monkeypatch.setattr(topic_graph_routes, "get_topic_graph_snapshot", _fake_get_snapshot)
    auth = AuthContext(user_id=uuid4(), organization_id=None, email="test@example.com", role="admin", is_global_admin=True)

    caplog.set_level(logging.INFO, logger=topic_graph_routes.logger.name)
    await topic_graph_routes.get_graph_snapshot("org-1", "2026-04-10", auth)

    assert "topic_graph.stage=view_graph_request" in caplog.text
    assert "topic_graph.stage=view_graph_success" in caplog.text


@pytest.mark.asyncio
async def test_get_graph_node_evidence_logs_success(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    async def _fake_get_evidence(_org_id: str, _date: date, _node_id: str):
        return [{"snippet": "hello"}]

    monkeypatch.setattr(topic_graph_routes, "get_node_evidence", _fake_get_evidence)
    auth = AuthContext(user_id=uuid4(), organization_id=None, email="test@example.com", role="admin", is_global_admin=True)

    caplog.set_level(logging.INFO, logger=topic_graph_routes.logger.name)
    await topic_graph_routes.get_graph_node_evidence("org-1", "2026-04-10", "node-a", auth)

    assert "topic_graph.stage=view_evidence_request" in caplog.text
    assert "topic_graph.stage=view_evidence_success" in caplog.text
