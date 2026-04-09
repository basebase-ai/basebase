"""Add workflow model override to organizations.

Revision ID: 131_workflow_model
Revises: 130_org_llm_config
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "131_workflow_model"
down_revision: Union[str, None] = "130_org_llm_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("llm_workflow_model", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "llm_workflow_model")
