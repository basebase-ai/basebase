"""Add agent_responding to conversations and create notifications table.

- conversations.agent_responding: when false, agent does not respond until @Basebase
- notifications: in-app mention notifications for human-to-human chat

Revision ID: 114_add_agent_responding_and_notifications
Revises: 113_create_workstreams_table
Create Date: 2026-03-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "114_add_agent_responding_and_notifications"
down_revision: Union[str, None] = "113_create_workstreams_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "agent_responding",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(50), nullable=False, server_default="mention"),
        sa.Column("conversation_id", UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("message_id", UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_notifications_user_read_created",
        "notifications",
        ["user_id", "read", "created_at"],
        postgresql_where=sa.text("read = false"),
    )

    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY notifications_user_org ON notifications
        FOR ALL
        USING (
            organization_id::text = COALESCE(NULLIF(current_setting('app.current_org_id', true), ''), '00000000-0000-0000-0000-000000000000')
            AND user_id::text = COALESCE(NULLIF(current_setting('app.current_user_id', true), ''), '00000000-0000-0000-0000-000000000000')
        )
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS notifications_user_org ON notifications")
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_column("conversations", "agent_responding")
