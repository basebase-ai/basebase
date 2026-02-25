{
  "event_message": "cannot insert multiple commands into a prepared statement",
  "id": "c4d8c54b-74d9-407f-bdf9-65fa6a6904a8",
  "metadata": [
    {
      "file": null,
      "host": "db-izcwxmpvafizqkcxioje",
      "metadata": [],
      "parsed": [
        {
          "application_name": "Supavisor",
          "backend_type": "client backend",
          "command_tag": "PARSE",
          "connection_from": "2600:1f13:838:6e01:5e8f:364:f3:7a74:60902",
          "context": null,
          "database_name": "postgres",
          "detail": null,
          "error_severity": "ERROR",
          "hint": null,
          "internal_query": null,
          "internal_query_pos": null,
          "leader_pid": null,
          "location": null,
          "process_id": 31505,
          "query": "SELECT set_config('app.current_org_id', '', false); RESET ROLE",
          "query_id": 0,
          "query_pos": null,
          "session_id": "699f27ad.7b11",
          "session_line_num": 77,
          "session_start_time": "2026-02-25 16:47:41 UTC",
          "sql_state_code": "42601",
          "timestamp": "2026-02-25 16:49:32.153 UTC",
          "transaction_id": 0,
          "user_name": "postgres",
          "virtual_transaction_id": "16/17922"
        }
      ],
      "parsed_from": null,
      "project": null,
      "source_type": null
    }
  ],
  "timestamp": 1772038172153000
}"""
Granola MCP connector – meeting notes via Granola's MCP server.

Uses OAuth (browser-based, stored in Nango). Works for all Granola plans
including free; free tier can only query notes from the last 30 days.

MCP server: https://mcp.granola.ai/mcp
Docs: https://docs.granola.ai/help-center/sharing/integrations/mcp
"""

from __future__ import annotations

from connectors.base_mcp import BaseMCPConnector
from connectors.registry import (
    AuthType,
    Capability,
    ConnectorAction,
    ConnectorMeta,
    ConnectorScope,
)

GRANOLA_MCP_URL: str = "https://mcp.granola.ai/mcp"


class GranolaMCPConnector(BaseMCPConnector):
    """Connector for Granola meeting notes via MCP (OAuth, all plans)."""

    source_system: str = "granola_mcp"
    mcp_server_url: str = GRANOLA_MCP_URL

    meta = ConnectorMeta(
        name="Granola (MCP)",
        slug="granola_mcp",
        auth_type=AuthType.OAUTH2,
        scope=ConnectorScope.USER,
        entity_types=["notes", "meetings"],
        capabilities=[Capability.QUERY, Capability.ACTION],
        nango_integration_id="granola_mcp",
        description="Granola meeting notes via MCP – list, search, and chat with your meetings",
        query_description="Search and list meeting notes via Granola MCP. Use list_meetings, get_meetings, or query_granola_meetings.",
        actions=[
            ConnectorAction(
                name="list_meetings",
                description="List your meetings with id, title, date, and attendees.",
                parameters=[],
            ),
            ConnectorAction(
                name="get_meetings",
                description="Search meeting content: id, title, date, attendees, private notes, enhanced notes.",
                parameters=[
                    {"name": "query", "type": "string", "required": False, "description": "Search query over meeting content"},
                ],
            ),
            ConnectorAction(
                name="query_granola_meetings",
                description="Chat with your Granola meetings (natural language questions over your notes).",
                parameters=[
                    {"name": "query", "type": "string", "required": True, "description": "Question or request about your meetings"},
                ],
            ),
            ConnectorAction(
                name="get_meeting_transcript",
                description="Get raw transcript for a meeting (paid Granola tiers only).",
                parameters=[
                    {"name": "meeting_id", "type": "string", "required": True, "description": "Meeting ID from list_meetings"},
                ],
            ),
        ],
    )
