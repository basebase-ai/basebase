"""Add Meet space fields to meetings table.

Revision ID: 100_meet_space_fields
Revises: 099_meeting_huddle_fields
Create Date: 2026-03-12

Adds columns for direct Google Meet REST API v2 support:
meet_space_name (spaces/abc123), meeting_code, transcript_url.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "100_meet_space_fields"
down_revision: Union[str, None] = "099_meeting_huddle_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("meet_space_name", sa.String(255), nullable=True))
    op.add_column("meetings", sa.Column("meeting_code", sa.String(50), nullable=True))
    op.add_column("meetings", sa.Column("transcript_url", sa.String(500), nullable=True))

    op.create_index("ix_meetings_meet_space_name", "meetings", ["meet_space_name"])


def downgrade() -> None:
    op.drop_index("ix_meetings_meet_space_name", table_name="meetings")

    op.drop_column("meetings", "transcript_url")
    op.drop_column("meetings", "meeting_code")
    op.drop_column("meetings", "meet_space_name")
