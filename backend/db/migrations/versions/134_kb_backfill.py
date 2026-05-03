"""backfill knowledge base from temp_data

Revision ID: 134_kb_backfill
Revises: 133_kb_schema
Create Date: 2026-05-03
"""
from alembic import op

revision = "134_kb_backfill"
down_revision = "133_kb_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    INSERT INTO kb_entries (
      organization_id, entry_kind, namespace, key, content, metadata,
      created_by_user_id, created_at, expires_at, legacy_temp_data_id, visibility
    )
    SELECT
      organization_id,
      'fact',
      namespace,
      key,
      value,
      metadata,
      created_by_user_id,
      created_at,
      expires_at,
      id,
      'org'
    FROM temp_data
    ON CONFLICT (legacy_temp_data_id) DO NOTHING
    """)

    op.execute("""
    INSERT INTO kb_entry_sources (organization_id, kb_entry_id, source_type, source_id)
    SELECT e.organization_id, e.id, 'temp_data_migration', t.id
    FROM kb_entries e
    JOIN temp_data t ON t.id = e.legacy_temp_data_id
    ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM kb_entry_sources WHERE source_type = 'temp_data_migration'")
    op.execute("DELETE FROM kb_entries WHERE legacy_temp_data_id IS NOT NULL")
