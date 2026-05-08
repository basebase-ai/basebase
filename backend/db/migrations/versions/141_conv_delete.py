"""Cascade chat message deletes with conversations.

Revision ID: 141_conv_delete
Revises: 140_global_email_scope
Create Date: 2026-05-07
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "141_conv_delete"
down_revision: Union[str, None] = "140_global_email_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_chat_messages_conversation_fk(on_delete: str | None) -> None:
    action_sql = f" ON DELETE {on_delete}" if on_delete else ""
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE
                constraint_name text;
            BEGIN
                SELECT con.conname INTO constraint_name
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                JOIN pg_attribute att ON att.attrelid = rel.oid
                    AND att.attnum = ANY(con.conkey)
                JOIN pg_class foreign_rel ON foreign_rel.oid = con.confrelid
                WHERE con.contype = 'f'
                  AND nsp.nspname = current_schema()
                  AND rel.relname = 'chat_messages'
                  AND att.attname = 'conversation_id'
                  AND foreign_rel.relname = 'conversations'
                LIMIT 1;

                IF constraint_name IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE chat_messages DROP CONSTRAINT %I', constraint_name);
                END IF;

                ALTER TABLE chat_messages
                ADD CONSTRAINT fk_chat_messages_conversation_id
                FOREIGN KEY (conversation_id)
                REFERENCES conversations(id){action_sql};
            END $$;
            """
        )
    )


def upgrade() -> None:
    _replace_chat_messages_conversation_fk("CASCADE")


def downgrade() -> None:
    _replace_chat_messages_conversation_fk(None)
