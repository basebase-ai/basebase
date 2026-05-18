"""Add models registry and llm_usage tables for token-based credits.

Revision ID: 144_add_models_llm_usage
Revises: 143_int_acct_id
Create Date: 2026-05-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "144_add_models_llm_usage"
down_revision: Union[str, None] = "143_int_acct_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (model_name, provider, input_$/M, output_$/M, is_enabled, supports_images, supports_tools, max_context)
# Pricing sourced May 2026; DeepSeek uses discounted launch pricing.
_SEED_MODELS: tuple[tuple[str, str, str, str, bool, bool, bool, int | None], ...] = (
    ("claude-opus-4-6", "anthropic", "5.000000", "25.000000", True, True, True, 1000000),
    ("claude-haiku-4-5-20251001", "anthropic", "1.000000", "5.000000", True, True, True, 200000),
    ("MiniMax-M2.7", "minimax", "0.300000", "1.200000", True, False, True, 205000),
    ("MiniMax-M2.7-highspeed", "minimax", "0.600000", "2.400000", True, False, True, 205000),
    ("gpt-5.5", "openai", "5.000000", "30.000000", True, True, True, 128000),
    ("gpt-5.5-mini", "openai", "0.750000", "4.500000", True, True, True, 400000),
    ("gpt-5", "openai", "1.250000", "10.000000", True, True, True, 128000),
    ("gemini-2.5-pro", "gemini", "1.250000", "10.000000", True, True, True, 1000000),
    ("gemini-2.5-flash", "gemini", "0.300000", "2.500000", True, True, True, 1000000),
    ("qwen3.6-plus", "qwen", "0.280000", "1.650000", True, False, True, 1000000),
    ("qwen3-30b-a3b-instruct-2507", "qwen", "0.080000", "0.280000", True, False, True, 131000),
    ("deepseek-v4-pro", "deepseek", "0.440000", "0.870000", True, False, True, 1000000),
)

_ORG_MATCH_SQL: str = """
    organization_id::text = COALESCE(
        NULLIF(current_setting('app.current_org_id', true), ''),
        '00000000-0000-0000-0000-000000000000'
    )
"""


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("input_cost_per_m", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_cost_per_m", sa.Numeric(12, 6), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("supports_images", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("max_context_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_models_model_name", "models", ["model_name"], unique=True)

    op.create_table(
        "llm_usage",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL", onupdate="CASCADE"),
            nullable=True,
        ),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("credits_charged", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_llm_usage_organization_id", "llm_usage", ["organization_id"])
    op.create_index(
        "ix_llm_usage_org_created_at",
        "llm_usage",
        ["organization_id", "created_at"],
    )

    models_table = sa.table(
        "models",
        sa.column("model_name", sa.String),
        sa.column("provider", sa.String),
        sa.column("input_cost_per_m", sa.Numeric),
        sa.column("output_cost_per_m", sa.Numeric),
        sa.column("is_enabled", sa.Boolean),
        sa.column("supports_images", sa.Boolean),
        sa.column("supports_tools", sa.Boolean),
        sa.column("max_context_tokens", sa.Integer),
    )
    op.bulk_insert(
        models_table,
        [
            {
                "model_name": name,
                "provider": provider,
                "input_cost_per_m": inp,
                "output_cost_per_m": out,
                "is_enabled": enabled,
                "supports_images": images,
                "supports_tools": tools,
                "max_context_tokens": ctx,
            }
            for name, provider, inp, out, enabled, images, tools, ctx in _SEED_MODELS
        ],
    )

    op.execute("ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_usage FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS org_isolation ON llm_usage")
    op.execute(
        f"""
        CREATE POLICY org_isolation ON llm_usage
        FOR ALL
        USING (
            {_ORG_MATCH_SQL.strip()}
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS org_isolation ON llm_usage")
    op.drop_index("ix_llm_usage_org_created_at", table_name="llm_usage")
    op.drop_index("ix_llm_usage_organization_id", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_models_model_name", table_name="models")
    op.drop_table("models")
