"""Rename knowledge_base_docs to knowledge_base.

Revision ID: 138_kb_rename
Revises: 137_kb_docs
Create Date: 2026-04-30
"""

from alembic import op


revision = "138_kb_rename"
down_revision = "137_kb_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_base_docs DISABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS knowledge_base_docs_org_isolation ON knowledge_base_docs"
    )

    op.rename_table("knowledge_base_docs", "knowledge_base")
    op.execute("ALTER INDEX IF EXISTS ix_kb_docs_ns_entity RENAME TO ix_kb_ns_entity")
    op.execute("ALTER INDEX IF EXISTS ix_kb_docs_entity RENAME TO ix_kb_entity")
    op.execute("ALTER INDEX IF EXISTS ix_kb_docs_expires RENAME TO ix_kb_expires")

    op.execute("ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY knowledge_base_org_isolation ON knowledge_base
        FOR ALL
        USING (organization_id = current_setting('app.current_org_id')::uuid)
        WITH CHECK (organization_id = current_setting('app.current_org_id')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS knowledge_base_org_isolation ON knowledge_base")
    op.execute("ALTER TABLE knowledge_base DISABLE ROW LEVEL SECURITY")

    op.rename_table("knowledge_base", "knowledge_base_docs")
    op.execute("ALTER INDEX IF EXISTS ix_kb_ns_entity RENAME TO ix_kb_docs_ns_entity")
    op.execute("ALTER INDEX IF EXISTS ix_kb_entity RENAME TO ix_kb_docs_entity")
    op.execute("ALTER INDEX IF EXISTS ix_kb_expires RENAME TO ix_kb_docs_expires")

    op.execute("ALTER TABLE knowledge_base_docs ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY knowledge_base_docs_org_isolation ON knowledge_base_docs
        FOR ALL
        USING (organization_id = current_setting('app.current_org_id')::uuid)
        WITH CHECK (organization_id = current_setting('app.current_org_id')::uuid)
        """
    )
