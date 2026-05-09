import json

from services.chat_message_projections import (
    PromptMessageProjection,
    _PROMPT_MESSAGES_SQL,
    _RECENT_USER_TEXT_SQL,
    _SEMANTIC_WORD_COUNT_SQL,
    _coerce_blocks,
)
from services.conversation_summary import _format_messages


def _normalized(sql: str) -> str:
    return " ".join(sql.lower().split())


def test_prompt_projection_sql_omits_tool_payload_fields() -> None:
    sql = _normalized(_PROMPT_MESSAGES_SQL)

    assert "select *" not in sql
    assert "jsonb_build_object" in sql
    assert "'name'" in sql
    assert "->> 'input'" not in sql
    assert "-> 'input'" not in sql
    assert "->> 'result'" not in sql
    assert "-> 'result'" not in sql


def test_recent_user_text_projection_returns_text_not_full_jsonb() -> None:
    sql = _normalized(_RECENT_USER_TEXT_SQL)

    assert "select *" not in sql
    assert "as content_blocks" not in sql
    assert "string_agg" in sql
    assert "legacy_content" in sql


def test_semantic_count_sql_returns_count_not_jsonb() -> None:
    sql = _normalized(_SEMANTIC_WORD_COUNT_SQL)

    assert "select *" not in sql
    assert "as semantic_words" in sql
    assert "as content_blocks" not in sql


def test_coerce_blocks_accepts_driver_json_strings() -> None:
    blocks = [
        {"type": "text", "text": "hello"},
        "bad",
        {"type": "tool_use", "name": "lookup"},
    ]

    assert _coerce_blocks(json.dumps(blocks)) == [blocks[0], blocks[2]]


def test_summary_formatter_uses_projected_tool_names_only() -> None:
    formatted = _format_messages(
        [
            PromptMessageProjection(
                role="assistant",
                content_blocks=[
                    {"type": "text", "text": "Checking"},
                    {"type": "tool_use", "name": "big_query"},
                ],
            )
        ]
    )

    assert formatted == "ASSISTANT: Checking [Tool call: big_query]"
