from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "migrations"
    / "versions"
    / "140_global_email_scope.py"
)


class TestGlobalEmailActivityScopeMigration:
    def _load_migration(self) -> ModuleType:
        spec = importlib.util.spec_from_file_location(
            "migration_140_global_email_scope", MIGRATION_PATH
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_revision_ids_fit_alembic_limit(self) -> None:
        mig = self._load_migration()

        assert mig.revision == "140_global_email_scope"
        assert mig.down_revision == "139_email_scope"
        assert len(mig.revision) <= 32
        assert isinstance(mig.down_revision, str)
        assert len(mig.down_revision) <= 32

    def test_upgrade_policy_applies_email_scope_before_global_admin_bypass(self) -> None:
        mig = self._load_migration()
        executed_sql: list[str] = []

        with patch.object(
            mig.op, "execute", side_effect=lambda sql: executed_sql.append(str(sql))
        ):
            mig.upgrade()

        combined_sql = "\n".join(executed_sql)

        assert (
            "DROP POLICY IF EXISTS org_and_user_isolation ON activities"
            in combined_sql
        )
        assert "CREATE POLICY org_and_user_isolation ON activities" in combined_sql
        assert "activities.type = 'email'" in combined_sql
        assert "COALESCE(activities.type, '') <> 'email'" in combined_sql
        assert "activities.owner_user_id = COALESCE" in combined_sql
        assert "FROM integrations i" in combined_sql
        assert "i.id = activities.integration_id" in combined_sql
        assert "i.user_id = activities.owner_user_id" in combined_sql
        assert "i.is_active = TRUE" in combined_sql
        assert "i.share_synced_data = TRUE" in combined_sql
        assert "current_app_user_is_global_admin()" in combined_sql
        assert "WITH CHECK" in combined_sql

        email_branch_start = combined_sql.index("activities.type = 'email'")
        non_email_branch_start = combined_sql.index(
            "COALESCE(activities.type, '') <> 'email'"
        )
        global_admin_check = combined_sql.index("current_app_user_is_global_admin()")

        assert email_branch_start < non_email_branch_start
        assert non_email_branch_start < global_admin_check

    def test_downgrade_restores_previous_global_admin_email_bypass(self) -> None:
        mig = self._load_migration()
        executed_sql: list[str] = []

        with patch.object(
            mig.op, "execute", side_effect=lambda sql: executed_sql.append(str(sql))
        ):
            mig.downgrade()

        combined_sql = "\n".join(executed_sql)

        assert "CREATE POLICY org_and_user_isolation ON activities" in combined_sql
        assert "current_app_user_is_global_admin()" in combined_sql
        assert "activities.type = 'email'" in combined_sql
        assert "i.share_synced_data = TRUE" in combined_sql

        global_admin_check = combined_sql.index("current_app_user_is_global_admin()")
        email_branch_start = combined_sql.index("activities.type = 'email'")

        assert global_admin_check < email_branch_start
