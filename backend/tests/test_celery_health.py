from __future__ import annotations

import asyncio
from typing import Any

from services import celery_health


def test_ensure_celery_workers_available_success(monkeypatch: Any) -> None:
    async def _fake_inspect() -> dict[str, Any] | None:
        return {"worker@a": {"ok": "pong"}}

    async def _fake_incident(*, title: str, details: str) -> bool:
        raise AssertionError("incident should not be called")

    monkeypatch.setattr(celery_health, "_inspect_celery_workers", _fake_inspect)
    monkeypatch.setattr(celery_health, "create_pagerduty_incident", _fake_incident)

    ok = asyncio.run(celery_health.ensure_celery_workers_available())
    assert ok is True


def test_ensure_celery_workers_available_retries_before_success(monkeypatch: Any) -> None:
    monkeypatch.setenv("CELERY_STARTUP_PING_ATTEMPTS", "3")
    monkeypatch.setenv("CELERY_STARTUP_RETRY_DELAY_SECONDS", "0")

    attempts = 0

    async def _fake_inspect() -> dict[str, Any] | None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return None
        return {"worker@a": {"ok": "pong"}}

    async def _fake_incident(*, title: str, details: str) -> bool:
        raise AssertionError("incident should not be called")

    monkeypatch.setattr(celery_health, "_inspect_celery_workers", _fake_inspect)
    monkeypatch.setattr(celery_health, "create_pagerduty_incident", _fake_incident)

    ok = asyncio.run(celery_health.ensure_celery_workers_available())
    assert ok is True
    assert attempts == 3


def test_ensure_celery_workers_available_incidents_on_no_workers(monkeypatch: Any) -> None:
    monkeypatch.setenv("CELERY_STARTUP_PING_ATTEMPTS", "3")
    monkeypatch.setenv("CELERY_STARTUP_RETRY_DELAY_SECONDS", "0")

    attempts = 0

    async def _fake_inspect() -> dict[str, Any] | None:
        nonlocal attempts
        attempts += 1
        return None

    incident_titles: list[str] = []

    async def _fake_incident(*, title: str, details: str) -> bool:
        incident_titles.append(title)
        return True

    monkeypatch.setattr(celery_health, "_inspect_celery_workers", _fake_inspect)
    monkeypatch.setattr(celery_health, "create_pagerduty_incident", _fake_incident)

    ok = asyncio.run(celery_health.ensure_celery_workers_available())
    assert ok is False
    assert attempts == 3
    assert incident_titles == ["Celery workers unavailable at startup"]


def test_ensure_celery_workers_available_incidents_on_check_error(monkeypatch: Any) -> None:
    monkeypatch.setenv("CELERY_STARTUP_PING_ATTEMPTS", "2")
    monkeypatch.setenv("CELERY_STARTUP_RETRY_DELAY_SECONDS", "0")

    attempts = 0

    async def _fake_inspect() -> dict[str, Any] | None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("broker unreachable")

    incident_titles: list[str] = []

    async def _fake_incident(*, title: str, details: str) -> bool:
        incident_titles.append(title)
        return True

    monkeypatch.setattr(celery_health, "_inspect_celery_workers", _fake_inspect)
    monkeypatch.setattr(celery_health, "create_pagerduty_incident", _fake_incident)

    ok = asyncio.run(celery_health.ensure_celery_workers_available())
    assert ok is False
    assert attempts == 2
    assert incident_titles == ["Celery startup check failed"]
