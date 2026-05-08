"""
WebSocket handler for chat interface.

Responsibilities:
- Accept WebSocket connections
- Manage subscriptions to background agent tasks
- Send active task state on connect for catchup
- Handle CRM operation approvals
- Stream task updates to subscribed clients
- Broadcast sync progress events to clients

Architecture:
- WebSocket is a subscription mechanism, not the driver of agent processes
- Agent tasks run as background asyncio tasks managed by TaskManager
- Tasks persist to database and continue even if client disconnects
- Clients can reconnect and catch up on missed updates
"""

import json
import logging
import asyncio
import contextlib
import time
from collections import defaultdict
from typing import Dict, Optional, Set
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


FANOUT_SEND_TIMEOUT_SECONDS = 1.5


async def _send_with_timeout(websocket: WebSocket, message: str) -> bool:
    """Send a message to one websocket with timeout protection."""
    try:
        await asyncio.wait_for(
            websocket.send_text(message),
            timeout=FANOUT_SEND_TIMEOUT_SECONDS,
        )
        return True
    except Exception:
        return False


async def _fanout_message(websockets: Set[WebSocket], message: str) -> Set[WebSocket]:
    """Fan out a message concurrently and return websockets that failed."""
    if not websockets:
        return set()

    send_tasks = [
        asyncio.create_task(_send_with_timeout(ws, message))
        for ws in websockets
    ]
    results = await asyncio.gather(*send_tasks, return_exceptions=True)

    dead: Set[WebSocket] = set()
    for ws, result in zip(websockets, results, strict=False):
        if isinstance(result, Exception) or result is not True:
            dead.add(ws)

    return dead


# =============================================================================
# Sync Progress Broadcasting
# =============================================================================

class SyncProgressBroadcaster:
    """
    Manages WebSocket connections for broadcasting sync progress events.
    
    Clients are grouped by organization_id so we only send events to
    users who belong to that organization.
    """
    
    def __init__(self) -> None:
        # org_id -> set of websockets
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
    
    def register(self, organization_id: str, websocket: WebSocket) -> None:
        """Register a websocket for sync progress updates."""
        self._connections[organization_id].add(websocket)
    
    def unregister(self, organization_id: str, websocket: WebSocket) -> None:
        """Unregister a websocket."""
        self._connections[organization_id].discard(websocket)
        if not self._connections[organization_id]:
            del self._connections[organization_id]
    
    async def broadcast(
        self,
        organization_id: str,
        event_type: str,
        data: dict,
    ) -> None:
        """Broadcast an event to all connected clients for an organization."""
        websockets = self._connections.get(organization_id, set())
        if not websockets:
            return
        
        message = json.dumps({
            "type": event_type,
            **data,
        })
        
        # Send to all concurrently so one stalled client can't block fanout.
        dead = await _fanout_message(websockets, message)
        if dead:
            logger.debug(
                "sync fanout removed %s stale websocket(s) for organization %s",
                len(dead),
                organization_id,
            )
        
        # Clean up dead connections
        for ws in dead:
            self._connections[organization_id].discard(ws)


# Global broadcaster instance
sync_broadcaster = SyncProgressBroadcaster()


async def broadcast_sync_progress(
    organization_id: str,
    provider: str,
    count: int,
    status: str = "syncing",
    step: Optional[str] = None,
) -> None:
    """
    Broadcast sync progress to all connected clients for an organization.
    
    Called from connectors during sync to update the UI in real-time.
    
    Args:
        organization_id: The organization UUID
        provider: The provider name (e.g., "google_calendar")
        count: Current count of synced items
        status: "syncing" or "completed"
        step: Current sync phase (e.g., "accounts", "deals", "contacts", "activities")
    """
    data: dict[str, str | int] = {
        "provider": provider,
        "count": count,
        "status": status,
    }
    if step is not None:
        data["step"] = step
    await sync_broadcaster.broadcast(
        organization_id=organization_id,
        event_type="sync_progress",
        data=data,
    )


async def broadcast_tool_progress(
    organization_id: str,
    conversation_id: str,
    tool_id: str,
    tool_name: str,
    result: dict,
    status: str = "running",
) -> None:
    """
    Broadcast tool progress to all connected clients for an organization.
    
    Called from tools during execution to update the UI with progress.
    
    Args:
        organization_id: The organization UUID
        conversation_id: The conversation containing the tool call
        tool_id: The tool_use block ID
        tool_name: Name of the tool (e.g., "write_on_connector")
        result: Progress result dict
        status: "running" for progress, "complete" when done
    """
    await sync_broadcaster.broadcast(
        organization_id=organization_id,
        event_type="tool_progress",
        data={
            "conversation_id": conversation_id,
            "tool_id": tool_id,
            "tool_name": tool_name,
            "result": result,
            "status": status,
        },
    )


# =============================================================================
# Conversation Message Broadcasting (Multi-User)
# =============================================================================

class ConversationBroadcaster:
    """
    Manages WebSocket connections for broadcasting conversation messages.
    
    Tracks connections by user_id so we can send messages to specific
    participants in a shared conversation.
    """
    
    def __init__(self) -> None:
        # user_id -> set of websockets (a user can have multiple tabs open)
        self._user_connections: Dict[str, Set[WebSocket]] = defaultdict(set)
    
    def register(self, user_id: str, websocket: WebSocket) -> None:
        """Register a websocket for a user."""
        self._user_connections[user_id].add(websocket)
    
    def unregister(self, user_id: str, websocket: WebSocket) -> None:
        """Unregister a websocket."""
        self._user_connections[user_id].discard(websocket)
        if not self._user_connections[user_id]:
            del self._user_connections[user_id]

    def get_user_websockets(self, user_id: str) -> Set[WebSocket]:
        """Return a copy of the set of websockets for a user (for subscription use)."""
        return self._user_connections.get(user_id, set()).copy()

    async def broadcast_to_users(
        self,
        user_ids: list[str],
        event_type: str,
        data: dict,
        exclude_user_id: Optional[str] = None,
    ) -> None:
        """Broadcast an event to specific users (excluding sender)."""
        message = json.dumps({
            "type": event_type,
            **data,
        })
        
        dead_connections: list[tuple[str, WebSocket]] = []
        for user_id in user_ids:
            if exclude_user_id and user_id == exclude_user_id:
                continue
            
            websockets = self._user_connections.get(user_id, set())
            dead_for_user = await _fanout_message(websockets, message)
            dead_connections.extend((user_id, ws) for ws in dead_for_user)
            if dead_for_user:
                logger.debug(
                    "conversation fanout removed %s stale websocket(s) for user %s",
                    len(dead_for_user),
                    user_id,
                )
        
        # Clean up dead connections
        for user_id, ws in dead_connections:
            self._user_connections[user_id].discard(ws)


# Global conversation broadcaster instance
conversation_broadcaster = ConversationBroadcaster()


async def broadcast_conversation_message(
    conversation_id: str,
    scope: str,
    participant_user_ids: list[str],
    message_data: dict,
    sender_user_id: Optional[str] = None,
) -> None:
    """
    Broadcast a new message to all conversation participants.
    
    Only broadcasts for shared conversations. Private conversations
    don't need broadcast since there's only one user.
    
    Args:
        conversation_id: The conversation UUID
        scope: "private" or "shared"
        participant_user_ids: List of user UUIDs who are in the conversation
        message_data: The message dict (from ChatMessage.to_dict())
        sender_user_id: The user who sent the message (excluded from broadcast)
    """
    if scope == "private":
        return  # No broadcast needed for private conversations
    
    if not participant_user_ids:
        return
    
    await conversation_broadcaster.broadcast_to_users(
        user_ids=participant_user_ids,
        event_type="new_message",
        data={
            "conversation_id": conversation_id,
            "message": message_data,
            "sender_user_id": sender_user_id,
        },
        exclude_user_id=sender_user_id,
    )


# =============================================================================
# Chat WebSocket Handler
# =============================================================================

from models.conversation import Conversation
from models.database import get_session
from config import get_redis_connection_kwargs, settings
from models.user import User
from sqlalchemy import select


def _generate_title(message: str) -> str:
    """Generate a conversation title from the first message."""
    cleaned = message.strip().replace("\n", " ")
    words = cleaned.split()[:8]
    title = " ".join(words)
    if len(title) > 40:
        title = title[:40]
    if len(cleaned) > len(title):
        title += "..."
    return title or "New Chat"

logger = logging.getLogger(__name__)


def _warn_org_required_rejection(
    *,
    user_id: str,
    message_type: str,
    conversation_id: str | None = None,
) -> None:
    """Emit a warning when a websocket message is rejected due to missing org context."""
    logger.warning(
        "[WebSocket] Rejected %s message: no organization context (user_id=%s, conversation_id=%s)",
        message_type,
        user_id,
        conversation_id or "none",
    )


WORKFLOW_TOOL_STATUS_BASE_INTERVAL_SECONDS: float = 1.5
WORKFLOW_TOOL_STATUS_MAX_BACKOFF_SECONDS: float = 30.0
WORKFLOW_TOOL_STATUS_SANITY_TIMEOUT_SECONDS: float = 90.0


def _workflow_tool_progress_channel(organization_id: str) -> str:
    """Redis pub/sub channel for tool progress produced by workflow workers."""
    return f"workflow_tool_progress:{organization_id}"


def _normalize_tool_progress_payload(raw_payload: object) -> dict | None:
    """Validate and normalize a Redis tool-progress payload before websocket fanout."""
    try:
        payload = json.loads(raw_payload if isinstance(raw_payload, str) else raw_payload.decode("utf-8"))
    except (AttributeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("[WebSocket] Ignoring malformed workflow tool progress payload: %s", exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("[WebSocket] Ignoring non-object workflow tool progress payload: %r", payload)
        return None

    conversation_id = str(payload.get("conversation_id") or "").strip()
    tool_id = str(payload.get("tool_id") or "").strip()
    if not conversation_id or not tool_id:
        logger.warning("[WebSocket] Ignoring workflow tool progress payload missing IDs: %s", payload)
        return None

    result = payload.get("result")
    return {
        "type": "tool_progress",
        "conversation_id": conversation_id,
        "tool_id": tool_id,
        "tool_name": str(payload.get("tool_name") or "unknown"),
        "result": result if isinstance(result, dict) else {},
        "status": str(payload.get("status") or "running"),
    }


async def _stream_workflow_tool_status(websocket: WebSocket, organization_id: str) -> None:
    """Subscribe to worker-published workflow tool progress and push deltas."""
    last_sent: dict[str, str] = {}
    consecutive_errors: int = 0
    logger.info("[WebSocket] Starting Redis workflow tool status stream for org %s", organization_id)

    while True:
        redis_client: aioredis.Redis | None = None
        pubsub: aioredis.client.PubSub | None = None
        try:
            redis_client = aioredis.from_url(
                settings.REDIS_URL,
                **get_redis_connection_kwargs(decode_responses=True),
            )
            pubsub = redis_client.pubsub()
            channel = _workflow_tool_progress_channel(organization_id)
            await pubsub.subscribe(channel)
            consecutive_errors = 0
            last_heard_at = time.monotonic()
            logger.debug("[WebSocket] Subscribed to workflow tool progress channel %s", channel)

            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=WORKFLOW_TOOL_STATUS_BASE_INTERVAL_SECONDS,
                )
                now = time.monotonic()
                if message is None:
                    if now - last_heard_at >= WORKFLOW_TOOL_STATUS_SANITY_TIMEOUT_SECONDS:
                        raise TimeoutError(
                            "No Redis workflow tool progress messages received within sanity timeout"
                        )
                    continue

                last_heard_at = now
                update = _normalize_tool_progress_payload(message.get("data"))
                if update is None:
                    continue

                key: str = f"{update['conversation_id']}:{update['tool_id']}"
                signature: str = json.dumps(
                    {"status": update.get("status"), "result": update.get("result") or {}},
                    sort_keys=True,
                    default=str,
                )
                if last_sent.get(key) == signature:
                    continue

                await websocket.send_text(json.dumps(update))
                last_sent[key] = signature
                logger.debug(
                    "[WebSocket] Sent worker-published workflow tool status: conv=%s tool=%s status=%s",
                    update["conversation_id"],
                    update["tool_id"],
                    update.get("status"),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors <= 3:
                logger.warning("[WebSocket] Workflow status Redis stream error: %s", exc)
            elif consecutive_errors == 4:
                logger.warning(
                    "[WebSocket] Workflow status Redis stream error (suppressing further): %s", exc
                )
        finally:
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    await pubsub.unsubscribe(_workflow_tool_progress_channel(organization_id))
                with contextlib.suppress(Exception):
                    await pubsub.close()
            if redis_client is not None:
                with contextlib.suppress(Exception):
                    await redis_client.aclose()

        sleep_time: float = min(
            WORKFLOW_TOOL_STATUS_BASE_INTERVAL_SECONDS * (2 ** consecutive_errors),
            WORKFLOW_TOOL_STATUS_MAX_BACKOFF_SECONDS,
        )
        await asyncio.sleep(sleep_time)


async def _execute_tool_approval(
    operation_id: str,
    approved: bool,
    options: dict,
    organization_id: str | None,
    user_id: str,
) -> dict:
    """
    Execute or cancel a pending tool approval.
    
    Routes to the appropriate execution function based on the tool type.
    
    Args:
        operation_id: The pending operation ID
        approved: Whether the user approved the operation
        options: Tool-specific options (e.g., skip_duplicates for CRM)
        organization_id: Organization UUID
        user_id: User UUID
        
    Returns:
        Execution result dict with status, message, etc.
    """
    from models.pending_operation import PendingOperation, CrmOperation
    from models.database import get_session
    from agents.tools import (
        cancel_crm_operation,
        execute_crm_operation,
        get_pending_operation,
        remove_pending_operation,
        execute_send_email_from,
        execute_send_slack,
        execute_save_memory,
        execute_keep_notes,
        execute_create_cloud_file,
        execute_edit_cloud_file,
    )
    
    # First check if this is in our in-memory pending operations store
    pending_op = get_pending_operation(operation_id)
    
    if pending_op:
        tool_name = pending_op["tool_name"]
        params = pending_op["params"]
        op_org_id = pending_op["organization_id"]
        op_user_id = pending_op["user_id"]
        
        # Remove from pending store
        remove_pending_operation(operation_id)
        
        if not approved:
            return {
                "status": "canceled",
                "message": "Operation canceled by user",
                "tool_name": tool_name,
            }
        
        # Execute based on tool type
        if tool_name == "send_email_from":
            result = await execute_send_email_from(params, op_org_id, op_user_id)
            result["tool_name"] = tool_name
            return result
        elif tool_name == "send_slack":
            result = await execute_send_slack(params, op_org_id)
            result["tool_name"] = tool_name
            return result
        elif tool_name == "manage_memory":
            result = await execute_save_memory(params, op_org_id, op_user_id)
            result["tool_name"] = tool_name
            return result
        elif tool_name == "keep_notes":
            workflow_id = params.get("workflow_id", "")
            run_id = params.get("run_id")
            result = await execute_keep_notes(params, op_org_id, op_user_id, workflow_id, run_id)
            result["tool_name"] = tool_name
            return result
        elif tool_name == "create_cloud_file":
            result = await execute_create_cloud_file(params, op_org_id, op_user_id)
            result["tool_name"] = tool_name
            return result
        elif tool_name == "edit_cloud_file":
            result = await execute_edit_cloud_file(params, op_org_id, op_user_id)
            result["tool_name"] = tool_name
            return result






        else:
            return {
                "status": "failed",
                "error": f"Unknown tool type: {tool_name}",
                "tool_name": tool_name,
            }
    
    # Check if this is a CRM operation (stored in database)
    async with get_session() as session:
        crm_op = await session.get(CrmOperation, UUID(operation_id))
        
        if crm_op:
            # It's a CRM operation
            skip_duplicates = options.get("skip_duplicates", True)
            if approved:
                result = await execute_crm_operation(operation_id, skip_duplicates)
            else:
                result = await cancel_crm_operation(operation_id)
            result["tool_name"] = "write_to_system_of_record"
            return result
    
    # Operation not found
    return {
        "status": "failed",
        "error": f"Pending operation {operation_id} not found. It may have expired or already been processed.",
        "tool_name": "unknown",
    }


async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for chat communication.
    
    SECURITY: Authentication is done via JWT token passed as query parameter.
    The token is verified before accepting the connection.

    Protocol (client -> server):
    - {"type": "send_message", "message": "...", "conversation_id": "..."}
    - {"type": "typing", "conversation_id": "..."}  # shared chats; throttled client-side
    - {"type": "subscribe", "task_id": "...", "since_index": 0}
    - {"type": "cancel", "task_id": "..."}
    - {"type": "crm_approval", "operation_id": "...", "approved": true/false}

    Protocol (server -> client):
    - {"type": "active_tasks", "tasks": [...]} - sent on connect
    - {"type": "task_started", "task_id": "...", "conversation_id": "..."}
    - {"type": "task_chunk", "task_id": "...", "chunk": {...}}
    - {"type": "task_complete", "task_id": "...", "status": "..."}
    - {"type": "catchup", "task_id": "...", "chunks": [...]}
    - {"type": "crm_approval_result", ...}
    - {"type": "user_typing", "conversation_id": "...", "user_id": "...", "user_name": "..."}

    Args:
        websocket: The WebSocket connection
    """
    from agents.tools import (
        cancel_crm_operation,
        execute_crm_operation,
        update_tool_call_result,
    )
    from services.credits import can_use_credits
    from services.task_manager import task_manager

    # Verify JWT token BEFORE accepting the connection
    from api.auth_middleware import verify_websocket_token
    
    try:
        auth = await verify_websocket_token(websocket)
    except Exception as e:
        # verify_websocket_token already closed the WebSocket with appropriate code
        logger.warning(f"WebSocket auth failed: {e}")
        return
    
    await websocket.accept()
    
    # User is authenticated - extract values from verified auth context
    user_id_str = auth.user_id_str
    organization_id = auth.organization_id_str
    user_email = auth.email
    
    # Check user status (already done in auth middleware, but double-check waitlist)
    if auth.role == "waitlist":
        await websocket.close(code=1008, reason="You're on the waitlist. We'll notify you when you have access.")
        return

    workflow_status_task: asyncio.Task[None] | None = None

    try:
        # Register for sync progress broadcasts
        if organization_id:
            sync_broadcaster.register(organization_id, websocket)
            workflow_status_task = asyncio.create_task(
                _stream_workflow_tool_status(websocket, organization_id)
            )
        
        # Register for conversation message broadcasts (multi-user support)
        conversation_broadcaster.register(user_id_str, websocket)
        
        # Send active tasks on connect for client catchup
        active_tasks = await task_manager.get_active_tasks(user_id_str, organization_id)
        await websocket.send_text(json.dumps({
            "type": "active_tasks",
            "tasks": active_tasks,
        }))

        # Auto-subscribe to all active tasks
        for task in active_tasks:
            await task_manager.subscribe(task["id"], websocket)

        user_display_name: str = (
            user_email.split("@", 1)[0] if user_email else "Someone"
        )
        if organization_id:
            async with get_session(organization_id=organization_id) as session:
                name_row = await session.execute(
                    select(User.name).where(User.id == UUID(user_id_str))
                )
                db_name: str | None = name_row.scalar_one_or_none()
                if db_name:
                    user_display_name = db_name

        while True:
            raw_message = await websocket.receive_text()

            try:
                data = json.loads(raw_message)
            except json.JSONDecodeError:
                # Legacy: plain text treated as send_message
                data = {"type": "send_message", "message": raw_message}

            message_type = data.get("type", "send_message")

            if message_type == "typing":
                ty_conv_id = data.get("conversation_id")
                if not ty_conv_id:
                    continue
                if not organization_id:
                    _warn_org_required_rejection(
                        user_id=user_id_str,
                        message_type=message_type,
                        conversation_id=str(ty_conv_id),
                    )
                    continue
                try:
                    ty_conv_uuid = UUID(str(ty_conv_id))
                except ValueError:
                    continue
                async with get_session(organization_id=organization_id) as session:
                    ty_row = await session.execute(
                        select(Conversation.scope, Conversation.participating_user_ids).where(
                            Conversation.id == ty_conv_uuid
                        )
                    )
                    ty_conv = ty_row.one_or_none()
                if not ty_conv:
                    continue
                ty_scope: str = ty_conv[0] if ty_conv[0] else "private"
                if ty_scope != "shared":
                    continue
                ty_participants: list[str] = [
                    str(uid) for uid in (ty_conv[1] or [])
                ]
                if not ty_participants:
                    continue
                await conversation_broadcaster.broadcast_to_users(
                    user_ids=ty_participants,
                    event_type="user_typing",
                    data={
                        "conversation_id": str(ty_conv_id),
                        "user_id": user_id_str,
                        "user_name": user_display_name,
                    },
                    exclude_user_id=user_id_str,
                )
                continue

            # Handle send_message - start a new background task
            if message_type == "send_message" or message_type == "chat":
                user_message = data.get("message")
                conversation_id = data.get("conversation_id")
                local_time = data.get("local_time")
                timezone = data.get("timezone")
                attachment_ids: list[str] | None = data.get("attachment_ids")

                if not user_message:
                    continue

                if not organization_id:
                    _warn_org_required_rejection(
                        user_id=user_id_str,
                        message_type=message_type,
                        conversation_id=str(conversation_id) if conversation_id else None,
                    )
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "error": "Organization required to send messages. Select a team or complete onboarding.",
                            }
                        )
                    )
                    continue

                # Create conversation if needed
                if not conversation_id:
                    # Generate title from first message
                    title = _generate_title(user_message)
                    
                    # Generate UUID upfront - SQLAlchemy default isn't populated until flush
                    conv_uuid = uuid4()
                    
                    # Get scope from request (default to shared)
                    conv_scope = data.get("scope", "shared")
                    if conv_scope not in ("private", "shared"):
                        conv_scope = "shared"
                    
                    async with get_session(
                        organization_id=organization_id,
                        user_id=user_id_str,
                    ) as session:
                        conversation = Conversation(
                            id=conv_uuid,
                            user_id=UUID(user_id_str),
                            organization_id=UUID(organization_id),
                            participating_user_ids=[UUID(user_id_str)],
                            title=title,
                            scope=conv_scope,
                        )
                        session.add(conversation)
                        await session.commit()

                    conversation_id = str(conv_uuid)

                    await websocket.send_text(json.dumps({
                        "type": "conversation_created",
                        "conversation_id": conversation_id,
                        "title": title,
                        "scope": conv_scope,
                    }))

                mentions: list[dict] | None = data.get("mentions")
                from services.chat_messages import resolve_agent_responding, save_user_message
                from services.notifications import create_mention_notifications

                should_invoke_agent, suggested_invites = await resolve_agent_responding(
                    conversation_id=conversation_id,
                    organization_id=organization_id,
                    mentions=mentions,
                    message_text=user_message,
                )

                if suggested_invites:
                    await websocket.send_text(json.dumps({
                        "type": "mention_invite_suggested",
                        "conversation_id": conversation_id,
                        "users": suggested_invites,
                    }))

                if not should_invoke_agent:
                    # Human-only path: save message, notify participants, no agent
                    message_id = await save_user_message(
                        conversation_id=conversation_id,
                        user_id=user_id_str,
                        organization_id=organization_id,
                        message_text=user_message,
                        attachment_ids=attachment_ids,
                        sender_email=user_email,
                    )
                    async with get_session(
                        organization_id=organization_id,
                        user_id=user_id_str,
                    ) as session:
                        conv_row = await session.execute(
                            select(Conversation.participating_user_ids).where(
                                Conversation.id == UUID(conversation_id)
                            )
                        )
                        row = conv_row.one_or_none()
                    participant_ids: list[str] = (
                        [str(uid) for uid in (row[0] or [])] if row else []
                    )
                    try:
                        await create_mention_notifications(
                            conversation_id=conversation_id,
                            message_id=message_id,
                            actor_user_id=user_id_str,
                            organization_id=organization_id,
                            mentions=mentions,
                            participant_user_ids=participant_ids,
                        )
                    except Exception:
                        logger.exception("Failed to create mention notifications for conversation %s", conversation_id)
                    await websocket.send_text(json.dumps({
                        "type": "message_sent",
                        "conversation_id": conversation_id,
                        "agent_responding": False,
                    }))
                    continue

                if not await can_use_credits(organization_id):
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "error": "Insufficient credits or no active subscription. Please upgrade your plan or add a payment method.",
                        "code": "insufficient_credits",
                    }))
                    continue

                # Start background task
                is_new_conversation: bool = not data.get("conversation_id")
                task_id = await task_manager.start_task(
                    conversation_id=conversation_id,
                    user_id=user_id_str,
                    organization_id=organization_id,
                    user_message=user_message,
                    user_email=user_email,
                    local_time=local_time,
                    timezone=timezone,
                    is_new_conversation=is_new_conversation,
                    attachment_ids=attachment_ids,
                )

                # Subscribe this websocket to the task
                await task_manager.subscribe(task_id, websocket)

                # Notify client that task started
                task_started_payload = json.dumps({
                    "type": "task_started",
                    "task_id": task_id,
                    "conversation_id": conversation_id,
                })
                await websocket.send_text(task_started_payload)

                # Auto-subscribe other participants in shared conversations
                async with get_session(organization_id=organization_id) as session:
                    conv_row = await session.execute(
                        select(Conversation.scope, Conversation.participating_user_ids).where(
                            Conversation.id == UUID(conversation_id)
                        )
                    )
                    row = conv_row.one_or_none()
                if row and row[0] == "shared" and row[1]:
                    participant_ids: list[str] = [str(uid) for uid in row[1]]
                    for other_user_id in participant_ids:
                        if other_user_id == user_id_str:
                            continue
                        other_websockets = conversation_broadcaster.get_user_websockets(other_user_id)
                        for other_ws in other_websockets:
                            await task_manager.subscribe(task_id, other_ws)
                            await _send_with_timeout(other_ws, task_started_payload)

            # Handle subscribe - client wants to subscribe to a task (e.g., after reconnect)
            elif message_type == "subscribe":
                task_id = data.get("task_id")
                since_index = data.get("since_index", 0)

                if not task_id:
                    continue

                await task_manager.subscribe(task_id, websocket)

                # Send catchup chunks
                chunks = await task_manager.get_task_chunks(task_id, since_index)
                task = await task_manager.get_task(task_id)

                await websocket.send_text(json.dumps({
                    "type": "catchup",
                    "task_id": task_id,
                    "conversation_id": task.get("conversation_id") if task else None,
                    "chunks": chunks,
                    "task_status": task.get("status") if task else "unknown",
                }))

            # Handle cancel - cancel a running task
            elif message_type == "cancel":
                task_id = data.get("task_id")
                if task_id:
                    cancelled = await task_manager.cancel_task(task_id)
                    await websocket.send_text(json.dumps({
                        "type": "task_cancelled",
                        "task_id": task_id,
                        "success": cancelled,
                    }))

            # Handle tool approval messages (generic for all tools)
            elif message_type == "tool_approval":
                operation_id = data.get("operation_id")
                approved = data.get("approved", False)
                options = data.get("options", {})
                tool_conversation_id = data.get("conversation_id")

                if not operation_id:
                    await websocket.send_text(json.dumps({
                        "type": "tool_approval_result",
                        "status": "error",
                        "error": "Missing operation_id",
                    }))
                    continue

                # Execute the appropriate tool based on stored operation
                result = await _execute_tool_approval(
                    operation_id=operation_id,
                    approved=approved,
                    options=options,
                    organization_id=organization_id,
                    user_id=user_id_str,
                )

                await update_tool_call_result(operation_id, {
                    "type": "tool_approval_result",
                    "status": result.get("status", "unknown"),
                    "operation_id": operation_id,
                    **result,
                })

                await websocket.send_text(json.dumps({
                    "type": "tool_approval_result",
                    "operation_id": operation_id,
                    **result,
                }))

                # If operation failed, start a task for the agent to handle the error
                if result.get("status") == "failed" and result.get("error") and tool_conversation_id and organization_id:
                    tool_name = result.get("tool_name", "tool")
                    error_feedback = (
                        f"[{tool_name} Operation Failed] The operation you requested was approved "
                        f"but failed with this error:\n\n{result.get('error')}\n\n"
                        f"Please analyze the error, explain what went wrong to the user, "
                        f"and offer to retry with corrected parameters."
                    )

                    task_id = await task_manager.start_task(
                        conversation_id=tool_conversation_id,
                        user_id=user_id_str,
                        organization_id=organization_id,
                        user_message=error_feedback,
                    )
                    await task_manager.subscribe(task_id, websocket)

                    await websocket.send_text(json.dumps({
                        "type": "task_started",
                        "task_id": task_id,
                        "conversation_id": tool_conversation_id,
                    }))

            # Legacy: Handle CRM approval messages (for backward compatibility)
            elif message_type == "crm_approval":
                operation_id = data.get("operation_id")
                approved = data.get("approved", False)
                skip_duplicates = data.get("skip_duplicates", True)
                crm_conversation_id = data.get("conversation_id")

                if not operation_id:
                    await websocket.send_text(json.dumps({
                        "type": "crm_approval_result",
                        "status": "error",
                        "error": "Missing operation_id",
                    }))
                    continue

                if approved:
                    result = await execute_crm_operation(operation_id, skip_duplicates)
                else:
                    result = await cancel_crm_operation(operation_id)

                await update_tool_call_result(operation_id, {
                    "type": "crm_approval_result",
                    "status": result.get("status", "unknown"),
                    "operation_id": operation_id,
                    **result,
                })

                await websocket.send_text(json.dumps({
                    "type": "crm_approval_result",
                    "operation_id": operation_id,
                    **result,
                }))

                # If operation failed, start a task for the agent to handle the error
                if result.get("status") == "failed" and result.get("error") and crm_conversation_id and organization_id:
                    error_feedback = (
                        f"[CRM Operation Failed] The operation you requested was approved "
                        f"but failed with this error:\n\n{result.get('error')}\n\n"
                        f"Please analyze the error, explain what went wrong to the user, "
                        f"and offer to retry with corrected parameters."
                    )

                    task_id = await task_manager.start_task(
                        conversation_id=crm_conversation_id,
                        user_id=user_id_str,
                        organization_id=organization_id,
                        user_message=error_feedback,
                    )
                    await task_manager.subscribe(task_id, websocket)

                    await websocket.send_text(json.dumps({
                        "type": "task_started",
                        "task_id": task_id,
                        "conversation_id": crm_conversation_id,
                    }))

    except WebSocketDisconnect:
        logger.info("User %s disconnected", user_id_str)
    finally:
        if workflow_status_task:
            workflow_status_task.cancel()
            try:
                await workflow_status_task
            except asyncio.CancelledError:
                pass
        # Clean up subscriptions
        await task_manager.unsubscribe_all(websocket)
        # Unregister from sync progress broadcasts
        if organization_id:
            sync_broadcaster.unregister(organization_id, websocket)
        # Unregister from conversation message broadcasts
        conversation_broadcaster.unregister(user_id_str, websocket)
