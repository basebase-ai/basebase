from uuid import uuid4

from sqlalchemy.dialects import postgresql

from services.conversation_embeddings import _recent_user_message_text_query
from services.conversation_summary import _recent_message_blocks_query


def _compile(query: object) -> str:
    return str(
        query.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_summary_prompt_query_projects_only_role_and_blocks() -> None:
    sql = _compile(_recent_message_blocks_query(uuid4(), 50))

    assert "chat_messages.role" in sql
    assert "chat_messages.content_blocks" in sql
    assert "chat_messages.content," not in sql
    assert "chat_messages.tool_calls" not in sql
    assert "chat_messages.user_id" not in sql


def test_embedding_recent_query_projects_only_text_sources() -> None:
    sql = _compile(_recent_user_message_text_query(uuid4(), 50))

    assert "chat_messages.content" in sql
    assert "chat_messages.content_blocks" in sql
    assert "chat_messages.tool_calls" not in sql
    assert "chat_messages.user_id" not in sql
    assert "chat_messages.organization_id" not in sql
