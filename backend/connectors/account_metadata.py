"""Account identity metadata returned after OAuth (multi-account integrations)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountMetadata:
    """Stable account identity plus optional UI fields.

    ``identifier`` is the canonical provider-side account id (e.g. email,
    workspace id, portal id). It may be ``None`` when the connector cannot
    resolve a real identity – callers must treat that as the legacy
    single-account / NULL-keyed row and never persist a placeholder UUID.
    """

    identifier: str | None
    label: str | None = None
    avatar_url: str | None = None
