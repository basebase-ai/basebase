"""
Notification endpoints for in-app mention badges and unread indicators.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from api.auth_middleware import AuthContext, get_current_auth
from models.database import get_session
from models.notification import Notification

router = APIRouter()
logger = logging.getLogger(__name__)


class NotificationResponse(BaseModel):
    """Response model for a notification."""
    id: str
    type: str
    conversation_id: str
    actor_user_id: Optional[str]
    actor_name: Optional[str]
    read: bool
    created_at: str


class MarkReadRequest(BaseModel):
    """Request to mark notifications as read."""
    conversation_id: str


@router.get("/", response_model=list[NotificationResponse])
async def list_notifications(
    auth: AuthContext = Depends(get_current_auth),
    unread_only: bool = True,
) -> list[NotificationResponse]:
    """List notifications for the current user (unread by default)."""
    org_id = auth.organization_id_str
    user_id = auth.user_id_str
    if not org_id or not user_id:
        return []

    user_uuid = UUID(user_id)
    org_uuid = UUID(org_id)
    async with get_session(organization_id=org_id, user_id=user_id) as session:
        query = (
            select(Notification)
            .where(Notification.user_id == user_uuid)
            .where(Notification.organization_id == org_uuid)
        )
        if unread_only:
            query = query.where(Notification.read == False)
        query = query.order_by(Notification.created_at.desc()).limit(100)
        result = await session.execute(query)
        notifications = list(result.scalars().all())
        # IMPORTANT: Build response payload inside the active session.
        # get_session() always rolls back during cleanup to reset RLS context, and
        # rollback expires ORM instances. Accessing notification fields after the
        # context exits can trigger DetachedInstanceError / "not bound to a Session".
        response_payload = [
            NotificationResponse(
                id=str(n.id),
                type=n.type,
                conversation_id=str(n.conversation_id),
                actor_user_id=str(n.actor_user_id) if n.actor_user_id else None,
                actor_name=None,
                read=n.read,
                created_at=n.created_at.isoformat() if n.created_at else "",
            )
            for n in notifications
        ]
        logger.debug(
            "Listed %d notifications for user=%s org=%s unread_only=%s",
            len(response_payload),
            user_id,
            org_id,
            unread_only,
        )

    # Resolve actor names (simplified: we don't join User here; actor_name stored at create time)
    # For now return without actor_name from DB - we'd need a join. Plan stores it in WS push.
    return response_payload


@router.post("/read")
async def mark_notifications_read(
    request: MarkReadRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> dict[str, bool]:
    """Mark all notifications for a conversation as read."""
    org_id = auth.organization_id_str
    user_id = auth.user_id_str
    if not org_id or not user_id:
        raise HTTPException(status_code=400, detail="Missing org or user")

    user_uuid = UUID(user_id)
    conv_uuid = UUID(request.conversation_id)
    async with get_session(organization_id=org_id, user_id=user_id) as session:
        await session.execute(
            update(Notification)
            .where(Notification.user_id == user_uuid)
            .where(Notification.conversation_id == conv_uuid)
            .values(read=True)
        )
        await session.commit()

    return {"success": True}
