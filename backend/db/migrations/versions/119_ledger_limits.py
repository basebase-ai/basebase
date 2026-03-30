"""Add index for user-scoped action ledger reads.

Revision ID: 119_ledger_limits
Revises: 118_create_action_ledger
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "119_ledger_limits"
down_revision: Union[str, None] = "118_create_action_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_action_ledger_org_user_created",
        "action_ledger",
        ["organization_id", "user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_action_ledger_org_user_created", table_name="action_ledger")
