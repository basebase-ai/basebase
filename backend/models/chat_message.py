"""
ChatMessage model for storing conversation history.

Content blocks follow the Anthropic API pattern:
- {"type": "text", "text": "..."}
- {"type": "tool_use", "id": "...", "name": "...", "input": {...}, "result": {...}, "status": "complete"}
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base

if TYPE_CHECKING:
    from models.conversation import Conversation


def semantic_word_count_from_blocks(blocks: list[dict[str, Any]] | None) -> int:
    """Count words in text-type content blocks only.

    Tool-use, tool-result, and attachment blocks are excluded — they hold
    structured payloads, not user-facing prose, and we don't want a foreach
    over 10k records to count as 10k "words" for summary-staleness gating.
    """
    if not blocks:
        return 0
    total: int = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text_val: str = str(block.get("text") or "").strip()
        if text_val:
            total += len(text_val.split())
    return total


class ChatMessage(Base):
    """ChatMessage model for storing conversation history."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # user_id is nullable for Slack conversations where we don't know the RevTops user
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", onupdate="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'user' or 'assistant'
    source_user_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )  # External sender ID (e.g. Slack user ID)
    source_user_email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # External sender email (e.g. Slack profile email)
    
    # New: Array of content blocks [{type: 'text'|'tool_use', ...}]
    content_blocks: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )

    # Denormalized count of words across text-type content blocks only.
    # Kept in sync by the before_insert / before_update event listener below
    # so that conversation-summary staleness checks can SUM this column instead
    # of streaming every row's content_blocks JSONB back to Python.
    semantic_word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    semantic_word_count_backfilled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Legacy fields - kept for backwards compatibility during migration
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=True
    )

    # Relationships
    conversation: Mapped[Optional["Conversation"]] = relationship(
        "Conversation", back_populates="messages"
    )

    def to_dict(
        self,
        sender_name: str | None = None,
        sender_email: str | None = None,
        sender_avatar_url: str | None = None,
    ) -> dict[str, Any]:
        """Convert to dictionary for API responses.
        
        Args:
            sender_name: Optional sender name (populated by API join for user messages)
            sender_email: Optional sender email (populated by API join for user messages)
            sender_avatar_url: Optional sender avatar URL (populated by API join for user messages)
        """
        # Use content_blocks if available and non-empty, otherwise convert legacy format
        blocks = self.content_blocks
        if not blocks:  # Handles None, empty list, etc.
            blocks = self._legacy_to_blocks()
        
        return {
            "id": str(self.id),
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "role": self.role,
            "content_blocks": blocks,
            "created_at": f"{self.created_at.isoformat()}Z" if self.created_at else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "sender_name": sender_name,
            "sender_email": sender_email or self.source_user_email,
            "sender_avatar_url": sender_avatar_url,
        }
    
    def _legacy_to_blocks(self) -> list[dict[str, Any]]:
        """Convert legacy content + tool_calls to content_blocks format."""
        blocks: list[dict[str, Any]] = []
        
        # Add text content if present
        if self.content and self.content.strip():
            blocks.append({"type": "text", "text": self.content})
        
        # Add tool calls if present
        if self.tool_calls:
            for tc in self.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("input", {}),
                    "result": tc.get("result"),
                    "status": "complete",
                })

        return blocks


def _sync_semantic_word_count(_mapper, _connection, target: ChatMessage) -> None:
    """Recompute ``semantic_word_count`` from ``content_blocks`` on every write.

    Centralized here so all 6+ ChatMessage writer sites stay in sync without
    each having to remember to update the column.
    """
    target.semantic_word_count = semantic_word_count_from_blocks(target.content_blocks)
    target.semantic_word_count_backfilled = True


event.listen(ChatMessage, "before_insert", _sync_semantic_word_count)
event.listen(ChatMessage, "before_update", _sync_semantic_word_count)
