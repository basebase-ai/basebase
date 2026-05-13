"""
Integration model for tracking connected integrations.

With Nango, we don't store OAuth tokens ourselves - Nango handles that.
This model just tracks which integrations are connected and their sync status.

All integrations are user-scoped (each user connects with their own credentials).
Sharing flags control what other team members can access:
- share_synced_data: Team can see synced records (deals, contacts, etc.)
- share_query_access: Team can query live data via this connection
- share_write_access: Team can write data via this connection (rare)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base

# Stored in ``extra_data`` JSONB (no dedicated column).
INTEGRATION_ACCOUNT_AVATAR_EXTRA_KEY: Final[str] = "account_avatar_url"


def read_account_avatar_url(extra_data: dict[str, Any] | None) -> str | None:
    """Return avatar URL from integration ``extra_data``, if set."""
    if not extra_data:
        return None
    raw: Any = extra_data.get(INTEGRATION_ACCOUNT_AVATAR_EXTRA_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def merge_account_avatar_into_extra_data(
    extra_data: dict[str, Any] | None,
    avatar_url: str | None,
) -> dict[str, Any] | None:
    """Return a copy of ``extra_data`` with ``account_avatar_url`` set or cleared."""
    merged: dict[str, Any] = dict(extra_data) if extra_data else {}
    if avatar_url and avatar_url.strip():
        merged[INTEGRATION_ACCOUNT_AVATAR_EXTRA_KEY] = avatar_url.strip()
    else:
        merged.pop(INTEGRATION_ACCOUNT_AVATAR_EXTRA_KEY, None)
    return merged or None


class Integration(Base):  # type: ignore[misc]
    """
    Integration model for tracking connected integrations.

    Nango handles OAuth tokens and credentials.
    We store the nango_connection_id to retrieve credentials when needed.

    All integrations are user-scoped. Sharing flags control team access:
    - share_synced_data: Others can see synced data (default true for CRMs)
    - share_query_access: Others can query live data via this connection
    - share_write_access: Others can write via this connection (almost always false)
    """

    def __init__(self, **kwargs: Any) -> None:
        if "provider" not in kwargs and "connector" in kwargs:
            kwargs["provider"] = kwargs["connector"]
        elif "connector" not in kwargs and "provider" in kwargs:
            kwargs["connector"] = kwargs["provider"]
        super().__init__(**kwargs)

    __tablename__ = "integrations"
    __table_args__ = (
        Index(
            "uq_integration_org_connector_user_single",
            "organization_id",
            "connector",
            "user_id",
            unique=True,
            postgresql_where=text("account_identifier IS NULL"),
        ),
        Index(
            "uq_integration_org_connector_user_account",
            "organization_id",
            "connector",
            "user_id",
            "account_identifier",
            unique=True,
            postgresql_where=text("account_identifier IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )

    # Connector slug: 'hubspot', 'slack', 'google_calendar', 'salesforce', 'gmail', etc.
    connector: Mapped[str] = mapped_column(String(50), nullable=False)

    # Legacy column kept for DB NOT-NULL constraint; always mirrors `connector`.
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # Owner of this integration (who authenticated)
    # NOTE: nullable=True for backwards compatibility during migration.
    # New code always sets user_id; Phase 2 migration will make it NOT NULL.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE"), nullable=True, index=True
    )

    # DEPRECATED: scope column kept for backwards compatibility with old clients.
    # All new integrations are user-scoped. Will be dropped in Phase 2 migration.
    scope: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Sharing flags - control what team members can access
    share_synced_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_query_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_write_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # True until user configures sharing preferences after OAuth
    pending_sharing_config: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Nango connection ID — legacy "{org_id}:user:{user_id}" or suffixed with
    # ":{uuid}" for multi-account rows.
    nango_connection_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Stable per-provider account id (email, portal id, team id, etc.). NULL
    # until backfilled; at most one NULL row per (org, connector, user).
    account_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Human-readable label for UI (e.g. display name, workspace name).
    account_label: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # User who connected this integration (same as user_id, kept for audit trail)
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE"), nullable=True
    )

    # Status
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Additional provider-specific data
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Sync statistics - counts of objects synced (e.g., {"accounts": 5, "deals": 10})
    sync_stats: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True
    )

    def to_dict(self, include_sharing: bool = False) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        avatar_url: str | None = read_account_avatar_url(self.extra_data)
        result: dict[str, Any] = {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "connector": self.connector,
            "provider": self.connector,  # Deprecated alias for connector; remove after frontend migration
            "user_id": str(self.user_id),
            "account_identifier": self.account_identifier,
            "account_label": self.account_label,
            "account_avatar_url": avatar_url,
            "is_active": self.is_active,
            "last_sync_at": f"{self.last_sync_at.isoformat()}Z" if self.last_sync_at else None,
            "last_error": self.last_error,
            "created_at": f"{self.created_at.isoformat()}Z" if self.created_at else None,
            "sync_stats": self.sync_stats,
        }
        if include_sharing:
            result.update({
                "share_synced_data": self.share_synced_data,
                "share_query_access": self.share_query_access,
                "share_write_access": self.share_write_access,
                "pending_sharing_config": self.pending_sharing_config,
                "connected_by_user_id": str(self.connected_by_user_id) if self.connected_by_user_id else None,
            })
        return result
