"""Account identity metadata returned after OAuth (multi-account integrations)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountMetadata:
    """Stable account identity plus optional UI fields."""

    identifier: str
    label: str | None = None
    avatar_url: str | None = None
