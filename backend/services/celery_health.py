"""Celery worker availability checks and startup incidenting."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from services.pagerduty import create_pagerduty_incident

logger = logging.getLogger(__name__)

DEFAULT_STARTUP_PING_ATTEMPTS = 3
DEFAULT_STARTUP_RETRY_DELAY_SECONDS = 2.0


async def _inspect_celery_workers(timeout_seconds: float = 5.0) -> dict[str, Any] | None:
    """Return Celery inspect ping response, or None when no workers reply."""
    from workers.celery_app import celery_app

    def _ping() -> dict[str, Any] | None:
        inspector = celery_app.control.inspect(timeout=timeout_seconds)
        return inspector.ping()

    return await asyncio.to_thread(_ping)


async def ensure_celery_workers_available() -> bool:
    """Verify Celery worker availability and raise PagerDuty incident if unavailable."""
    max_attempts = max(1, int(os.getenv("CELERY_STARTUP_PING_ATTEMPTS", DEFAULT_STARTUP_PING_ATTEMPTS)))
    retry_delay_seconds = max(
        0.0,
        float(os.getenv("CELERY_STARTUP_RETRY_DELAY_SECONDS", DEFAULT_STARTUP_RETRY_DELAY_SECONDS)),
    )
    logger.info(
        "Checking Celery worker availability at API startup attempts=%s retry_delay_seconds=%.2f",
        max_attempts,
        retry_delay_seconds,
    )

    last_exception: Exception | None = None
    ping_response: dict[str, Any] | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            ping_response = await _inspect_celery_workers()
        except Exception as exc:  # pragma: no cover - tested via behavior
            last_exception = exc
            logger.warning(
                "Celery startup health check attempt %s/%s raised error: %s",
                attempt,
                max_attempts,
                exc,
            )
        else:
            if ping_response:
                worker_names = sorted(ping_response.keys())
                logger.info(
                    "Celery worker startup check succeeded attempt=%s/%s workers=%s",
                    attempt,
                    max_attempts,
                    worker_names,
                )
                return True

            logger.warning(
                "Celery startup health check attempt %s/%s received no worker responses",
                attempt,
                max_attempts,
            )

        if attempt < max_attempts and retry_delay_seconds > 0:
            await asyncio.sleep(retry_delay_seconds)

    if last_exception is not None:
        logger.exception("Celery startup health check failed after %s attempts", max_attempts, exc_info=last_exception)
        await create_pagerduty_incident(
            title="Celery startup check failed",
            details=(
                "API startup could not verify Celery worker availability after "
                f"{max_attempts} attempts. Error: {last_exception}"
            ),
        )
        return False

    logger.error("No Celery workers responded to startup ping after %s attempts", max_attempts)
    await create_pagerduty_incident(
        title="Celery workers unavailable at startup",
        details=(
            "API startup pinged Celery workers but received no responses after "
            f"{max_attempts} attempts. This usually means worker processes are "
            "not running or cannot connect to the broker."
        ),
    )
    return False
