"""Utilities for warming public preview metadata/image caches after creation."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx

from config import settings

logger = logging.getLogger(__name__)

PreviewEntity = Literal["app", "artifact"]


def _build_preview_urls(entity: PreviewEntity, entity_id: str) -> list[str]:
    """Return candidate URLs that trigger metadata + snapshot cache generation."""
    base = settings.FRONTEND_URL.rstrip("/")
    if entity == "app":
        return [
            f"{base}/basebase/apps/{entity_id}",
            f"{base}/api/public/share/apps/{entity_id}",
            f"{base}/api/public/share/apps/{entity_id}/snapshot.png",
        ]
    return [
        f"{base}/basebase/documents/{entity_id}",
        f"{base}/api/public/share/artifacts/{entity_id}",
        f"{base}/api/public/share/artifacts/{entity_id}/snapshot.png",
    ]


async def _fetch_for_warmup(client: httpx.AsyncClient, url: str) -> tuple[str, int | None]:
    try:
        response = await client.get(url)
        return url, response.status_code
    except Exception:
        logger.exception("[public_preview_warmup] request failed url=%s", url)
        return url, None


async def warm_public_preview_cache(entity: PreviewEntity, entity_id: str) -> None:
    """
    Best-effort warmup for social preview endpoints before returning share/view links.

    This intentionally never raises so create flows remain reliable if warmup endpoints
    are temporarily unavailable.
    """
    urls = _build_preview_urls(entity, entity_id)
    logger.info(
        "[public_preview_warmup] start entity=%s entity_id=%s candidate_urls=%s",
        entity,
        entity_id,
        urls,
    )
    timeout = httpx.Timeout(5.0, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        results = await asyncio.gather(*[_fetch_for_warmup(client, url) for url in urls])

    for url, status in results:
        if status is None:
            logger.warning("[public_preview_warmup] no-response entity=%s entity_id=%s url=%s", entity, entity_id, url)
            continue
        if status >= 400:
            logger.warning(
                "[public_preview_warmup] non-success status entity=%s entity_id=%s status=%s url=%s",
                entity,
                entity_id,
                status,
                url,
            )
            continue
        logger.info(
            "[public_preview_warmup] warmed entity=%s entity_id=%s status=%s url=%s",
            entity,
            entity_id,
            status,
            url,
        )
