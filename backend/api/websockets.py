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
from collections import defaultdict
from typing import Dict, Optional, Set
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect

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
    integration_id: Optional[str] = None,
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
        integration_id: Specific integration row UUID this event targets. When
            present, the UI scopes its "syncing" indicator to that row only
            (multi-account: one provider can have multiple connected accounts).
    """
    data: dict[str, str | int] = {
        "provider": provider,
        "count": count,
        "status": status,
    }
    if step is not None:
        data["step"] = step
    if integration_id is not None and integration_id.strip():
        data["integration_id"] = integration_id.strip()
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
from models.user import User
from models.workflow import WorkflowRun
from sqlalchemy import and_, select


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


WORKFLOW_TOOL_PROGRESS_PUBSUB_POLL_SECONDS: float = 1.5
WORKFLOW_TOOL_PROGRESS_SANITY_TIMEOUT_SECONDS: float = 60.0
WORKFLOW_TOOL_PROGRESS_MAX_TIMEOUT_SECONDS: float = 60.0 * 60.0
REDIS_TOOL_PROGRESS_RECONNECT_BASE_SECONDS: float = 1.5
REDIS_TOOL_PROGRESS_RECONNECT_MAX_SECONDS: float = 30.0


def _tool_progress_signature(event: dict[str, object]) -> str:
    """Return a stable signature for de-duping rehydrated tool progress events."""
    result = event.get("result") if isinstance(event.get("result"), dict) else {}
    return f"{event.get('status')}::{json.dumps(result, sort_keys=True, default=str)}"


async def _send_tool_progress_event(
    websocket: WebSocket,
    organization_id: str,
    event: dict[str, object],
) -> bool:
    """Send one tool progress event with timeout protection."""
    sent = await _send_with_timeout(websocket, json.dumps(event, default=str))
    if not sent:
        logger.debug(
            "[WebSocket] Closing tool progress subscription after send failure org=%s",
            organization_id,
        )
    return sent


async def _collect_running_workflow_tool_updates(
    organization_id: str,
) -> list[dict[str, object]]:
    """Collect persisted running workflow tool states for connect/resubscribe rehydration."""
    updates: list[dict[str, object]] = []
    logger.debug(
        "[WebSocket] Rehydrating running workflow tool updates for org %s",
        organization_id,
    )
    async with get_session(organization_id=organization_id) as session:
        run_rows = await session.execute(
            select(WorkflowRun.output)
            .where(
                and_(
                    WorkflowRun.organization_id == UUID(organization_id),
                    WorkflowRun.status == "running",
                )
            )
        )

        conversation_ids: list[UUID] = []
        for output in run_rows.scalars().all():
            if not isinstance(output, dict):
                continue
            conv_id = output.get("conversation_id")
            if not conv_id:
                continue
            try:
                conversation_ids.append(UUID(str(conv_id)))
            except ValueError:
                continue

        if not conversation_ids:
            return updates

        from models.chat_message import ChatMessage

        message_rows = await session.execute(
            select(ChatMessage)
            .join(Conversation, ChatMessage.conversation_id == Conversation.id)
            .where(
                and_(
                    Conversation.id.in_(conversation_ids),
                    Conversation.type == "workflow",
                    ChatMessage.role == "assistant",
                    ChatMessage.content_blocks.isnot(None),
                )
            )
            .order_by(ChatMessage.created_at.desc())
        )

        for message in message_rows.scalars().all():
            for block in message.content_blocks or []:
                if block.get("type") != "tool_use":
                    continue
                status = block.get("status")
                if status not in {"running", "streaming", "pending"}:
                    continue
                updates.append(
                    {
                        "type": "tool_progress",
                        "conversation_id": str(message.conversation_id),
                        "tool_id": str(block.get("id", "")),
                        "tool_name": str(block.get("name", "unknown")),
                        "result": (
                            block.get("result")
                            if isinstance(block.get("result"), dict)
                            else {}
                        ),
                        "status": "running",
                    }
                )

    return updates


async def _rehydrate_running_workflow_tool_status(
    websocket: WebSocket,
    organization_id: str,
    last_sent: dict[str, str],
    active_tools: dict[str, dict[str, object]] | None = None,
    observed_at: float | None = None,
) -> bool:
    """Send persisted running workflow tool states, de-duped against prior sends.

    When active_tools is provided, also track rehydrated running tools so the
    subscription timeout path can resolve stale tool progress for reconnecting
    clients even if no further Redis event arrives.
    """
    try:
        updates = await _collect_running_workflow_tool_updates(organization_id)
    except Exception as exc:
        logger.warning(
            "[WebSocket] Failed to rehydrate workflow tool status for org %s: %s",
            organization_id,
            exc,
        )
        return True

    for update in updates:
        key = f"{update.get('conversation_id')}:{update.get('tool_id')}"
        signature = _tool_progress_signature(update)
        if active_tools is not None:
            tracked_update = dict(update)
            tracked_update["first_seen_at"] = active_tools.get(key, {}).get(
                "first_seen_at",
                observed_at if observed_at is not None else asyncio.get_running_loop().time(),
            )
            active_tools[key] = tracked_update
        if last_sent.get(key) == signature:
            continue
        if not await _send_tool_progress_event(websocket, organization_id, update):
            return False
        last_sent[key] = signature
        logger.debug(
            "[WebSocket] Rehydrated workflow tool status: conv=%s tool=%s",
            update.get("conversation_id"),
            update.get("tool_id"),
        )
    return True


async def _redis_tool_progress_available() -> bool:
    """Return whether Redis pub/sub appears reachable now."""
    from services.tool_progress_pubsub import get_tool_progress_redis

    try:
        redis = await get_tool_progress_redis()
        await redis.ping()
        return True
    except Exception as exc:
        logger.debug("[WebSocket] Redis tool progress ping failed: %s", exc)
        return False


async def _wait_for_redis_tool_progress_recovery(organization_id: str) -> None:
    """Wait for Redis to recover without polling persisted workflow tool state."""
    retry_delay = REDIS_TOOL_PROGRESS_RECONNECT_BASE_SECONDS
    logger.warning(
        "[WebSocket] Redis unavailable for workflow tool progress; "
        "pausing pub/sub until Redis recovers org=%s",
        organization_id,
    )
    while True:
        await asyncio.sleep(retry_delay)
        if await _redis_tool_progress_available():
            logger.info(
                "[WebSocket] Redis recovered; rehydrating once before resubscribe org=%s",
                organization_id,
            )
            return
        retry_delay = min(retry_delay * 2, REDIS_TOOL_PROGRESS_RECONNECT_MAX_SECONDS)


async def _subscribe_workflow_tool_progress(
    websocket: WebSocket,
    organization_id: str,
) -> None:
    """Subscribe this websocket to Redis-published workflow tool progress."""
    from services.tool_progress_pubsub import (
        TOOL_PROGRESS_TERMINAL_STATUSES,
        build_tool_progress_event,
        get_tool_progress_redis,
        tool_progress_channel,
    )

    channel: str = tool_progress_channel(organization_id)
    last_sent: dict[str, str] = {}
    active_tools: dict[str, dict[str, object]] = {}
    last_silence_log_at: float | None = None

    while True:
        pubsub = None
        try:
            redis = await get_tool_progress_redis()
            pubsub = redis.pubsub()
            logger.info(
                "[WebSocket] Subscribing to workflow tool progress channel=%s org=%s",
                channel,
                organization_id,
            )
            await pubsub.subscribe(channel)

            if not await _rehydrate_running_workflow_tool_status(
                websocket,
                organization_id,
                last_sent,
                active_tools,
                asyncio.get_running_loop().time(),
            ):
                return

            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=WORKFLOW_TOOL_PROGRESS_PUBSUB_POLL_SECONDS,
                )
                now = asyncio.get_running_loop().time()

                if message is None:
                    if active_tools:
                        timed_out_tools = [
                            tool
                            for tool in active_tools.values()
                            if now - float(tool.get("first_seen_at", now))
                            >= WORKFLOW_TOOL_PROGRESS_MAX_TIMEOUT_SECONDS
                        ]
                        if timed_out_tools:
                            logger.error(
                                "[WebSocket] Tool progress max timeout after %.0fs org=%s active_tools=%s",
                                WORKFLOW_TOOL_PROGRESS_MAX_TIMEOUT_SECONDS,
                                organization_id,
                                [
                                    f"{tool.get('conversation_id')}:{tool.get('tool_id')}"
                                    for tool in timed_out_tools
                                ],
                            )
                        for timed_out in timed_out_tools:
                            key = f"{timed_out.get('conversation_id')}:{timed_out.get('tool_id')}"
                            active_tools.pop(key, None)
                            timeout_event = build_tool_progress_event(
                                conversation_id=str(timed_out.get("conversation_id", "")),
                                tool_id=str(timed_out.get("tool_id", "")),
                                tool_name=str(timed_out.get("tool_name", "unknown")),
                                result={
                                    "error": (
                                        "Tool progress timed out while waiting for worker updates."
                                    ),
                                    "message": (
                                        "Tool progress timed out while waiting for worker updates."
                                    ),
                                },
                                status="complete",
                            )
                            last_sent[key] = _tool_progress_signature(timeout_event)
                            if not await _send_tool_progress_event(
                                websocket,
                                organization_id,
                                timeout_event,
                            ):
                                return

                        if (
                            active_tools
                            and (
                                last_silence_log_at is None
                                or now - last_silence_log_at
                                >= WORKFLOW_TOOL_PROGRESS_SANITY_TIMEOUT_SECONDS
                            )
                        ):
                            logger.warning(
                                "[WebSocket] Tool progress worker silent for %.0fs org=%s active_tools=%s",
                                WORKFLOW_TOOL_PROGRESS_SANITY_TIMEOUT_SECONDS,
                                organization_id,
                                list(active_tools),
                            )
                            last_silence_log_at = now
                    continue

                raw_data = message.get("data")
                if not raw_data:
                    continue
                try:
                    event = json.loads(
                        raw_data
                        if isinstance(raw_data, str)
                        else raw_data.decode("utf-8")
                    )
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    logger.warning(
                        "[WebSocket] Ignoring invalid tool progress pub/sub payload channel=%s: %s",
                        channel,
                        exc,
                    )
                    continue

                if not isinstance(event, dict) or event.get("type") != "tool_progress":
                    logger.debug("[WebSocket] Ignoring unexpected tool progress event: %s", event)
                    continue

                key = f"{event.get('conversation_id')}:{event.get('tool_id')}"
                status = str(event.get("status") or "running")
                if status in TOOL_PROGRESS_TERMINAL_STATUSES:
                    active_tools.pop(key, None)
                else:
                    tracked_event = dict(event)
                    tracked_event["first_seen_at"] = active_tools.get(key, {}).get(
                        "first_seen_at",
                        now,
                    )
                    active_tools[key] = tracked_event
                    last_silence_log_at = None
                last_sent[key] = _tool_progress_signature(event)

                if not await _send_tool_progress_event(websocket, organization_id, event):
                    return
                logger.debug(
                    "[WebSocket] Forwarded tool progress from Redis: conv=%s tool=%s status=%s",
                    event.get("conversation_id"),
                    event.get("tool_id"),
                    status,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[WebSocket] Tool progress subscription failed for org %s: %s",
                organization_id,
                exc,
            )
            await _wait_for_redis_tool_progress_recovery(organization_id)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception as exc:
                    logger.debug(
                        "[WebSocket] Error closing tool progress pub/sub channel=%s: %s",
                        channel,
                        exc,
                    )
            logger.info(
                "[WebSocket] Stopped workflow tool progress subscription channel=%s org=%s",
                channel,
                organization_id,
            )


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
                _subscribe_workflow_tool_progress(websocket, organization_id)
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
                            source="web",
                        )
                        session.add(conversation)
                        await session.commit()

                    conversation_id = str(conv_uuid)

                    await websocket.send_text(json.dumps({
                        "type": "conversation_created",
                        "conversation_id": conversation_id,
                        "title": title,
                        "scope": conv_scope,
                        "source": "web",
                        "group_bucket_type": "direct",
                        "group_bucket_key": "direct",
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
