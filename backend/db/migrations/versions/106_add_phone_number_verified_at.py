"""Add phone_number_verified_at to users for SMS verification.

Revision ID: 106_add_phone_number_verified_at
Revises: 105_add_sms_whatsapp_consent
Create Date: 2026-03-13

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "106_add_phone_number_verified_at"
down_revision: Union[str, None] = "105_add_sms_whatsapp_consent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("phone_number_verified_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "phone_number_verified_at")
