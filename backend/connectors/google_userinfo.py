"""Shared Google OAuth userinfo for account_identifier / label / avatar."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from connectors.account_metadata import AccountMetadata

logger = logging.getLogger(__name__)

GOOGLE_USERINFO_URL: str = "https://www.googleapis.com/oauth2/v2/userinfo"


async def fetch_google_account_metadata(access_token: str) -> AccountMetadata:
    """Resolve Google account email (identifier) and optional name / picture."""
    headers: dict[str, str] = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(GOOGLE_USERINFO_URL, headers=headers)
        response.raise_for_status()
        data: dict[str, Any] = response.json()

    email_raw: Any = data.get("email") or data.get("id")
    if not email_raw:
        raise ValueError("Google userinfo response missing email/id")
    identifier: str = str(email_raw).strip().lower()
    name_raw: Any = data.get("name")
    label: str | None = str(name_raw).strip() if isinstance(name_raw, str) and name_raw.strip() else identifier
    pic_raw: Any = data.get("picture")
    avatar: str | None = str(pic_raw).strip() if isinstance(pic_raw, str) and pic_raw.strip() else None
    return AccountMetadata(identifier=identifier, label=label, avatar_url=avatar)
