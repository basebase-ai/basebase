from agents import tools


def test_temp_data_removed_from_writable_tables():
    assert "temp_data" not in tools.WRITABLE_TABLES
    assert "kb_entries" in tools.WRITABLE_TABLES


def test_kb_tables_allowed_for_read_query_table_list():
    assert "kb_entries" in tools.ALLOWED_TABLES
