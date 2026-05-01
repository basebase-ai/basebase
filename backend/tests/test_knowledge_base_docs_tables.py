from agents import tools


def test_knowledge_base_is_sql_accessible() -> None:
    assert "knowledge_base" in tools.ALLOWED_TABLES
    assert "knowledge_base" in tools.WRITABLE_TABLES


def test_temp_data_removed_from_sql_tables() -> None:
    assert "temp_data" not in tools.ALLOWED_TABLES
    assert "temp_data" not in tools.WRITABLE_TABLES
