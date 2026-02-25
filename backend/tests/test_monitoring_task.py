from __future__ import annotations

from typing import Any

from config import EXPECTED_ENV_VARS, settings
from workers.tasks import monitoring


class _FakeResponse:
    def __init__(self, status_code: int = 201, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:
        _FakeAsyncClient.last_call = {
            "url": url,
            "json": json,
            "headers": headers,
        }
        return _FakeResponse()


def test_expected_env_vars_include_pagerduty() -> None:
    assert "PAGERDUTY_FROM_EMAIL" in EXPECTED_ENV_VARS
    assert "PagerDuty_Key" in EXPECTED_ENV_VARS
    assert "PAGERDUTY_SERVICE_ID" in EXPECTED_ENV_VARS


def test_pagerduty_incident_request_shape(monkeypatch: Any) -> None:
    monkeypatch.setattr(monitoring.httpx, "AsyncClient", _FakeAsyncClient)

    import asyncio

    asyncio.run(
        monitoring._create_pagerduty_incident(
            from_email="alerts@revtops.com",
            api_key="pd_test_key",
            service_id="svc_123",
            check_result=monitoring.CheckResult(
                name="Redis",
                healthy=False,
                details="timeout",
            ),
        )
    )

    last_call = _FakeAsyncClient.last_call
    assert last_call["url"] == "https://api.pagerduty.com/incidents"
    assert last_call["headers"]["From"] == "alerts@revtops.com"
    assert last_call["headers"]["Authorization"] == "Token token=pd_test_key"
    assert last_call["json"]["incident"]["service"]["id"] == "svc_123"
    assert last_call["json"]["incident"]["title"] == "Redis is down"


def test_pagerduty_alias_var_is_loaded(monkeypatch: Any) -> None:
    monkeypatch.setenv("PagerDuty_Key", "alias_value")
    fresh_settings = settings.__class__()
    assert fresh_settings.PAGERDUTY_KEY == "alias_value"
