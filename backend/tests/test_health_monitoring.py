import asyncio

from workers.tasks import health_monitor


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class DummyAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_normalized_url_uses_base_url() -> None:
    url = health_monitor._normalized_url("https://example.com/", "/health")
    assert url == "https://example.com/health"


def test_dependency_monitor_creates_and_suppresses_duplicate_incidents(monkeypatch) -> None:
    fake_redis = FakeRedis()
    created: list[str] = []

    async def fake_check_http(client, url: str, label: str):
        if "nango" in label.lower():
            return False, f"{label} unreachable"
        return True, f"{label} ok"

    async def fake_check_redis_health():
        return True, "Redis ok"

    async def fake_create_incident(summary: str, details: str) -> bool:
        created.append(summary)
        return True

    monkeypatch.setattr(health_monitor.redis, "from_url", lambda *args, **kwargs: fake_redis)
    monkeypatch.setattr(health_monitor.httpx, "AsyncClient", lambda *args, **kwargs: DummyAsyncClient())
    monkeypatch.setattr(health_monitor, "_check_http", fake_check_http)
    monkeypatch.setattr(health_monitor, "_check_redis_health", fake_check_redis_health)
    monkeypatch.setattr(health_monitor, "_create_pagerduty_incident", fake_create_incident)

    first = asyncio.run(health_monitor.run_dependency_health_checks())
    second = asyncio.run(health_monitor.run_dependency_health_checks())

    assert first["nango"] == "down_incident_created"
    assert second["nango"] == "down_existing_incident"
    assert len(created) == 1


def test_settings_accept_pagerduty_alias() -> None:
    config = health_monitor.settings.__class__(PagerDuty_Key="alias-key")
    assert config.PAGERDUTY_KEY == "alias-key"
