"""Infrastructure reachability monitoring and PagerDuty alerting tasks."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import text

from config import get_redis_connection_kwargs, settings
from models.database import get_admin_session
from services.incident_throttling import clear_incident_failure, evaluate_incident_creation
from services.pagerduty import create_pagerduty_incident
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_HEARTBEAT_KEY = "monitoring:dependency_checks:last_completed_at"
_HEARTBEAT_STALE_AFTER_SECONDS = 30 * 60
_ACTION_LEDGER_MAX_BYTES = 10 * 1024 * 1024 * 1024
_ACTION_LEDGER_TARGET_BYTES = 9 * 1024 * 1024 * 1024
_ACTION_LEDGER_RETENTION_DAYS = 100
_ACTION_LEDGER_DELETE_BATCH_SIZE = 1000


@dataclass(frozen=True)
class CheckResult:
    """Represents reachability status for a monitored dependency."""

    name: str
    healthy: bool
    details: str


def _api_healthcheck_url() -> str:
    """Resolve API health endpoint URL for ASGI process monitoring."""
    base_url = settings.BACKEND_PUBLIC_URL or "https://api.basebase.com"
    return f"{base_url.rstrip('/')}/health"


async def _check_http_endpoint(name: str, url: str, timeout_s: float = 10.0) -> CheckResult:
    """Check if an HTTP endpoint is reachable and returns a non-5xx response."""
    logger.info("Checking endpoint %s (%s)", name, url)
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.get(url)
        if name == "Supabase" and response.status_code == 522:
            return CheckResult(
                name=name,
                healthy=False,
                details=(
                    f"HTTP 522 from {url} (possible Supabase connection pool outage)"
                ),
            )
        if response.status_code >= 500:
            return CheckResult(name=name, healthy=False, details=f"HTTP {response.status_code} from {url}")
        return CheckResult(name=name, healthy=True, details=f"HTTP {response.status_code} from {url}")
    except Exception as exc:
        logger.exception("Endpoint check failed for %s (%s)", name, url)
        return CheckResult(name=name, healthy=False, details=f"Request failed for {url}: {exc}")


async def _check_jwks_endpoint(timeout_s: float = 10.0) -> CheckResult:
    """Check if Supabase JWKS endpoint is reachable and returns signing keys."""
    supabase_url = settings.SUPABASE_URL
    if not supabase_url:
        return CheckResult(
            name="Auth JWKS",
            healthy=False,
            details="SUPABASE_URL is not configured",
        )

    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    logger.info("Checking JWKS endpoint (%s)", jwks_url)
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            response = await client.get(jwks_url)
        if response.status_code >= 500:
            return CheckResult(name="Auth JWKS", healthy=False, details=f"HTTP {response.status_code} from {jwks_url}")

        payload = response.json()
        keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(keys, list):
            return CheckResult(name="Auth JWKS", healthy=False, details=f"Invalid JWKS payload from {jwks_url}")

        return CheckResult(name="Auth JWKS", healthy=True, details=f"JWKS reachable with {len(keys)} key(s)")
    except Exception as exc:
        logger.exception("JWKS endpoint check failed (%s)", jwks_url)
        return CheckResult(name="Auth JWKS", healthy=False, details=f"Request failed for {jwks_url}: {exc}")


async def _check_redis(timeout_s: float = 10.0) -> CheckResult:
    """Check if Redis is reachable via PING."""
    import redis.asyncio as aioredis

    redis_url = settings.REDIS_URL
    logger.info("Checking Redis reachability via %s", redis_url)
    redis_client = aioredis.from_url(
        redis_url,
        **get_redis_connection_kwargs(),
    )

    try:
        async with redis_client:
            is_ok = await redis_client.ping()
        if is_ok:
            return CheckResult(name="Redis", healthy=True, details="PING returned true")
        return CheckResult(name="Redis", healthy=False, details="PING returned false")
    except Exception as exc:
        logger.exception("Redis health check failed")
        return CheckResult(name="Redis", healthy=False, details=f"Redis ping failed: {exc}")


async def _create_pagerduty_incident(
    *,
    check_result: CheckResult,
) -> None:
    """Create an incident in PagerDuty v2 REST API."""
    await create_pagerduty_incident(
        title=f"{check_result.name} is down",
        details=(
            "Automated Basebase dependency monitor detected an outage. "
            f"Dependency: {check_result.name}. Details: {check_result.details}"
        ),
    )


async def _run_dependency_checks() -> list[CheckResult]:
    """Run all dependency checks and return results."""
    checks = [
        _check_http_endpoint("Supabase", settings.SUPABASE_URL or "https://supabase.com"),
        _check_jwks_endpoint(),
        _check_http_endpoint("Nango", settings.NANGO_HOST),
        _check_redis(),
        _check_http_endpoint("www.basebase.com", "https://www.basebase.com"),
        _check_http_endpoint("API ASGI", _api_healthcheck_url()),
    ]

    return [await check for check in checks]


async def _record_check_heartbeat() -> None:
    """Persist the completion timestamp for dependency checks in Redis."""
    import redis.asyncio as aioredis

    now = int(time.time())
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(),
    )

    async with redis_client:
        await redis_client.set(_HEARTBEAT_KEY, now)

    logger.info("Recorded dependency-check heartbeat timestamp=%s", now)


async def _heartbeat_age_seconds() -> int | None:
    """Read heartbeat age in seconds from Redis, or None if unset."""
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        **get_redis_connection_kwargs(),
    )
    now = int(time.time())

    async with redis_client:
        raw_value = await redis_client.get(_HEARTBEAT_KEY)

    if raw_value is None:
        return None

    try:
        last_completed_at = int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid monitoring heartbeat payload in Redis: %r", raw_value)
        return _HEARTBEAT_STALE_AFTER_SECONDS + 1

    return max(0, now - last_completed_at)


@celery_app.task(bind=True, name="workers.tasks.monitoring.monitor_dependencies")
def monitor_dependencies(self: Any) -> dict[str, Any]:
    """Periodic task: monitor key dependencies and open PagerDuty incidents if down."""
    from workers.run_async import run_async

    logger.info("Task %s: Starting dependency monitoring run", self.request.id)

    async def _run() -> dict[str, Any]:
        try:
            results = await _run_dependency_checks()
            await _record_check_heartbeat()
        except Exception as exc:
            logger.exception("Dependency monitoring run failed before checks completed")
            await create_pagerduty_incident(
                title="Dependency monitor failed to run",
                details=(
                    "Automated dependency checks failed to complete. "
                    f"Error: {exc}"
                ),
            )
            return {
                "status": "failed",
                "error": str(exc),
            }

        down = [result for result in results if not result.healthy]

        for result in results:
            level = logging.INFO if result.healthy else logging.WARNING
            logger.log(level, "Dependency check: %s healthy=%s (%s)", result.name, result.healthy, result.details)

            if result.healthy:
                logger.info(
                    "PagerDuty health check succeeded for %s; incident creation skipped",
                    result.name,
                )
                await clear_incident_failure(result.name)
            else:
                logger.warning(
                    "PagerDuty health check failed for %s; evaluating incident throttle",
                    result.name,
                )

        for result in down:
            should_create, reason = await evaluate_incident_creation(result.name)
            if not should_create:
                logger.info(
                    "PagerDuty incident suppressed for %s due to throttle reason=%s",
                    result.name,
                    reason,
                )
                continue

            logger.warning(
                "PagerDuty incident allowed for %s reason=%s",
                result.name,
                reason,
            )
            await _create_pagerduty_incident(
                check_result=result,
            )

        return {
            "status": "ok",
            "total_checks": len(results),
            "down_count": len(down),
            "down_services": [result.name for result in down],
        }

    return run_async(_run())


@celery_app.task(bind=True, name="workers.tasks.monitoring.monitoring_heartbeat_watchdog")
def monitoring_heartbeat_watchdog(self: Any) -> dict[str, Any]:
    """Ensure dependency checks are executing regularly and incident on stale runs."""
    from workers.run_async import run_async

    logger.info("Task %s: Starting dependency monitor heartbeat watchdog", self.request.id)

    async def _run() -> dict[str, Any]:
        try:
            age_seconds = await _heartbeat_age_seconds()
        except Exception as exc:
            logger.exception("Failed to read dependency monitor heartbeat")
            await create_pagerduty_incident(
                title="Dependency monitor heartbeat unavailable",
                details=(
                    "Could not read monitoring heartbeat state from Redis, so regular "
                    f"health-check execution cannot be verified. Error: {exc}"
                ),
            )
            return {"status": "failed", "error": str(exc)}

        if age_seconds is None:
            logger.warning("Dependency monitor heartbeat is missing")
            await create_pagerduty_incident(
                title="Dependency monitor heartbeat missing",
                details=(
                    "No dependency-check heartbeat has been recorded yet. "
                    "Health checks may not be running."
                ),
            )
            return {"status": "stale", "age_seconds": None}

        if age_seconds >= _HEARTBEAT_STALE_AFTER_SECONDS:
            logger.warning(
                "Dependency monitor heartbeat stale age_seconds=%s threshold_seconds=%s",
                age_seconds,
                _HEARTBEAT_STALE_AFTER_SECONDS,
            )
            await create_pagerduty_incident(
                title="Dependency monitor heartbeat stale",
                details=(
                    "Dependency checks have not completed within the required interval. "
                    f"Last completion age_seconds={age_seconds}. "
                    f"Threshold_seconds={_HEARTBEAT_STALE_AFTER_SECONDS}."
                ),
            )
            return {"status": "stale", "age_seconds": age_seconds}

        logger.info(
            "Dependency monitor heartbeat healthy age_seconds=%s threshold_seconds=%s",
            age_seconds,
            _HEARTBEAT_STALE_AFTER_SECONDS,
        )
        return {"status": "ok", "age_seconds": age_seconds}

    return run_async(_run())


async def _action_ledger_total_bytes() -> int:
    """Return total bytes occupied by action_ledger table (+indexes)."""
    async with get_admin_session() as session:
        result = await session.execute(
            text("SELECT pg_total_relation_size('action_ledger')")
        )
        size_bytes = int(result.scalar_one() or 0)
    return size_bytes


async def _delete_action_ledger_batch(*, cutoff: datetime | None) -> int:
    """Delete oldest action_ledger rows in bounded batches."""
    clause = "WHERE created_at < :cutoff" if cutoff is not None else ""
    params: dict[str, Any] = {"batch_size": _ACTION_LEDGER_DELETE_BATCH_SIZE}
    if cutoff is not None:
        params["cutoff"] = cutoff

    async with get_admin_session() as session:
        result = await session.execute(
            text(
                f"""
                WITH doomed AS (
                    SELECT id
                    FROM action_ledger
                    {clause}
                    ORDER BY created_at ASC
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                DELETE FROM action_ledger a
                USING doomed d
                WHERE a.id = d.id
                RETURNING a.id
                """
            ),
            params,
        )
        deleted = len(result.fetchall())
        await session.commit()
    return deleted


@celery_app.task(bind=True, name="workers.tasks.monitoring.prune_action_ledger")
def prune_action_ledger(self: Any) -> dict[str, Any]:
    """Apply time and size retention limits to action_ledger."""
    from workers.run_async import run_async

    logger.info("Task %s: Starting action_ledger pruning run", self.request.id)

    async def _run() -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=_ACTION_LEDGER_RETENTION_DAYS)
        deleted_for_age = 0
        deleted_for_size = 0

        # 1) Always enforce retention window first.
        while True:
            deleted = await _delete_action_ledger_batch(cutoff=cutoff)
            if deleted == 0:
                break
            deleted_for_age += deleted
            logger.info(
                "action_ledger retention batch deleted=%s cutoff=%s",
                deleted,
                cutoff.isoformat(),
            )

        # 2) Enforce max size by trimming oldest rows.
        current_size = await _action_ledger_total_bytes()
        logger.info(
            "action_ledger size check bytes=%s max_bytes=%s target_bytes=%s",
            current_size,
            _ACTION_LEDGER_MAX_BYTES,
            _ACTION_LEDGER_TARGET_BYTES,
        )
        while current_size > _ACTION_LEDGER_MAX_BYTES:
            deleted = await _delete_action_ledger_batch(cutoff=None)
            if deleted == 0:
                logger.warning(
                    "action_ledger exceeded max size but no rows were deleted; stopping prune loop"
                )
                break
            deleted_for_size += deleted
            current_size = await _action_ledger_total_bytes()
            logger.info(
                "action_ledger size-prune batch deleted=%s remaining_bytes=%s",
                deleted,
                current_size,
            )
            if current_size <= _ACTION_LEDGER_TARGET_BYTES:
                break

        final_size = await _action_ledger_total_bytes()
        logger.info(
            "action_ledger prune complete deleted_for_age=%s deleted_for_size=%s final_bytes=%s",
            deleted_for_age,
            deleted_for_size,
            final_size,
        )
        return {
            "status": "ok",
            "deleted_for_age": deleted_for_age,
            "deleted_for_size": deleted_for_size,
            "final_size_bytes": final_size,
            "retention_days": _ACTION_LEDGER_RETENTION_DAYS,
            "max_size_bytes": _ACTION_LEDGER_MAX_BYTES,
        }

    return run_async(_run())
