"""Add account_identifier/account_label for multi-account integrations.

Allows multiple OAuth connections per (organization_id, connector, user_id)
when each row has a distinct account_identifier (e.g. Gmail email, HubSpot
portal id). Legacy rows keep account_identifier NULL until backfilled; a
partial unique index permits at most one NULL row per (org, connector, user).

Revision ID: 143_int_acct_id
Revises: 142_chat_msg_swc
Create Date: 2026-05-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "143_int_acct_id"
down_revision: Union[str, None] = "142_chat_msg_swc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "integrations",
        sa.Column("account_identifier", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "integrations",
        sa.Column("account_label", sa.String(length=512), nullable=True),
    )

    op.execute(
        'ALTER TABLE integrations DROP CONSTRAINT IF EXISTS "uq_integration_org_connector_user"'
    )

    op.create_index(
        "uq_integration_org_connector_user_single",
        "integrations",
        ["organization_id", "connector", "user_id"],
        unique=True,
        postgresql_where=sa.text("account_identifier IS NULL"),
    )
    op.create_index(
        "uq_integration_org_connector_user_account",
        "integrations",
        ["organization_id", "connector", "user_id", "account_identifier"],
        unique=True,
        postgresql_where=sa.text("account_identifier IS NOT NULL"),
    )


def downgrade() -> None:
    # Partial unique indexes: use raw SQL for reliable drops across Alembic/SQLAlchemy versions.
    op.execute("DROP INDEX IF EXISTS uq_integration_org_connector_user_account")
    op.execute("DROP INDEX IF EXISTS uq_integration_org_connector_user_single")

    op.create_unique_constraint(
        "uq_integration_org_connector_user",
        "integrations",
        ["organization_id", "connector", "user_id"],
    )

    op.drop_column("integrations", "account_label")
    op.drop_column("integrations", "account_identifier")
