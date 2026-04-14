from __future__ import annotations

import importlib
from unittest.mock import patch


class TestOrgMembersSelfEditMigration:
    def _load_migration(self):
        return importlib.import_module("db.migrations.versions.133_org_members_self_edit")

    def test_revision_metadata(self) -> None:
        mig = self._load_migration()
        assert mig.revision == "133_org_members_self_edit"
        assert mig.down_revision == "132_wf_llm_model"
        assert len(mig.revision) <= 32
        assert len(mig.down_revision) <= 32

    def test_upgrade_creates_self_or_admin_write_policies(self) -> None:
        mig = self._load_migration()
        executed_sql: list[str] = []

        with patch.object(mig.op, "execute", side_effect=lambda sql: executed_sql.append(str(sql))):
            mig.upgrade()

        combined_sql = "\n".join(executed_sql)

        assert "DROP POLICY IF EXISTS org_isolation ON org_members" in combined_sql
        assert "CREATE POLICY org_members_select ON org_members" in combined_sql
        assert "CREATE POLICY org_members_insert ON org_members" in combined_sql
        assert "CREATE POLICY org_members_update ON org_members" in combined_sql
        assert "CREATE POLICY org_members_delete ON org_members" in combined_sql

        # Non-admin users should only be able to update/delete their own row.
        assert "user_id::text = COALESCE" in combined_sql
        # Org admins can edit any row in the same org.
        assert "admin_membership.role = 'admin'" in combined_sql
        assert "admin_membership.status IN ('active', 'onboarding')" in combined_sql

    def test_downgrade_restores_org_isolation_policy(self) -> None:
        mig = self._load_migration()
        executed_sql: list[str] = []

        with patch.object(mig.op, "execute", side_effect=lambda sql: executed_sql.append(str(sql))):
            mig.downgrade()

        combined_sql = "\n".join(executed_sql)

        assert "DROP POLICY IF EXISTS org_members_select ON org_members" in combined_sql
        assert "DROP POLICY IF EXISTS org_members_insert ON org_members" in combined_sql
        assert "DROP POLICY IF EXISTS org_members_update ON org_members" in combined_sql
        assert "DROP POLICY IF EXISTS org_members_delete ON org_members" in combined_sql
        assert "CREATE POLICY org_isolation ON org_members" in combined_sql
        assert "FOR ALL" in combined_sql
        assert "WITH CHECK" in combined_sql
