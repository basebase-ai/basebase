"""Add SMS and WhatsApp consent flags to users for A2P opt-in.

Revision ID: 105_add_sms_whatsapp_consent
Revises: 104_fix_activities_rls_enabled
Create Date: 2026-03-13

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "105_add_sms_whatsapp_consent"
down_revision: Union[str, None] = "104_fix_activities_rls_enabled"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("sms_consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "users",
        sa.Column("whatsapp_consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("users", "whatsapp_consent")
    op.drop_column("users", "sms_consent")
