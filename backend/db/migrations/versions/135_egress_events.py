"""135_egress_events

Revision ID: 135_egress_events
Revises: 134_topic_graph
Create Date: 2026-05-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "135_egress_events"
down_revision = "134_topic_graph"
branch_labels = None
depends_on = None

assert len(revision) <= 32
assert not isinstance(down_revision, str) or len(down_revision) <= 32


def upgrade() -> None:
    op.create_table(
        "egress_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connector", sa.String(length=50), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=True),
        sa.Column("bytes_out", sa.Integer(), nullable=False),
        sa.Column("scan_mode", sa.String(length=32), nullable=False, server_default="count_only"),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_egress_events_org_created", "egress_events", ["organization_id", "created_at"], unique=False)
    op.create_index("ix_egress_events_connector_created", "egress_events", ["connector", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_egress_events_connector_created", table_name="egress_events")
    op.drop_index("ix_egress_events_org_created", table_name="egress_events")
    op.drop_table("egress_events")
