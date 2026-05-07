from connectors.slack import markdown_to_mrkdwn


def test_markdown_to_mrkdwn_strips_email_style_blockquote_separators() -> None:
    """Bare ``>`` lines (email reply paragraph separators) must not pass through.

    Slack mrkdwn renders a line containing only ``>`` as a literal ``>`` character
    (since there's no content after the marker). When forwarded/replied email
    content gets sent to Slack, those marker-only lines produced stray ``>``
    glyphs floating between blockquote paragraphs. We strip them so consecutive
    quoted lines collapse into one continuous Slack blockquote.
    """
    sample: str = (
        "> Subject: Deck + next steps\n"
        "> Ash,\n"
        ">\n"
        "> Good conversation today.\n"
        "\n"
        "Deck is attached.\n"
        "\n"
        ">\n"
        "> We are moving quickly on the round.\n"
        "\n"
        "Happy to meet the broader team.\n"
        "\n"
        ">\n"
        "> Looking forward to it.\n"
        ">\n"
        "> Teg"
    )

    text, _blocks = markdown_to_mrkdwn(sample)

    for line in text.split("\n"):
        assert line.strip() != ">", f"stray bare '>' line found: {line!r}"

    assert "> Subject: Deck + next steps\n> Ash,\n> Good conversation today." in text
    assert "> Looking forward to it.\n> Teg" in text


def test_markdown_to_mrkdwn_preserves_blockquote_chars_inside_code_blocks() -> None:
    """``>`` inside fenced code blocks must not be stripped by blockquote normalization."""
    sample: str = (
        "intro\n"
        "\n"
        "```\n"
        ">\n"
        "> some quoted output\n"
        "```\n"
    )

    text, _blocks = markdown_to_mrkdwn(sample)

    assert "```\n>\n> some quoted output\n```" in text


def test_markdown_to_mrkdwn_uses_blocks_for_single_table() -> None:
    text, blocks = markdown_to_mrkdwn(
        """
Summary

| Name | Value |
| --- | --- |
| A | 1 |
| B | 2 |
""".strip()
    )

    assert blocks is not None
    assert len(blocks) == 1
    assert blocks[0]["type"] == "table"
    assert "Table: 2 rows × 2 columns" in text


def test_markdown_to_mrkdwn_falls_back_to_code_blocks_for_multiple_tables() -> None:
    text, blocks = markdown_to_mrkdwn(
        """
First table:
| Name | Value |
| --- | --- |
| A | 1 |

Second table:
| Team | Score |
| --- | --- |
| X | 99 |
""".strip()
    )

    assert blocks is None
    assert text.count("```") >= 4
    assert "Name | Value" in text
    assert "Team | Score" in text
