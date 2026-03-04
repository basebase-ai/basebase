"""Add GIN index on conversations.participating_user_ids for fast array lookups.

Revision ID: 089_gin_index_participating_user_ids
Revises: 088_add_org_company_summary
Create Date: 2026-03-03

Array containment checks (ANY) on participating_user_ids cause sequential scans
on every chat list request. A GIN index enables indexed array lookups.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "089_gin_index_participating_user_ids"
down_revision: Union[str, None] = "088_add_org_company_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_participating_user_ids_gin",
        "conversations",
        ["participating_user_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversations_participating_user_ids_gin",
        table_name="conversations",
    )
