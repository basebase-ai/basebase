"""Refresh Daily Digest workflow prompt and app code (wait for run on Generate).

Revision ID: 146_daily_digest_generate_wait
Revises: 145_daily_digest_temp
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "146_daily_digest_generate_wait"
down_revision: Union[str, None] = "145_daily_digest_temp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from services.digest_templates import (
        DAILY_DIGEST_APP_FRONTEND_CODE,
        DAILY_DIGEST_APP_TITLE,
        DAILY_DIGEST_WORKFLOW_NAME,
        DAILY_DIGEST_WORKFLOW_PROMPT,
    )

    conn = op.get_bind()
    conn.execute(
        sa.text("""
        UPDATE workflows
        SET prompt = :prompt, updated_at = NOW()
        WHERE name = :name AND archived_at IS NULL
        """),
        {"prompt": DAILY_DIGEST_WORKFLOW_PROMPT, "name": DAILY_DIGEST_WORKFLOW_NAME},
    )
    conn.execute(
        sa.text("""
        UPDATE apps
        SET frontend_code = :frontend_code, updated_at = NOW()
        WHERE title = :title
        """),
        {"frontend_code": DAILY_DIGEST_APP_FRONTEND_CODE, "title": DAILY_DIGEST_APP_TITLE},
    )


def downgrade() -> None:
    pass
