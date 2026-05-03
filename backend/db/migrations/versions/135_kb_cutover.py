"""cut over temp_data to knowledge base

Revision ID: 135_kb_cutover
Revises: 134_kb_backfill
Create Date: 2026-05-03
"""
from alembic import op

revision = "135_kb_cutover"
down_revision = "134_kb_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE temp_data RENAME TO temp_data_legacy")
    op.execute("""
    CREATE VIEW temp_data AS
    SELECT
      legacy_temp_data_id AS id,
      organization_id,
      NULL::text AS entity_type,
      NULL::uuid AS entity_id,
      namespace,
      key,
      content AS value,
      metadata,
      created_by_user_id,
      created_at,
      expires_at
    FROM kb_entries
    WHERE legacy_temp_data_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS temp_data")
    op.execute("ALTER TABLE temp_data_legacy RENAME TO temp_data")
