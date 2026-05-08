from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.dialects import postgresql
from sqlalchemy.inspection import inspect

from models.chat_message import ChatMessage
from models.conversation import Conversation


def test_chat_message_conversation_fk_cascades_in_model() -> None:
    fk = next(iter(ChatMessage.__table__.c.conversation_id.foreign_keys))

    assert fk.column.table.name == "conversations"
    assert fk.ondelete == "CASCADE"


def test_conversation_child_relationships_do_not_null_messages_or_notifications() -> None:
    relationships = inspect(Conversation).relationships

    messages = relationships.messages
    assert messages.passive_deletes is True
    assert "delete-orphan" in messages.cascade

    notifications = relationships.notifications
    assert notifications.passive_deletes is True
    assert "delete-orphan" in notifications.cascade


def test_delete_conversation_route_deletes_messages_before_parent() -> None:
    route_source = (Path(__file__).resolve().parents[1] / "api/routes/chat.py").read_text(encoding="utf-8")

    message_delete = "delete(ChatMessage).where(ChatMessage.conversation_id == conv_uuid)"
    parent_delete = "await session.delete(conversation)"
    assert message_delete in route_source
    assert parent_delete in route_source
    assert route_source.index(message_delete) < route_source.index(parent_delete)


def test_chat_message_delete_statement_targets_conversation_id() -> None:
    statement = delete(ChatMessage).where(ChatMessage.conversation_id == "00000000-0000-0000-0000-000000000001")
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "DELETE FROM chat_messages" in compiled
    assert "chat_messages.conversation_id" in compiled
