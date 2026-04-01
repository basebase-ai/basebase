from uuid import uuid4

from agents.orchestrator import ChatOrchestrator
from models.chat_message import ChatMessage


def test_extract_text_preview_prefers_legacy_content():
    msg = ChatMessage(
        id=uuid4(),
        content="Legacy content text",
        role="assistant",
        content_blocks=[{"type": "text", "text": "Block text"}],
    )

    preview = ChatOrchestrator._extract_text_preview(msg)

    assert preview == "Legacy content text"


def test_extract_text_preview_falls_back_to_text_blocks():
    msg = ChatMessage(
        id=uuid4(),
        content="",
        role="user",
        content_blocks=[
            {"type": "tool_use", "name": "run_sql_query"},
            {"type": "text", "text": "First sentence."},
            {"type": "text", "text": "Second sentence."},
        ],
    )

    preview = ChatOrchestrator._extract_text_preview(msg)

    assert preview == "First sentence. Second sentence."
