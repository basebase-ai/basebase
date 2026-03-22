"""
Notification service for mention alerts and in-app badges.
"""
from __future__ import annotations

import logging
from uuid import UUID
from typing import Any

from sqlalchemy import select

from models.database import get_session
from models.notification import Notification
from models.user import User

logger = logging.getLogger(__name__)


async def create_mention_notifications(
    conversation_id: str,
    message_id: str,
    actor_user_id: str,
    organization_id: str,
    mentions: list[dict[str, Any]] | None,
    participant_user_ids: list[str],
) -> None:
    """
    Create notification records for mentioned users and push via WebSocket.

    - If mentions contains {"type": "user", "user_id": "..."}: create for each mentioned user.
    - Else (human-mode continuation): create for all participants except the sender.
    """
    mentions = mentions or []
    user_mentions = [m for m in mentions if m.get("type") == "user" and m.get("user_id")]

    if user_mentions:
        target_ids: list[str] = list({m["user_id"] for m in user_mentions})
    else:
        target_ids = [uid for uid in participant_user_ids if uid != actor_user_id]

    if not target_ids:
        return

    org_uuid = UUID(organization_id) if organization_id else None
    conv_uuid = UUID(conversation_id)
    actor_uuid = UUID(actor_user_id)
    msg_uuid = UUID(message_id) if message_id else None

    async with get_session(organization_id=organization_id) as session:
        actor_row = await session.execute(select(User.name).where(User.id == actor_uuid))
        actor_name: str | None = actor_row.scalar_one_or_none()
        created: list[Notification] = []
        for uid in target_ids:
            if uid == actor_user_id:
                continue
            n = Notification(
                user_id=UUID(uid),
                organization_id=org_uuid,
                type="mention",
                conversation_id=conv_uuid,
                message_id=msg_uuid,
                actor_user_id=actor_uuid,
                read=False,
            )
            session.add(n)
            created.append(n)
        await session.commit()

    from api.websockets import conversation_broadcaster

    for n in created:
        notification_data = {
            "id": str(n.id),
            "type": n.type,
            "conversation_id": str(n.conversation_id),
            "actor_user_id": str(n.actor_user_id),
            "actor_name": actor_name,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        await conversation_broadcaster.broadcast_to_users(
            user_ids=[str(n.user_id)],
            event_type="notification",
            data={"notification": notification_data},
            exclude_user_id=None,
        )
