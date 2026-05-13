"""Shared Google account-identity helpers for account_identifier / label / avatar.

Different Google connectors are granted different OAuth scopes, so a single
shared endpoint (e.g. ``/oauth2/v2/userinfo``) is not always reachable. Each
service exposes its own "who am I" endpoint that requires only the service's
own scope:

- Gmail:    ``GET gmail/v1/users/me/profile`` (gmail.readonly / gmail.metadata)
- Drive:    ``GET drive/v3/about?fields=user(emailAddress,displayName,photoLink)``
- Calendar: ``GET calendar/v3/users/me/calendarList`` (look for ``primary=true``)
- userinfo: ``GET oauth2/v2/userinfo`` (requires ``email`` / ``profile`` scopes)

``fetch_google_account_metadata`` tries the configured ``sources`` in order and
returns the first successful identity. Connectors pass their own service first
so we only fall back when truly necessary.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from connectors.account_metadata import AccountMetadata

logger = logging.getLogger(__name__)

GOOGLE_USERINFO_URL: str = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_PROFILE_URL: str = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
DRIVE_ABOUT_URL: str = "https://www.googleapis.com/drive/v3/about"
CALENDAR_LIST_URL: str = "https://www.googleapis.com/calendar/v3/users/me/calendarList"

_DEFAULT_SOURCES: tuple[str, ...] = ("userinfo", "gmail", "drive", "calendar")


async def _from_userinfo(client: httpx.AsyncClient, headers: dict[str, str]) -> AccountMetadata:
    response = await client.get(GOOGLE_USERINFO_URL, headers=headers)
    response.raise_for_status()
    data: dict[str, Any] = response.json() or {}
    email_raw: Any = data.get("email") or data.get("id")
    if not email_raw:
        raise ValueError("Google userinfo response missing email/id")
    identifier: str = str(email_raw).strip().lower()
    name_raw: Any = data.get("name")
    label: str | None = (
        str(name_raw).strip() if isinstance(name_raw, str) and name_raw.strip() else identifier
    )
    pic_raw: Any = data.get("picture")
    avatar: str | None = (
        str(pic_raw).strip() if isinstance(pic_raw, str) and pic_raw.strip() else None
    )
    return AccountMetadata(identifier=identifier, label=label, avatar_url=avatar)


async def _from_gmail_profile(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> AccountMetadata:
    response = await client.get(GMAIL_PROFILE_URL, headers=headers)
    response.raise_for_status()
    data: dict[str, Any] = response.json() or {}
    email_raw: Any = data.get("emailAddress")
    if not email_raw:
        raise ValueError("Gmail profile response missing emailAddress")
    identifier: str = str(email_raw).strip().lower()
    return AccountMetadata(identifier=identifier, label=identifier, avatar_url=None)


async def _from_drive_about(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> AccountMetadata:
    response = await client.get(
        DRIVE_ABOUT_URL,
        headers=headers,
        params={"fields": "user(emailAddress,displayName,photoLink)"},
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json() or {}
    user: dict[str, Any] = body.get("user") or {}
    email_raw: Any = user.get("emailAddress")
    if not email_raw:
        raise ValueError("Drive about response missing user.emailAddress")
    identifier: str = str(email_raw).strip().lower()
    name_raw: Any = user.get("displayName")
    label: str | None = (
        str(name_raw).strip() if isinstance(name_raw, str) and name_raw.strip() else identifier
    )
    pic_raw: Any = user.get("photoLink")
    avatar: str | None = (
        str(pic_raw).strip() if isinstance(pic_raw, str) and pic_raw.strip() else None
    )
    return AccountMetadata(identifier=identifier, label=label, avatar_url=avatar)


async def _from_calendar_list(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> AccountMetadata:
    response = await client.get(
        CALENDAR_LIST_URL,
        headers=headers,
        params={"maxResults": 250},
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json() or {}
    items_raw: Any = body.get("items")
    items: list[dict[str, Any]] = items_raw if isinstance(items_raw, list) else []
    primary: dict[str, Any] | None = next(
        (c for c in items if isinstance(c, dict) and c.get("primary")),
        None,
    )
    if primary is None and items:
        primary = items[0] if isinstance(items[0], dict) else None
    if primary is None:
        raise ValueError("Calendar list response empty")
    email_raw: Any = primary.get("id")
    if not email_raw:
        raise ValueError("Calendar list missing primary id")
    identifier: str = str(email_raw).strip().lower()
    summary_raw: Any = primary.get("summary")
    label: str | None = (
        str(summary_raw).strip() if isinstance(summary_raw, str) and summary_raw.strip() else identifier
    )
    return AccountMetadata(identifier=identifier, label=label, avatar_url=None)


async def fetch_google_account_metadata(
    access_token: str,
    *,
    sources: tuple[str, ...] | list[str] | None = None,
) -> AccountMetadata:
    """Resolve a Google account's email / label / avatar using the first source that works.

    Args:
        access_token: OAuth access token.
        sources: Ordered list of identity sources to try. Each connector should
            pass its own service first (e.g. ``("gmail", "userinfo")`` for the
            Gmail connector) to avoid wasted 401s on scopes it does not own.
    """
    chosen: tuple[str, ...] = tuple(sources) if sources else _DEFAULT_SOURCES
    headers: dict[str, str] = {"Authorization": f"Bearer {access_token}"}
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        for source in chosen:
            try:
                if source == "userinfo":
                    return await _from_userinfo(client, headers)
                if source == "gmail":
                    return await _from_gmail_profile(client, headers)
                if source == "drive":
                    return await _from_drive_about(client, headers)
                if source == "calendar":
                    return await _from_calendar_list(client, headers)
                logger.warning(
                    "Unknown Google identity source requested",
                    extra={"source": source},
                )
            except Exception as exc:
                last_error = exc
                logger.info(
                    "Google account metadata source failed; trying next",
                    extra={"source": source, "error": str(exc)},
                )
                continue
    if last_error is not None:
        raise last_error
    raise ValueError("No Google account metadata source produced a result")
