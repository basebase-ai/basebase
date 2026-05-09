"""
Conversation embeddings for semantic workstream clustering.

Builds a single vector per conversation from title + summary + recent user messages,
stored in conversations.embedding. Staleness is tracked via embedding_message_count.

Snapshot-stale marking and workstreams_stale broadcast are done by
conversation_post_completion.run_post_completion() after this returns.
"""

import logging
from models.conversation import Conversation
from models.database import get_session
from sqlalchemy import update

from services.embeddings import get_embedding_service
from services.chat_message_projections import fetch_recent_user_text_projections

logger = logging.getLogger(__name__)

_STALENESS_THRESHOLD = 2
_MAX_RECENT_CHARS = 12_000
_MAX_MESSAGES_FOR_RECENT = 50


def build_embedding_text(
    title: str | None,
    summary_overall: str | None,
    recent_user_texts: list[str],
) -> str:
    """Build a single string for embedding: title + summary + recent user messages."""
    sections: list[str] = []
    if title and title.strip():
        sections.append(f"Title: {title.strip()}")
    if summary_overall and summary_overall.strip():
        sections.append(f"Summary: {summary_overall.strip()}")
    combined_recent = "\n".join(recent_user_texts).strip()
    if combined_recent:
        if len(combined_recent) > _MAX_RECENT_CHARS:
            combined_recent = combined_recent[-_MAX_RECENT_CHARS:]
        sections.append(f"Recent: {combined_recent}")
    text = "\n\n".join(sections).strip()
    return text if text else "Untitled conversation"


async def update_conversation_embedding(
    conversation_id: str,
    organization_id: str,
) -> bool:
    """
    Generate or refresh the conversation embedding if stale.

    Staleness: message_count - embedding_message_count >= _STALENESS_THRESHOLD.
    Builds text from title + plain-text summary + last N user messages, then embeds.

    Returns True if the embedding was updated, False if skipped or on failure.
    """
    try:
        conversation_title: str | None = None
        current_count = 0
        summary_text: str | None = None
        recent_texts: list[str] = []

        async with get_session(organization_id=organization_id) as session:
            conv = await session.get(Conversation, conversation_id)
            if not conv:
                logger.warning("Embedding: conversation %s not found", conversation_id)
                return False

            conversation_title = conv.title
            current_count = conv.message_count
            emb_count: int = conv.embedding_message_count
            if (current_count - emb_count) < _STALENESS_THRESHOLD:
                logger.debug(
                    "Embedding skipped for conversation %s (message_count=%d, embedding_message_count=%d, threshold=%d)",
                    conversation_id,
                    current_count,
                    emb_count,
                    _STALENESS_THRESHOLD,
                )
                return False

            summary_text = (conv.summary or "").strip() or None

            user_messages = await fetch_recent_user_text_projections(
                session,
                conv.id,
                limit=_MAX_MESSAGES_FOR_RECENT,
            )
            total_chars = 0
            for msg in reversed(user_messages):
                text = msg.block_text
                if not text and msg.legacy_content:
                    text = msg.legacy_content
                if text:
                    recent_texts.append(text)
                    total_chars += len(text)
                    if total_chars >= _MAX_RECENT_CHARS:
                        break

        embedding_text = build_embedding_text(
            title=conversation_title,
            summary_overall=summary_text,
            recent_user_texts=recent_texts,
        )
        if not embedding_text or embedding_text == "Untitled conversation":
            embedding_text = f"Conversation {conversation_id}"

        service = get_embedding_service()
        vector: list[float] = await service.generate_embedding(embedding_text)

        async with get_session(organization_id=organization_id) as session:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    embedding=vector,
                    embedding_message_count=current_count,
                )
            )
            await session.commit()

        logger.info(
            "Embedding updated for conversation %s (message_count=%d, text_chars=%d, recent_messages=%d)",
            conversation_id,
            current_count,
            len(embedding_text),
            len(recent_texts),
        )
        return True

    except Exception:
        logger.exception(
            "Failed to update embedding for conversation %s in org %s",
            conversation_id,
            organization_id,
        )
        return False
