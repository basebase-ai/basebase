"""create knowledge base schema

Revision ID: 133_kb_schema
Revises: 132_wf_llm_model
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "133_kb_schema"
down_revision = "132_wf_llm_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_kind", sa.Text(), nullable=False, server_default="fact"),
        sa.Column("namespace", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_scope", sa.Text(), nullable=True),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="org"),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legacy_temp_data_id", postgresql.UUID(as_uuid=True), nullable=True, unique=True),
    )
    op.create_index("ix_kb_entries_org_ns_created", "kb_entries", ["organization_id", "namespace", "created_at"])

    op.create_table(
        "kb_entry_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kb_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("kb_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kb_entry_id", "source_type", "source_id", "source_ref", name="uq_kb_entry_source"),
    )

    op.create_table(
        "kb_cluster_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "kb_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("kb_cluster_types.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "kb_entry_cluster_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kb_entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("kb_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cluster_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("kb_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=True),
        sa.Column("assigned_by", sa.Text(), nullable=False, server_default="rule"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kb_entry_id", "cluster_id", name="uq_kb_entry_cluster"),
    )

    for table in ["kb_entries", "kb_entry_sources", "kb_cluster_types", "kb_clusters", "kb_entry_cluster_links"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY org_isolation ON {table}
            FOR ALL
            USING (organization_id::text = COALESCE(NULLIF(current_setting('app.current_org_id', true), ''), '00000000-0000-0000-0000-000000000000'))
            WITH CHECK (organization_id::text = COALESCE(NULLIF(current_setting('app.current_org_id', true), ''), '00000000-0000-0000-0000-000000000000'))
            """
        )


def downgrade() -> None:
    for table in ["kb_entry_cluster_links", "kb_clusters", "kb_cluster_types", "kb_entry_sources", "kb_entries"]:
        op.execute(f"DROP POLICY IF EXISTS org_isolation ON {table}")
    op.drop_table("kb_entry_cluster_links")
    op.drop_table("kb_clusters")
    op.drop_table("kb_cluster_types")
    op.drop_table("kb_entry_sources")
    op.drop_index("ix_kb_entries_org_ns_created", table_name="kb_entries")
    op.drop_table("kb_entries")
