from importlib import import_module


def test_new_migration_revision_lengths():
    modules = [
        import_module("db.migrations.versions.133_kb_schema"),
        import_module("db.migrations.versions.134_kb_backfill"),
        import_module("db.migrations.versions.135_kb_cutover"),
    ]
    for m in modules:
        assert len(m.revision) <= 32
        if isinstance(m.down_revision, str):
            assert len(m.down_revision) <= 32
