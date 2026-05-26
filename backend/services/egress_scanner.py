"""Count-only outbound telemetry helper used by connectors and auditing services."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from models.database import get_session
from models.egress_event import EgressEvent

logger = logging.getLogger(__name__)


def estimate_bytes_out(payload: dict[str, Any]) -> int:
    """Best-effort UTF-8 byte estimate for outbound payload logging."""
    try:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        logger.warning("[EgressScanner] Failed to JSON-encode payload; falling back to string length", exc_info=True)
        return len(str(payload).encode("utf-8"))


async def record_count_only_egress_event(
    *,
    organization_id: str,
    user_id: str | None,
    context: dict[str, Any] | None,
    connector: str,
    operation: str,
    payload: dict[str, Any],
    destination: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a count-only egress event in a short insert-only transaction."""
    bytes_out = estimate_bytes_out(payload)
    ctx = context or {}
    conversation_id = ctx.get("conversation_id")
    workflow_id = ctx.get("workflow_id")

    logger.info(
        "[EgressScanner] Recording count-only event org=%s connector=%s operation=%s bytes_out=%d destination=%s",
        organization_id,
        connector,
        operation,
        bytes_out,
        destination,
    )

    try:
        entry = EgressEvent(
            organization_id=uuid.UUID(organization_id),
            user_id=uuid.UUID(user_id) if user_id else None,
            conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
            workflow_id=uuid.UUID(workflow_id) if workflow_id else None,
            connector=connector,
            operation=operation,
            destination=destination,
            bytes_out=bytes_out,
            scan_mode="count_only",
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        )
        async with get_session(organization_id) as session:
            session.add(entry)
            await session.commit()
    except Exception:
        logger.warning(
            "[EgressScanner] Failed to record count-only egress event for %s.%s",
            connector,
            operation,
            exc_info=True,
        )
