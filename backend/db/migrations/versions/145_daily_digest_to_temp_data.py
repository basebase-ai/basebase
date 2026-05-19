"""Migrate daily digest to temp_data; seed workflow + app; drop legacy tables.

Revision ID: 145_daily_digest_temp
Revises: 144_add_models_llm_usage
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "145_daily_digest_temp"
down_revision: Union[str, None] = "144_add_models_llm_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dedupe_temp_data(conn: sa.Connection) -> None:
    conn.execute(
        sa.text("""
        DELETE FROM temp_data a
        USING temp_data b
        WHERE a.id > b.id
          AND a.organization_id = b.organization_id
          AND a.namespace = b.namespace
          AND COALESCE(a.key, '') = COALESCE(b.key, '')
          AND COALESCE(a.entity_type, '') = COALESCE(b.entity_type, '')
          AND COALESCE(a.entity_id::text, '') = COALESCE(b.entity_id::text, '')
        """)
    )


def _backfill_from_legacy(conn: sa.Connection) -> None:
    conn.execute(
        sa.text("""
        INSERT INTO temp_data (
            id, organization_id, entity_type, entity_id, namespace, key,
            value, metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            d.organization_id,
            'user',
            d.user_id,
            'daily_digest',
            d.digest_date::text,
            d.summary || jsonb_build_object(
                'active_sources',
                COALESCE(d.raw_data->'active_sources', '[]'::jsonb)
            ),
            jsonb_build_object('generated_at', d.generated_at),
            d.generated_at
        FROM daily_digests d
        ON CONFLICT ON CONSTRAINT uq_temp_data_digest_slot DO NOTHING
        """)
    )
    conn.execute(
        sa.text("""
        INSERT INTO temp_data (
            id, organization_id, entity_type, entity_id, namespace, key,
            value, metadata, created_at
        )
        SELECT
            gen_random_uuid(),
            t.organization_id,
            'team',
            t.organization_id,
            'daily_digest',
            t.digest_date::text,
            jsonb_build_object('summary_text', t.summary_text, 'member_count', 0),
            jsonb_build_object('generated_at', t.generated_at),
            t.generated_at
        FROM daily_team_summaries t
        ON CONFLICT ON CONSTRAINT uq_temp_data_digest_slot DO NOTHING
        """)
    )


def _seed_workflow_and_app(conn: sa.Connection) -> None:
    from services.digest_templates import (
        DAILY_DIGEST_APP_FRONTEND_CODE,
        DAILY_DIGEST_APP_QUERIES,
        DAILY_DIGEST_APP_TITLE,
        DAILY_DIGEST_WORKFLOW_NAME,
        DAILY_DIGEST_WORKFLOW_PROMPT,
    )

    org_rows = conn.execute(sa.text("SELECT id FROM organizations")).fetchall()
    for (org_id,) in org_rows:
        org_str: str = str(org_id)
        owner_row = conn.execute(
            sa.text("""
            SELECT om.user_id
            FROM org_members om
            JOIN users u ON u.id = om.user_id
            WHERE om.organization_id = :oid
              AND om.status = 'active'
              AND u.is_guest = false
            ORDER BY
              CASE om.role WHEN 'admin' THEN 0 ELSE 1 END,
              om.created_at ASC NULLS LAST
            LIMIT 1
            """),
            {"oid": org_str},
        ).fetchone()
        if owner_row is None:
            continue
        owner_id: str = str(owner_row[0])

        existing_wf = conn.execute(
            sa.text("""
            SELECT id FROM workflows
            WHERE organization_id = :oid AND name = :name AND archived_at IS NULL
            LIMIT 1
            """),
            {"oid": org_str, "name": DAILY_DIGEST_WORKFLOW_NAME},
        ).fetchone()

        if existing_wf is not None:
            workflow_id: str = str(existing_wf[0])
        else:
            workflow_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                INSERT INTO workflows (
                    id, organization_id, created_by_user_id, name, description,
                    trigger_type, trigger_config, steps, prompt, auto_approve_tools,
                    is_enabled
                ) VALUES (
                    :id, :oid, :uid, :name, :desc,
                    'schedule', CAST(:trigger AS jsonb), '[]'::jsonb, :prompt,
                    CAST(:tools AS jsonb), true
                )
                """),
                {
                    "id": workflow_id,
                    "oid": org_str,
                    "uid": owner_id,
                    "name": DAILY_DIGEST_WORKFLOW_NAME,
                    "desc": "Nightly per-member activity summaries stored in temp_data.",
                    "trigger": json.dumps({"cron": "0 8 * * *"}),
                    "prompt": DAILY_DIGEST_WORKFLOW_PROMPT,
                    "tools": json.dumps(
                        ["run_sql_query", "run_sql_write", "collect_digest_data"]
                    ),
                },
            )

        existing_app = conn.execute(
            sa.text("""
            SELECT id FROM apps
            WHERE organization_id = :oid AND title = :title
            LIMIT 1
            """),
            {"oid": org_str, "title": DAILY_DIGEST_APP_TITLE},
        ).fetchone()

        if existing_app is not None:
            app_id: str = str(existing_app[0])
        else:
            app_id = str(uuid.uuid4())
            conn.execute(
                sa.text("""
                INSERT INTO apps (
                    id, user_id, organization_id, visibility, title, description,
                    queries, frontend_code
                ) VALUES (
                    :id, :uid, :oid, 'team', :title, :desc,
                    CAST(:queries AS jsonb), :frontend
                )
                """),
                {
                    "id": app_id,
                    "uid": owner_id,
                    "oid": org_str,
                    "title": DAILY_DIGEST_APP_TITLE,
                    "desc": "Team daily digest from workflow-generated temp_data rows.",
                    "queries": json.dumps(DAILY_DIGEST_APP_QUERIES),
                    "frontend": DAILY_DIGEST_APP_FRONTEND_CODE,
                },
            )

        conn.execute(
            sa.text("""
            UPDATE organizations SET home_app_id = :app_id WHERE id = :oid
            """),
            {"app_id": app_id, "oid": org_str},
        )


def upgrade() -> None:
    conn = op.get_bind()
    _dedupe_temp_data(conn)
    op.create_unique_constraint(
        "uq_temp_data_digest_slot",
        "temp_data",
        ["organization_id", "namespace", "key", "entity_type", "entity_id"],
    )
    _backfill_from_legacy(conn)
    _seed_workflow_and_app(conn)

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
    op.drop_constraint("uq_temp_data_digest_slot", "temp_data", type_="unique")
