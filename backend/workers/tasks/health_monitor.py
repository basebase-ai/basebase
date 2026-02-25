from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx
import redis.asyncio as redis

from config import get_redis_connection_kwargs, settings
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DependencyCheck:
    key: str
    label: str
    check_type: str
    target: str


DEPENDENCY_CHECKS: tuple[DependencyCheck, ...] = (
    DependencyCheck(
        key="supabase",
        label="Supabase",
        check_type="http",
        target="/auth/v1/health",
    ),
    DependencyCheck(
        key="nango",
        label="Nango",
        check_type="http",
        target="/health",
    ),
    DependencyCheck(
        key="redis",
        label="Redis",
        check_type="redis",
        target="redis://",
    ),
    DependencyCheck(
        key="www_revtops",
        label="www.revtops.com",
        check_type="http",
        target="https://www.revtops.com",
    ),
    DependencyCheck(
        key="api_revtops",
        label="api.revtops.com",
        check_type="http",
        target="https://api.revtops.com/health",
    ),
)


def _normalized_url(base_url: str | None, fallback_path: str) -> str | None:
    if not base_url:
        return None
    normalized_base = base_url.rstrip("/")
    if fallback_path.startswith("http"):
        return fallback_path
    return f"{normalized_base}{fallback_path}"


async def _check_http(client: httpx.AsyncClient, url: str, label: str) -> tuple[bool, str]:
    try:
        response = await client.get(url)
        if response.status_code >= 500:
            return False, f"{label} returned HTTP {response.status_code}"
        return True, f"{label} reachable (HTTP {response.status_code})"
    except Exception as exc:
        return False, f"{label} unreachable: {exc}"


async def _check_redis_health() -> tuple[bool, str]:
    redis_client = redis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )
    try:
        ping_result = await redis_client.ping()
        if ping_result is True:
            return True, "Redis reachable (PING ok)"
        return False, "Redis ping returned unexpected response"
    except Exception as exc:
        return False, f"Redis unreachable: {exc}"
    finally:
        await redis_client.aclose()


async def _create_pagerduty_incident(summary: str, details: str) -> bool:
    if not settings.PAGERDUTY_KEY:
        logger.warning("Skipping PagerDuty incident creation: PAGERDUTY_KEY/PagerDuty_Key not configured")
        return False
    if not settings.PAGERDUTY_FROM_EMAIL or not settings.PAGERDUTY_SERVICE_ID:
        logger.warning("Skipping PagerDuty incident creation: missing PAGERDUTY_FROM_EMAIL or PAGERDUTY_SERVICE_ID")
        return False

    payload = {
        "incident": {
            "type": "incident",
            "title": summary,
            "service": {
                "id": settings.PAGERDUTY_SERVICE_ID,
                "type": "service_reference",
            },
            "urgency": "high",
            "body": {
                "type": "incident_body",
                "details": details,
            },
        }
    }
    headers = {
        "Authorization": f"Token token={settings.PAGERDUTY_KEY}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
        "From": settings.PAGERDUTY_FROM_EMAIL,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://api.pagerduty.com/incidents",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return True


async def _redis_delete_safe(redis_state: redis.Redis, key: str) -> None:
    try:
        await redis_state.delete(key)
    except Exception as exc:
        logger.warning("Failed to clear incident state key", extra={"key": key, "error": str(exc)})


async def _redis_get_safe(redis_state: redis.Redis, key: str) -> str | None:
    try:
        return await redis_state.get(key)
    except Exception as exc:
        logger.warning("Failed to read incident state key", extra={"key": key, "error": str(exc)})
        return None


async def _redis_set_safe(redis_state: redis.Redis, key: str, value: str, ex: int) -> None:
    try:
        await redis_state.set(key, value, ex=ex)
    except Exception as exc:
        logger.warning("Failed to set incident state key", extra={"key": key, "error": str(exc)})


async def run_dependency_health_checks() -> dict[str, str]:
    results: dict[str, str] = {}
    redis_state = redis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(decode_responses=True),
    )

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for check in DEPENDENCY_CHECKS:
            if check.key == "supabase":
                url = _normalized_url(settings.SUPABASE_URL, check.target)
                if not url:
                    logger.info("Skipping Supabase health check: SUPABASE_URL not configured")
                    continue
                is_healthy, message = await _check_http(client, url, check.label)
            elif check.key == "nango":
                url = _normalized_url(settings.NANGO_HOST, check.target)
                is_healthy, message = await _check_http(client, url, check.label)
            elif check.check_type == "redis":
                is_healthy, message = await _check_redis_health()
            else:
                is_healthy, message = await _check_http(client, check.target, check.label)

            state_key = f"health_monitor:incident_open:{check.key}"
            logger.info("Dependency check result", extra={"dependency": check.key, "healthy": is_healthy, "message": message})

            if is_healthy:
                await _redis_delete_safe(redis_state, state_key)
                results[check.key] = "healthy"
                continue

            incident_open = await _redis_get_safe(redis_state, state_key)
            if incident_open:
                logger.warning("Dependency still down; incident already open", extra={"dependency": check.key})
                results[check.key] = "down_existing_incident"
                continue

            summary = f"[Revtops] {check.label} is down"
            details = f"Automated dependency monitor detected an outage for {check.label}.\n\nDetails: {message}"
            try:
                created = await _create_pagerduty_incident(summary, details)
                if created:
                    await _redis_set_safe(redis_state, state_key, "1", ex=60 * 60 * 12)
                    logger.error("Created PagerDuty incident", extra={"dependency": check.key, "details": message})
                    results[check.key] = "down_incident_created"
                else:
                    results[check.key] = "down_no_pagerduty_config"
            except Exception as exc:
                logger.exception("Failed to create PagerDuty incident", extra={"dependency": check.key, "error": str(exc)})
                results[check.key] = "down_incident_failed"

    await redis_state.aclose()
    return results


def run_dependency_health_checks_sync() -> dict[str, str]:
    return asyncio.run(run_dependency_health_checks())


@celery_app.task(name="workers.tasks.health_monitor.check_dependencies")
def check_dependencies() -> dict[str, str]:
    """Celery task wrapper for dependency monitoring."""
    return run_dependency_health_checks_sync()
