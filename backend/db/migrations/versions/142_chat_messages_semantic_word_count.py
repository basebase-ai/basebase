"""Add semantic_word_count to chat_messages.

Denormalizes per-message word count of text-type content blocks so that
``services.conversation_summary.count_semantic_words_for_conversation`` can
become ``SELECT sum(semantic_word_count) WHERE conversation_id = $1`` instead
of streaming every row's full ``content_blocks`` JSONB back to Python on every
assistant reply.

Revision ID: 142_chat_msg_swc
Revises: 141_conv_delete
Create Date: 2026-05-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "142_chat_msg_swc"
down_revision: Union[str, None] = "141_conv_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Adding a column with a non-volatile default is a metadata-only operation
    # in PG 11+, so this is fast even on very large tables.
    op.add_column(
        "chat_messages",
        sa.Column(
            "semantic_word_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Backfill is intentionally NOT run here — see
    # ``backend/scripts/backfill_chat_message_semantic_word_count.py`` for an
    # operator-controlled batched backfill. New writes are kept correct by the
    # SQLAlchemy ``before_insert`` / ``before_update`` event listener on the
    # ``ChatMessage`` model.


def downgrade() -> None:
    op.drop_column("chat_messages", "semantic_word_count")
