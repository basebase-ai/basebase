"""Tests for Slack table formatting (slack_tables module)."""

from connectors.slack_tables import (
    format_markdown_table_inline,
    parse_markdown_table,
)


def test_parse_markdown_table_valid() -> None:
    md = "| A | B |\n| 1 | 2 |\n| 3 | 4 |"
    out = parse_markdown_table(md)
    assert out is not None
    cols, rows = out
    assert cols == ["A", "B"]
    assert rows == [{"A": "1", "B": "2"}, {"A": "3", "B": "4"}]


def test_parse_markdown_table_no_leading_pipes() -> None:
    md = "Name | Email | Phone\n--- | --- | ---\nAlice | alice@co.com | 555\nBob | bob@co.com | 666"
    out = parse_markdown_table(md)
    assert out is not None
    cols, rows = out
    assert cols == ["Name", "Email", "Phone"]
    assert len(rows) == 2
    assert rows[0]["Name"] == "Alice"
    assert rows[1]["Email"] == "bob@co.com"


def test_parse_markdown_table_strips_separator_row() -> None:
    md = "| Name | Amount |\n| --- | --- |\n| Acme | 100 |"
    out = parse_markdown_table(md)
    assert out is not None
    cols, rows = out
    assert cols == ["Name", "Amount"]
    assert rows == [{"Name": "Acme", "Amount": "100"}]


def test_parse_markdown_table_empty_returns_none() -> None:
    assert parse_markdown_table("") is None
    assert parse_markdown_table("\n\n") is None


def test_format_inline_narrow_table_uses_codeblock() -> None:
    md = "| X | Y |\n| a | b |"
    result: str = format_markdown_table_inline(md)
    assert result.startswith("```")
    assert result.endswith("```")
    assert "X" in result and "Y" in result


def test_format_inline_wide_table_uses_list() -> None:
    md = (
        "| Name | Title | Email | Phone |\n"
        "| --- | --- | --- | --- |\n"
        "| Jon Alferness | CEO | jon@basebase.com | +1 (415) 596-7768 |\n"
        "| Teg Grenager | Head of Engineering | teg@basebase.com | +1 (415) 902-8648 |"
    )
    result: str = format_markdown_table_inline(md)
    assert "```" not in result
    assert "*Name:*" in result
    assert "*Email:*" in result
    assert "jon@basebase.com" in result


def test_format_inline_fallback_on_bad_input() -> None:
    result: str = format_markdown_table_inline("not a table at all")
    assert result.startswith("```")
