"""Scope meetings to ingesting connector.

Revision ID: 137_meeting_scope
Revises: 136_web_search_integration
Create Date: 2026-05-06

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision: str = "137_meeting_scope"
down_revision: Union[str, None] = "136_web_search_integration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NULL_UUID: str = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "meetings",
        sa.Column(
            "integration_id",
            sa.UUID(),
            sa.ForeignKey("integrations.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "meetings",
        sa.Column(
            "owner_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "meetings",
        sa.Column("visibility", sa.String(20), nullable=False, server_default="team"),
    )

    # Backfill from linked activities. If any linked activity is team-visible, the
    # meeting remains team-visible; otherwise keep it private to the owner of the
    # most recently synced linked activity. The grouped CTE keeps the update
    # set-based and avoids broad table locks beyond normal UPDATE row locks.
    conn.execute(
        text("""
            WITH scoped AS (
                SELECT
                    a.meeting_id,
                    CASE
                        WHEN bool_or(a.visibility = 'team') THEN 'team'::varchar
                        ELSE 'owner_only'::varchar
                    END AS visibility,
                    (
                        array_agg(a.integration_id ORDER BY a.synced_at DESC NULLS LAST)
                    )[1] AS integration_id,
                    CASE
                        WHEN bool_or(a.visibility = 'team') THEN NULL::uuid
                        ELSE (
                            array_agg(a.owner_user_id ORDER BY a.synced_at DESC NULLS LAST)
                        )[1]
                    END AS owner_user_id
                FROM activities a
                WHERE a.meeting_id IS NOT NULL
                GROUP BY a.meeting_id
            )
            UPDATE meetings m
            SET
                integration_id = scoped.integration_id,
                owner_user_id = scoped.owner_user_id,
                visibility = scoped.visibility
            FROM scoped
            WHERE scoped.meeting_id = m.id
        """)
    )

    op.create_index("ix_meetings_integration_id", "meetings", ["integration_id"])
    op.create_index("ix_meetings_owner_user_id", "meetings", ["owner_user_id"])
    op.create_index(
        "ix_meetings_org_visibility",
        "meetings",
        ["organization_id", "visibility"],
    )

    conn.execute(text("DROP POLICY IF EXISTS org_isolation ON meetings"))
    conn.execute(text("DROP POLICY IF EXISTS org_and_user_isolation ON meetings"))
    conn.execute(
        text(f"""
            CREATE POLICY org_and_user_isolation ON meetings
            FOR ALL
            USING (
                organization_id::text = COALESCE(
                    NULLIF(current_setting('app.current_org_id', true), ''),
                    '{NULL_UUID}'
                )
                AND (
                    visibility = 'team'
                    OR owner_user_id IS NULL
                    OR owner_user_id::text = COALESCE(
                        NULLIF(current_setting('app.current_user_id', true), ''),
                        '{NULL_UUID}'
                    )
                )
            )
            WITH CHECK (
                organization_id::text = COALESCE(
                    NULLIF(current_setting('app.current_org_id', true), ''),
                    '{NULL_UUID}'
                )
                AND (
                    visibility = 'team'
                    OR owner_user_id IS NULL
                    OR owner_user_id::text = COALESCE(
                        NULLIF(current_setting('app.current_user_id', true), ''),
                        '{NULL_UUID}'
                    )
                )
            )
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("DROP POLICY IF EXISTS org_and_user_isolation ON meetings"))
    conn.execute(
        text(f"""
            CREATE POLICY org_isolation ON meetings
            FOR ALL
            USING (
                organization_id::text = COALESCE(
                    NULLIF(current_setting('app.current_org_id', true), ''),
                    '{NULL_UUID}'
                )
            )
        """)
    )

    op.drop_index("ix_meetings_org_visibility", table_name="meetings")
    op.drop_index("ix_meetings_owner_user_id", table_name="meetings")
    op.drop_index("ix_meetings_integration_id", table_name="meetings")
    op.drop_column("meetings", "visibility")
    op.drop_column("meetings", "owner_user_id")
    op.drop_column("meetings", "integration_id")
