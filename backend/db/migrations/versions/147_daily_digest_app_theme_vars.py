"""Update Daily Digest app frontend_code to use host theme CSS variables.

Revision ID: 147_daily_digest_theme
Revises: 146_daily_digest_generate_wait
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "147_daily_digest_theme"
down_revision: Union[str, None] = "146_daily_digest_generate_wait"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from services.digest_templates import DAILY_DIGEST_APP_FRONTEND_CODE, DAILY_DIGEST_APP_TITLE

    conn = op.get_bind()
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
