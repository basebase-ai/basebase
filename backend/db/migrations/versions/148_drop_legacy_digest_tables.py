"""Drop legacy daily_digests and daily_team_summaries tables.

These tables have been fully replaced by temp_data rows with
namespace='daily_digest'. This is the destructive cleanup step
separated from the data migration (145) for backwards compatibility.

Revision ID: 148_drop_legacy_digests
Revises: 147_digest_app_theme_vars
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "148_drop_legacy_digests"
down_revision: Union[str, None] = "147_digest_app_theme_vars"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS daily_digests_select ON daily_digests")
    op.execute("DROP POLICY IF EXISTS daily_digests_insert ON daily_digests")
    op.execute("DROP POLICY IF EXISTS daily_digests_update ON daily_digests")
    op.execute("DROP POLICY IF EXISTS daily_digests_delete ON daily_digests")
    op.execute("DROP POLICY IF EXISTS daily_digests_org_isolation ON daily_digests")
    op.execute(
        "DROP POLICY IF EXISTS daily_team_summaries_org_isolation ON daily_team_summaries"
    )
    op.drop_index("ix_daily_digests_org_date", table_name="daily_digests")
    op.drop_index("ix_daily_team_summaries_org_date", table_name="daily_team_summaries")
    op.drop_table("daily_digests")
    op.drop_table("daily_team_summaries")


def downgrade() -> None:
    op.create_table(
        "daily_digests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("summary", postgresql.JSONB, nullable=False),
        sa.Column("raw_data", postgresql.JSONB, nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            "digest_date",
            name="uq_daily_digests_org_user_date",
        ),
    )
    op.create_table(
        "daily_team_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("digest_date", sa.Date(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "organization_id",
            "digest_date",
            name="uq_daily_team_summaries_org_date",
        ),
    )
    op.create_index(
        "ix_daily_digests_org_date",
        "daily_digests",
        ["organization_id", "digest_date"],
    )
    op.create_index(
        "ix_daily_team_summaries_org_date",
        "daily_team_summaries",
        ["organization_id", "digest_date"],
    )
