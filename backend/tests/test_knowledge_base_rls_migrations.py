from __future__ import annotations

import importlib
from unittest.mock import patch


def _sql_for_upgrade(module_name: str) -> str:
    mig = importlib.import_module(module_name)
    executed_sql: list[str] = []
    with (
        patch.object(mig.op, "execute", side_effect=lambda sql: executed_sql.append(str(sql))),
        patch.object(mig.op, "rename_table", side_effect=lambda old, new: executed_sql.append(f"RENAME TABLE {old} TO {new}")),
        patch.object(mig.op, "create_table", side_effect=lambda name, *args, **kwargs: executed_sql.append(f"CREATE TABLE {name}")),
        patch.object(mig.op, "create_index", side_effect=lambda name, table_name, columns, *args, **kwargs: executed_sql.append(f"CREATE INDEX {name} ON {table_name}({','.join(columns)})")),
    ):
        mig.upgrade()
    return "\n".join(executed_sql)


def test_137_revision_metadata_and_length_guards() -> None:
    mig = importlib.import_module("db.migrations.versions.137_kb_docs")
    assert mig.revision == "137_kb_docs"
    assert mig.down_revision == "58726d896351"
    assert len(mig.revision) <= 32
    assert len(mig.down_revision) <= 32


def test_138_revision_metadata_and_length_guards() -> None:
    mig = importlib.import_module("db.migrations.versions.138_kb_rename")
    assert mig.revision == "138_kb_rename"
    assert mig.down_revision == "137_kb_docs"
    assert len(mig.revision) <= 32
    assert len(mig.down_revision) <= 32


def test_137_upgrade_enables_rls_and_blocks_cross_org_access() -> None:
    sql = _sql_for_upgrade("db.migrations.versions.137_kb_docs")

    assert "ALTER TABLE knowledge_base_docs ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY knowledge_base_docs_org_isolation ON knowledge_base_docs" in sql
    assert "WITH CHECK (organization_id = current_setting('app.current_org_id')::uuid)" in sql

    assert "ALTER TABLE knowledge_base_collections ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY knowledge_base_collections_org_isolation ON knowledge_base_collections" in sql
    assert "WITH CHECK (organization_id = current_setting('app.current_org_id')::uuid)" in sql

    assert "ALTER TABLE knowledge_base_collection_items ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY knowledge_base_collection_items_org_isolation ON knowledge_base_collection_items" in sql
    # Cross-org inserts/selects fail because policy requires an in-org collection owner row.
    assert "FROM knowledge_base_collections c" in sql
    assert "c.organization_id = current_setting('app.current_org_id')::uuid" in sql


def test_138_upgrade_enables_rls_and_org_scoping_on_renamed_table() -> None:
    sql = _sql_for_upgrade("db.migrations.versions.138_kb_rename")

    assert "ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY knowledge_base_org_isolation ON knowledge_base" in sql
    assert "USING (organization_id = current_setting('app.current_org_id')::uuid)" in sql
    assert "WITH CHECK (organization_id = current_setting('app.current_org_id')::uuid)" in sql
