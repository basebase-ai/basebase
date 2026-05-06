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
    / "137_users_self_update.py"
)


class TestUsersSelfUpdateMigration:
    def _load_migration(self) -> ModuleType:
        spec = importlib.util.spec_from_file_location(
            "migration_137_users_self_update", MIGRATION_PATH
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_revision_ids_fit_alembic_limit(self) -> None:
        mig = self._load_migration()

        assert len(mig.revision) <= 32
        assert isinstance(mig.down_revision, str)
        assert len(mig.down_revision) <= 32

    def test_upgrade_replaces_broad_users_policy_with_write_scoped_policies(
        self,
    ) -> None:
        mig = self._load_migration()
        executed_sql: list[str] = []

        with patch.object(
            mig.op, "execute", side_effect=lambda sql: executed_sql.append(str(sql))
        ):
            mig.upgrade()

        combined_sql = "\n".join(executed_sql)

        assert (
            "CREATE OR REPLACE FUNCTION current_app_user_is_global_admin()"
            in combined_sql
        )
        assert (
            "CREATE OR REPLACE FUNCTION current_app_user_is_org_admin(target_org_id uuid)"
            in combined_sql
        )
        assert "SECURITY DEFINER" in combined_sql
        assert "DROP POLICY IF EXISTS org_isolation ON users" in combined_sql
        assert "CREATE POLICY users_select ON users" in combined_sql
        assert "CREATE POLICY users_insert ON users" in combined_sql
        assert "CREATE POLICY users_update ON users" in combined_sql
        assert "CREATE POLICY users_delete ON users" in combined_sql
        assert "users.id = COALESCE" in combined_sql
        assert "current_app_user_is_org_admin" in combined_sql
        assert "current_app_user_is_global_admin" in combined_sql
        assert "WITH CHECK" in combined_sql

    def test_downgrade_restores_historical_users_org_isolation_policy(self) -> None:
        mig = self._load_migration()
        executed_sql: list[str] = []

        with patch.object(
            mig.op, "execute", side_effect=lambda sql: executed_sql.append(str(sql))
        ):
            mig.downgrade()

        combined_sql = "\n".join(executed_sql)

        assert "DROP POLICY IF EXISTS users_select ON users" in combined_sql
        assert "DROP POLICY IF EXISTS users_insert ON users" in combined_sql
        assert "DROP POLICY IF EXISTS users_update ON users" in combined_sql
        assert "DROP POLICY IF EXISTS users_delete ON users" in combined_sql
        assert "CREATE POLICY org_isolation ON users" in combined_sql
        assert "FOR ALL" in combined_sql
        assert "DROP FUNCTION IF EXISTS current_app_user_is_org_admin(uuid)" in combined_sql
        assert "DROP FUNCTION IF EXISTS current_app_user_is_global_admin()" in combined_sql
