from pathlib import Path


def test_users_self_edit_migration_has_safe_revision_ids_and_write_policies():
    migration_path = Path("backend/db/migrations/versions/137_users_self_edit.py")
    source = migration_path.read_text()

    namespace: dict[str, object] = {}
    exec(compile(source, str(migration_path), "exec"), namespace)

    revision = namespace["revision"]
    down_revision = namespace["down_revision"]

    assert isinstance(revision, str)
    assert len(revision) <= 32
    assert isinstance(down_revision, str)
    assert len(down_revision) <= 32
    assert "CREATE POLICY users_update ON users" in source
    assert "users.id::text" in source
    assert "admin_membership.role = 'admin'" in source
    assert "CREATE POLICY users_delete ON users" in source
    assert "ALTER TABLE users FORCE ROW LEVEL SECURITY" in source
