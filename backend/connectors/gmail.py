"""
Gmail connector implementation via Google Gmail API.

Responsibilities:
- Authenticate with Google using OAuth token (via Nango)
- Fetch emails from Gmail
- Normalize email data to activity records
- Handle pagination
"""

import base64
import re
import uuid
from datetime import datetime, timedelta
from html import unescape
from typing import Any, Optional

import httpx

from api.websockets import broadcast_sync_progress
from connectors.account_metadata import AccountMetadata
from connectors.base import BaseConnector
from connectors.registry import (
    AuthType, Capability, ConnectorAction, ConnectorMeta, ConnectorScope,
)
from models.activity import Activity
from models.database import get_session
from services.automated_agent_footer import ensure_automated_agent_footer

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"

# Max characters returned for `message:<id>` live body text (QUERY).
_BODY_TEXT_MAX_CHARS: int = 20_000

# Default / upper bound for list + thread QUERY result sizes.
_QUERY_DEFAULT_MAX_MESSAGES: int = 10
_QUERY_MAX_MESSAGES_CAP: int = 25


class GmailConnector(BaseConnector):
    """Connector for Gmail data."""

    source_system = "gmail"
    meta = ConnectorMeta(
        name="Gmail",
        slug="gmail",
        auth_type=AuthType.OAUTH2,
        scope=ConnectorScope.USER,
        entity_types=["activities"],
        capabilities=[Capability.SYNC, Capability.QUERY, Capability.ACTION],
        actions=[
            ConnectorAction(
                name="send_email",
                description="Send an email via the user's connected Gmail account.",
                parameters=[
                    {"name": "to", "type": "string", "required": True, "description": "Recipient email address"},
                    {"name": "subject", "type": "string", "required": True, "description": "Email subject line"},
                    {"name": "body", "type": "string", "required": True, "description": "Email body (plain text)"},
                    {"name": "cc", "type": "array", "required": False, "description": "CC recipients"},
                    {"name": "bcc", "type": "array", "required": False, "description": "BCC recipients"},
                    {
                        "name": "account",
                        "type": "string",
                        "required": False,
                        "description": "Connected Gmail address to send from (defaults to primary / most recent).",
                    },
                ],
            ),
        ],
        nango_integration_id="gmail",
        description="Gmail – email sync, live search, and send",
        query_description=(
            "Live Gmail search via `query_on_connector(connector='gmail', query=...)` using Gmail's `q` syntax.\n"
            "- **Search / list (snippets):** pass a Gmail search string, e.g. `from:alice@example.com newer_than:2d`, "
            "`subject:\"proposal\"`, `has:attachment`. Append ` max:N` (default 10, max 25) to limit hits.\n"
            "- **One message (full body):** `message:<gmail_message_id>` — returns decoded plain text (or stripped HTML) "
            f"in `body_text`, truncated to {_BODY_TEXT_MAX_CHARS:,} characters.\n"
            "- **Thread:** `thread:<thread_id>` — all messages in the thread with snippets; the **latest** message "
            "also includes `body_text`.\n"
            "See Google: Gmail search operators."
        ),
        usage_guide="""# Gmail Usage Guide

## send_email action

Send an email via the user's connected Gmail account. Emails are sent from the authenticated user's Gmail address.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| to | string | Yes | Recipient email address (single address) |
| subject | string | Yes | Email subject line |
| body | string | Yes | Email body — plain text only |
| cc | array | No | CC recipients (list of email strings) |
| bcc | array | No | BCC recipients (list of email strings) |

**Note:** The body is plain text. HTML is not supported. For formatted content, use simple formatting (line breaks, bullet points with `-`).

### Examples

**Simple email:**
```json
{"to": "alice@example.com", "subject": "Meeting follow-up", "body": "Hi Alice,\\n\\nHere are the notes from our call.\\n\\n- Action 1\\n- Action 2"}
```

**With CC:**
```json
{"to": "client@example.com", "subject": "Proposal", "body": "Please find attached...", "cc": ["manager@company.com"]}
```

**Live search (on-demand):** Use `query_on_connector(connector='gmail', query='<Gmail q string>')` for up-to-the-minute results (see connector `query_description` for `message:` and `thread:` forms). Do **not** rely on sync alone for \"did someone reply yet?\".

**Synced warehouse:** Emails also sync into the `activities` table. Use `run_sql_query` with `WHERE source_system = 'gmail'` for bulk/historical analytics on already-synced rows.
""",
    )

    async def _get_headers(self) -> dict[str, str]:
        """Get authorization headers for Gmail API."""
        token, _ = await self.get_oauth_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to Gmail API."""
        headers = await self._get_headers()
        url = f"{GMAIL_API_BASE}{endpoint}"

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def get_labels(self) -> list[dict[str, Any]]:
        """Get list of Gmail labels."""
        data = await self._make_request("GET", "/users/me/labels")
        return data.get("labels", [])

    async def get_messages(
        self,
        label_ids: Optional[list[str]] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Get message list from Gmail."""
        if after is None:
            after = datetime.utcnow() - timedelta(days=30)
        if before is None:
            before = datetime.utcnow()

        # Build query string
        query_parts: list[str] = []
        query_parts.append(f"after:{int(after.timestamp())}")
        query_parts.append(f"before:{int(before.timestamp())}")
        query = " ".join(query_parts)

        messages: list[dict[str, Any]] = []
        page_token: Optional[str] = None
        
        # Broadcast that we're starting to fetch
        await broadcast_sync_progress(
            organization_id=self.organization_id,
            provider=self.source_system,
            count=0,
            status="syncing",
        )

        while len(messages) < max_results:
            params: dict[str, Any] = {
                "maxResults": min(100, max_results - len(messages)),
                "q": query,
            }
            if label_ids:
                params["labelIds"] = ",".join(label_ids)
            if page_token:
                params["pageToken"] = page_token

            data = await self._make_request("GET", "/users/me/messages", params=params)
            
            # Get message IDs
            message_list = data.get("messages", [])
            
            # Fetch full message details for each
            for msg_summary in message_list:
                if len(messages) >= max_results:
                    break
                msg_id = msg_summary.get("id")
                if msg_id:
                    try:
                        full_msg = await self._get_message_detail(msg_id)
                        messages.append(full_msg)
                        
                        # Broadcast progress every 10 messages fetched
                        if len(messages) % 10 == 0:
                            await broadcast_sync_progress(
                                organization_id=self.organization_id,
                                provider=self.source_system,
                                count=len(messages),
                                status="syncing",
                            )
                    except Exception as e:
                        print(f"Failed to fetch message {msg_id}: {e}")

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return messages

    async def _get_message_detail(self, message_id: str) -> dict[str, Any]:
        """Get full message details."""
        params = {"format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Subject", "Date"]}
        return await self._make_request("GET", f"/users/me/messages/{message_id}", params=params)

    async def _get_message_summary(self, message_id: str) -> dict[str, Any]:
        """Fetch one message with metadata headers (cheap; used by live QUERY)."""
        return await self._get_message_detail(message_id)

    async def _get_message_full(self, message_id: str) -> dict[str, Any]:
        """Fetch one message with full MIME payload (for body extraction)."""
        return await self._make_request(
            "GET",
            f"/users/me/messages/{message_id}",
            params={"format": "full"},
        )

    @staticmethod
    def _strip_max_suffix(raw: str) -> tuple[str, int]:
        """Strip trailing `` max:N`` from a list-style query; return (query, max_messages)."""
        stripped: str = raw.strip()
        match: re.Match[str] | None = re.search(r"\s+max:(\d+)\s*$", stripped, flags=re.IGNORECASE)
        if not match:
            return stripped, _QUERY_DEFAULT_MAX_MESSAGES
        q_part: str = stripped[: match.start()].strip()
        try:
            n: int = int(match.group(1))
        except ValueError:
            return q_part, _QUERY_DEFAULT_MAX_MESSAGES
        capped: int = max(1, min(n, _QUERY_MAX_MESSAGES_CAP))
        return q_part, capped

    @staticmethod
    def _b64url_decode(data: str) -> bytes:
        """Decode a Gmail API base64url ``body.data`` string."""
        padded: str = data + "=" * ((4 - len(data) % 4) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))

    @staticmethod
    def _strip_html_to_text(html: str) -> str:
        """Best-effort HTML → plain text for QUERY results."""
        without_blocks: str = re.sub(
            r"(?is)<(script|style)[^>]*>.*?</\1>",
            "",
            html,
        )
        without_tags: str = re.sub(r"<[^>]+>", " ", without_blocks)
        collapsed: str = re.sub(r"\s+", " ", without_tags).strip()
        return unescape(collapsed)

    def _extract_body_text(self, payload: dict[str, Any]) -> str:
        """Walk a Gmail ``payload`` tree; prefer ``text/plain``, else stripped ``text/html``."""
        plain_parts: list[str] = []
        html_parts: list[str] = []

        def walk(part: dict[str, Any]) -> None:
            mime_type: str = str(part.get("mimeType") or "")
            body: dict[str, Any] = part.get("body") or {}
            raw_data: Any = body.get("data")
            if isinstance(raw_data, str) and raw_data:
                try:
                    decoded: str = self._b64url_decode(raw_data).decode("utf-8", errors="replace")
                except Exception:
                    decoded = ""
                if mime_type == "text/plain" and decoded:
                    plain_parts.append(decoded)
                elif mime_type == "text/html" and decoded:
                    html_parts.append(decoded)
            for sub in part.get("parts") or []:
                if isinstance(sub, dict):
                    walk(sub)

        walk(payload)
        if plain_parts:
            text: str = "\n\n".join(plain_parts).strip()
        elif html_parts:
            text = self._strip_html_to_text("\n\n".join(html_parts))
        else:
            text = ""
        if len(text) > _BODY_TEXT_MAX_CHARS:
            text = text[:_BODY_TEXT_MAX_CHARS] + f"\n\n[Truncated — first {_BODY_TEXT_MAX_CHARS:,} characters]"
        return text

    def _gmail_message_to_query_row(
        self,
        gmail_msg: dict[str, Any],
        *,
        body_text: str | None = None,
    ) -> dict[str, Any]:
        """Shape a Gmail API message dict for ``query()`` JSON (not persisted)."""
        activity: Optional[Activity] = self._normalize_message(gmail_msg)
        if activity is None:
            return {}
        cf: dict[str, Any] = dict(activity.custom_fields or {})
        date_val: str | None = None
        if activity.activity_date is not None:
            date_val = activity.activity_date.isoformat()
        row: dict[str, Any] = {
            "id": activity.source_id or "",
            "thread_id": cf.get("thread_id"),
            "subject": activity.subject,
            "from": cf.get("from_email"),
            "from_name": cf.get("from_name"),
            "to": list(cf.get("to_emails") or []),
            "cc": list(cf.get("cc_emails") or []),
            "date": date_val,
            "snippet": (gmail_msg.get("snippet") or "")[:2000],
            "labels": list(cf.get("labels") or []),
            "is_unread": bool(cf.get("is_unread")),
            "is_sent": bool(cf.get("is_sent")),
        }
        if body_text is not None:
            row["body_text"] = body_text
        return row

    async def query(self, request: str) -> dict[str, Any]:
        """Live search / read Gmail on demand (QUERY capability)."""
        stripped: str = request.strip()
        if not stripped:
            return {"error": "Empty query"}

        lower: str = stripped.lower()
        if lower.startswith("message:"):
            raw_id: str = stripped[len("message:") :].strip()
            if not raw_id:
                return {"error": "message_id is required after 'message:'"}
            full_msg: dict[str, Any] = await self._get_message_full(raw_id)
            body_text: str = self._extract_body_text(full_msg.get("payload") or {})
            row: dict[str, Any] = self._gmail_message_to_query_row(full_msg, body_text=body_text)
            if not row:
                return {"error": f"Could not normalize message: {raw_id}"}
            return {"query": stripped, "count": 1, "messages": [row]}

        if lower.startswith("thread:"):
            thread_id: str = stripped[len("thread:") :].strip()
            if not thread_id:
                return {"error": "thread_id is required after 'thread:'"}
            meta_params: dict[str, Any] = {
                "format": "metadata",
                "metadataHeaders": ["From", "To", "Cc", "Subject", "Date"],
            }
            thread_data: dict[str, Any] = await self._make_request(
                "GET",
                f"/users/me/threads/{thread_id}",
                params=meta_params,
            )
            raw_messages: list[Any] = list(thread_data.get("messages") or [])
            typed_messages: list[dict[str, Any]] = [m for m in raw_messages if isinstance(m, dict)]

            def _internal_ms(msg: dict[str, Any]) -> int:
                raw: Any = msg.get("internalDate")
                try:
                    return int(raw) if raw is not None else 0
                except (TypeError, ValueError):
                    return 0

            typed_messages.sort(key=_internal_ms)
            rows: list[dict[str, Any]] = []
            last_id: str | None = None
            for m in typed_messages:
                mid_any = m.get("id")
                if isinstance(mid_any, str) and mid_any:
                    last_id = mid_any

            for m in typed_messages:
                mid_any = m.get("id")
                if not isinstance(mid_any, str) or not mid_any:
                    continue
                body_for_row: str | None = None
                if last_id is not None and mid_any == last_id:
                    full_last: dict[str, Any] = await self._get_message_full(mid_any)
                    body_for_row = self._extract_body_text(full_last.get("payload") or {})
                    row_t = self._gmail_message_to_query_row(full_last, body_text=body_for_row)
                else:
                    summary: dict[str, Any] = await self._get_message_summary(mid_any)
                    row_t = self._gmail_message_to_query_row(summary)
                if row_t:
                    rows.append(row_t)

            return {
                "query": stripped,
                "thread_id": thread_id,
                "count": len(rows),
                "messages": rows,
            }

        q_raw: str
        max_messages: int
        q_raw, max_messages = self._strip_max_suffix(stripped)
        if not q_raw:
            return {"error": "Empty query after removing max: suffix"}

        list_params: dict[str, Any] = {
            "q": q_raw,
            "maxResults": min(100, max_messages),
        }
        list_data: dict[str, Any] = await self._make_request("GET", "/users/me/messages", params=list_params)
        refs: list[Any] = list(list_data.get("messages") or [])
        out_rows: list[dict[str, Any]] = []
        for ref in refs:
            if len(out_rows) >= max_messages:
                break
            if not isinstance(ref, dict):
                continue
            mid: Any = ref.get("id")
            if not isinstance(mid, str) or not mid:
                continue
            detail: dict[str, Any] = await self._get_message_summary(mid)
            r = self._gmail_message_to_query_row(detail)
            if r:
                out_rows.append(r)

        return {
            "query": stripped,
            "count": len(out_rows),
            "messages": out_rows,
        }

    async def sync_deals(self) -> int:
        """Gmail doesn't have deals - return 0."""
        return 0

    async def sync_accounts(self) -> int:
        """Gmail doesn't have accounts - return 0."""
        return 0

    async def sync_contacts(self) -> int:
        """Gmail doesn't have contacts - return 0."""
        return 0

    async def sync_activities(self) -> int:
        """
        Sync Gmail emails as activities.

        This captures email activity and resolves email addresses to
        CRM contacts, accounts, and deals using synced HubSpot data.
        """
        await self.ensure_sync_active("sync_activities:start")
        from connectors.resolution import build_activity_resolver
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        after: datetime = self.sync_since or (datetime.utcnow() - timedelta(days=30))
        before: datetime = datetime.utcnow()

        messages: list[dict[str, Any]] = await self.get_messages(
            after=after,
            before=before,
            max_results=500,
        )

        # Build resolver from existing CRM data in the database
        resolver = await build_activity_resolver(self.organization_id)

        # Pre-load existing source_id -> UUID map (scoped to this integration to avoid
        # collisions when multiple users have Gmail connected - message IDs can repeat
        # across mailboxes)
        org_uuid: uuid.UUID = uuid.UUID(self.organization_id)
        integration_id: uuid.UUID = self._integration.id
        scope_prefix: str = f"{integration_id}:"
        existing_map: dict[str, uuid.UUID] = {}
        async with get_session(organization_id=self.organization_id, user_id=self.user_id) as session:
            result = await session.execute(
                select(Activity.source_id, Activity.id).where(
                    Activity.organization_id == org_uuid,
                    Activity.source_system == self.source_system,
                    Activity.integration_id == integration_id,
                    Activity.source_id.isnot(None),
                )
            )
            for row in result.all():
                existing_map[row[0]] = row[1]

        # Build row dicts for bulk upsert (deduplicate by source_id to avoid
        # undefined ON CONFLICT behavior when the same message appears twice
        # in a single INSERT batch due to Gmail pagination overlap)
        rows: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for message in messages:
            activity: Optional[Activity] = self._normalize_message(message)
            if not activity:
                continue

            # Scope source_id per integration so unique constraint (org, source_system, source_id)
            # is not violated when multiple users in same org connect Gmail
            raw_msg_id: str = activity.source_id or ""
            source_id: str = f"{scope_prefix}{raw_msg_id}"
            if source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            activity.source_id = source_id

            # Reuse existing ID if this message was previously synced
            existing_id: Optional[uuid.UUID] = existing_map.get(source_id)
            if existing_id:
                activity.id = existing_id

            # Collect all email addresses from this message
            cf: dict[str, Any] = activity.custom_fields or {}
            all_emails: list[str] = []
            from_email: Optional[str] = cf.get("from_email")
            if from_email:
                all_emails.append(from_email)
            all_emails.extend(cf.get("to_emails") or [])
            all_emails.extend(cf.get("cc_emails") or [])

            # Resolve to CRM entities
            resolved = resolver.resolve(all_emails)

            row: dict[str, Any] = {
                "id": activity.id,
                "organization_id": activity.organization_id,
                "source_system": activity.source_system,
                "source_id": activity.source_id,
                "type": activity.type,
                "subject": activity.subject,
                "description": activity.description,
                "activity_date": activity.activity_date,
                "contact_id": resolved.contact_id,
                "account_id": resolved.account_id,
                "deal_id": resolved.deal_id,
                "custom_fields": activity.custom_fields,
                "synced_at": datetime.utcnow(),
            }
            if activity.integration_id is not None:
                row["integration_id"] = activity.integration_id
            if activity.owner_user_id is not None:
                row["owner_user_id"] = activity.owner_user_id
            if activity.visibility:
                row["visibility"] = activity.visibility
            rows.append(row)

        # Bulk insert in batches — skip duplicates (emails don't change)
        BATCH_SIZE: int = 500
        count: int = 0
        async with get_session(organization_id=self.organization_id, user_id=self.user_id) as session:
            for i in range(0, len(rows), BATCH_SIZE):
                batch: list[dict[str, Any]] = rows[i : i + BATCH_SIZE]
                stmt = pg_insert(Activity).values(batch).on_conflict_do_nothing()
                await session.execute(stmt)
                await session.commit()
                count = i + len(batch)

        return count

    def _normalize_message(self, gmail_msg: dict[str, Any]) -> Optional[Activity]:
        """Transform Gmail message to our Activity model."""
        msg_id: str = gmail_msg.get("id", "")
        
        # Extract headers
        headers = gmail_msg.get("payload", {}).get("headers", [])
        header_dict: dict[str, str] = {}
        for header in headers:
            name = header.get("name", "").lower()
            value = header.get("value", "")
            header_dict[name] = value

        subject = header_dict.get("subject", "(No Subject)")
        from_header = header_dict.get("from", "")
        to_header = header_dict.get("to", "")
        cc_header = header_dict.get("cc", "")
        date_header = header_dict.get("date", "")

        # Parse from email
        from_email: Optional[str] = None
        from_name: Optional[str] = None
        if "<" in from_header and ">" in from_header:
            # Format: "Name <email@example.com>"
            parts = from_header.split("<")
            from_name = parts[0].strip().strip('"')
            from_email = parts[1].rstrip(">").strip()
        else:
            from_email = from_header.strip()

        # Parse to emails
        to_emails: list[str] = []
        for addr in to_header.split(","):
            addr = addr.strip()
            if "<" in addr and ">" in addr:
                email = addr.split("<")[1].rstrip(">").strip()
                to_emails.append(email)
            elif addr:
                to_emails.append(addr)

        # Parse cc emails
        cc_emails: list[str] = []
        for addr in cc_header.split(","):
            addr = addr.strip()
            if "<" in addr and ">" in addr:
                email = addr.split("<")[1].rstrip(">").strip()
                cc_emails.append(email)
            elif addr:
                cc_emails.append(addr)

        # Parse date
        activity_date: Optional[datetime] = None
        internal_date = gmail_msg.get("internalDate")
        if internal_date:
            try:
                # internalDate is in milliseconds
                activity_date = datetime.utcfromtimestamp(int(internal_date) / 1000)
            except (ValueError, TypeError):
                pass

        # Get snippet as description
        snippet = gmail_msg.get("snippet", "")

        # Get labels
        label_ids = gmail_msg.get("labelIds", [])
        is_unread = "UNREAD" in label_ids
        is_sent = "SENT" in label_ids
        has_attachments = any(
            part.get("filename") 
            for part in gmail_msg.get("payload", {}).get("parts", [])
        )

        vis: dict[str, Any] = self._activity_visibility_fields()
        return Activity(
            id=uuid.uuid4(),
            organization_id=uuid.UUID(self.organization_id),
            source_system=self.source_system,
            source_id=msg_id,
            type="email",
            subject=subject,
            description=snippet[:2000] if snippet else None,
            activity_date=activity_date,
            **vis,
            custom_fields={
                "from_email": from_email,
                "from_name": from_name,
                "to_emails": to_emails[:10],
                "cc_emails": cc_emails[:5],
                "recipient_count": len(to_emails) + len(cc_emails),
                "has_attachments": has_attachments,
                "is_unread": is_unread,
                "is_sent": is_sent,
                "labels": label_ids[:10],
                "thread_id": gmail_msg.get("threadId"),
            },
        )

    async def sync_all(self) -> dict[str, int]:
        """Run all sync operations."""
        activities_count = await self.sync_activities()

        # Broadcast completion
        await broadcast_sync_progress(
            organization_id=self.organization_id,
            provider=self.source_system,
            count=activities_count,
            status="completed",
        )

        return {
            "accounts": 0,
            "deals": 0,
            "contacts": 0,
            "activities": activities_count,
        }

    async def fetch_deal(self, deal_id: str) -> dict[str, Any]:
        """Gmail doesn't have deals."""
        return {"error": "Gmail does not support deals"}

    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a side-effect action."""
        if action == "send_email":
            return await self.send_email(
                to=params["to"],
                subject=params["subject"],
                body=params["body"],
                cc=params.get("cc"),
                bcc=params.get("bcc"),
                reply_to=params.get("reply_to"),
                thread_id=params.get("thread_id"),
                account=params.get("account"),
            )
        raise ValueError(f"Unknown action: {action}")

    async def fetch_account_metadata(self) -> AccountMetadata:
        from connectors.google_userinfo import fetch_google_account_metadata

        token, _ = await self.get_oauth_token()
        return await fetch_google_account_metadata(token)

    async def send_email(
        self,
        to: str | list[str],
        subject: str,
        body: str,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        reply_to: Optional[str] = None,
        thread_id: Optional[str] = None,
        account: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send an email via the user's Gmail account.
        
        Args:
            to: Recipient email address(es)
            subject: Email subject
            body: Email body (plain text)
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address
            thread_id: Optional thread ID to reply in thread
            account: Optional connected account email (lowercased) to send from
            
        Returns:
            Dict with id, threadId on success, or error on failure
        """
        prev_filter: str | None = self._account_identifier_filter
        prev_token: str | None = self._token
        try:
            acct: str | None = account.strip().lower() if isinstance(account, str) and account.strip() else None
            if acct:
                self._account_identifier_filter = acct
                self._token = None

            import email.mime.text
            import email.mime.multipart

            # Build recipients list
            to_list = [to] if isinstance(to, str) else to
            body_with_footer: str = ensure_automated_agent_footer(body)
            if body_with_footer != body:
                print(f"[GmailConnector] Applied automated-agent footer before send to {to_list}")

            # Create message
            message = email.mime.multipart.MIMEMultipart()
            message["To"] = ", ".join(to_list)
            message["Subject"] = subject

            if cc:
                message["Cc"] = ", ".join(cc)
            if bcc:
                message["Bcc"] = ", ".join(bcc)
            if reply_to:
                message["Reply-To"] = reply_to

            # Attach body
            message.attach(email.mime.text.MIMEText(body_with_footer, "plain"))

            # Encode to base64url
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            # Build request body
            request_body: dict[str, Any] = {"raw": raw_message}
            if thread_id:
                request_body["threadId"] = thread_id

            headers = await self._get_headers()
            url = f"{GMAIL_API_BASE}/users/me/messages/send"

            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        url,
                        headers=headers,
                        json=request_body,
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    data = response.json()

                    return {
                        "success": True,
                        "id": data.get("id"),
                        "threadId": data.get("threadId"),
                        "labelIds": data.get("labelIds", []),
                    }

                except httpx.HTTPStatusError as e:
                    error_msg = e.response.text if e.response else str(e)
                    return {
                        "success": False,
                        "error": f"Gmail API error: {error_msg}",
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "error": str(e),
                    }
        finally:
            self._account_identifier_filter = prev_filter
            self._token = prev_token
