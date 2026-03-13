"""Add summary_doc_id to meetings table.

Revision ID: 102_summary_doc_id
Revises: 101_add_messenger_tables
Create Date: 2026-03-13

Tracks which Google Drive doc was used for the Gemini summary so the
same doc isn't assigned to multiple meetings.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "102_summary_doc_id"
down_revision: Union[str, None] = "101_messenger_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("summary_doc_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "summary_doc_id")
