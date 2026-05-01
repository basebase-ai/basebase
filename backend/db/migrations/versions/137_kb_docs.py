"""Rename temp_data to knowledge_base_docs and add doc collections.

Revision ID: 137_kb_docs
Revises: 58726d896351
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "137_kb_docs"
down_revision = "58726d896351"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE temp_data DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS temp_data_org_isolation ON temp_data")

    op.rename_table("temp_data", "knowledge_base_docs")
    op.execute(
        "ALTER INDEX IF EXISTS ix_temp_data_ns_entity RENAME TO ix_kb_docs_ns_entity"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_temp_data_entity RENAME TO ix_kb_docs_entity"
    )
    op.execute(
        "ALTER INDEX IF EXISTS ix_temp_data_expires RENAME TO ix_kb_docs_expires"
    )

    op.execute("ALTER TABLE knowledge_base_docs ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY knowledge_base_docs_org_isolation ON knowledge_base_docs
        FOR ALL
        USING (organization_id = current_setting('app.current_org_id')::uuid)
        WITH CHECK (organization_id = current_setting('app.current_org_id')::uuid)
        """
    )

    op.create_table(
        "knowledge_base_collections",
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
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "name", name="uq_kb_collections_org_name"),
    )
    op.create_index(
        "ix_kb_collections_org_name",
        "knowledge_base_collections",
        ["organization_id", "name"],
    )

    op.create_table(
        "knowledge_base_collection_items",
        sa.Column(
            "collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_base_collections.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_base_docs.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_kb_collection_items_doc",
        "knowledge_base_collection_items",
        ["doc_id"],
    )

    op.execute("ALTER TABLE knowledge_base_collections ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY knowledge_base_collections_org_isolation ON knowledge_base_collections
        FOR ALL
        USING (organization_id = current_setting('app.current_org_id')::uuid)
        WITH CHECK (organization_id = current_setting('app.current_org_id')::uuid)
        """
    )

    op.execute("ALTER TABLE knowledge_base_collection_items ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY knowledge_base_collection_items_org_isolation ON knowledge_base_collection_items
        FOR ALL
        USING (
            EXISTS (
                SELECT 1
                FROM knowledge_base_collections c
                WHERE c.id = collection_id
                  AND c.organization_id = current_setting('app.current_org_id')::uuid
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM knowledge_base_collections c
                WHERE c.id = collection_id
                  AND c.organization_id = current_setting('app.current_org_id')::uuid
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS knowledge_base_collection_items_org_isolation ON knowledge_base_collection_items"
    )
    op.execute(
        "DROP POLICY IF EXISTS knowledge_base_collections_org_isolation ON knowledge_base_collections"
    )
    op.execute(
        "DROP POLICY IF EXISTS knowledge_base_docs_org_isolation ON knowledge_base_docs"
    )

    op.drop_index("ix_kb_collection_items_doc", table_name="knowledge_base_collection_items")
    op.drop_table("knowledge_base_collection_items")

    op.drop_index("ix_kb_collections_org_name", table_name="knowledge_base_collections")
    op.drop_table("knowledge_base_collections")

    op.execute("ALTER TABLE knowledge_base_docs DISABLE ROW LEVEL SECURITY")
    op.rename_table("knowledge_base_docs", "temp_data")

    op.execute("ALTER INDEX IF EXISTS ix_kb_docs_ns_entity RENAME TO ix_temp_data_ns_entity")
    op.execute("ALTER INDEX IF EXISTS ix_kb_docs_entity RENAME TO ix_temp_data_entity")
    op.execute("ALTER INDEX IF EXISTS ix_kb_docs_expires RENAME TO ix_temp_data_expires")

    op.execute("ALTER TABLE temp_data ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY temp_data_org_isolation ON temp_data
        FOR ALL
        USING (organization_id = current_setting('app.current_org_id')::uuid)
        """
    )
