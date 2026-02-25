"""
Base connector for MCP (Model Context Protocol) backed integrations.

Subclasses set mcp_server_url and meta; this base implements get_schema (from
MCP tools/list), query (dispatch to an MCP tool), and execute_action (call
MCP tool by name). CRM abstract methods are no-ops.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from connectors.base import BaseConnector
from services.mcp_client import MCPClientError, call_tool, list_tools

logger = logging.getLogger(__name__)


class BaseMCPConnector(BaseConnector):
    """
    Base for connectors that talk to an MCP server via Streamable HTTP.

    Subclasses must set:
    - source_system
    - meta (ConnectorMeta with QUERY + ACTION, and actions mirroring MCP tools)
    - mcp_server_url: str (e.g. https://mcp.granola.ai/mcp)
    """

    mcp_server_url: str = ""

    # ------------------------------------------------------------------
    # CRM abstract methods (no-ops)
    # ------------------------------------------------------------------

    async def sync_deals(self) -> int:
        return 0

    async def sync_accounts(self) -> int:
        return 0

    async def sync_contacts(self) -> int:
        return 0

    async def sync_activities(self) -> int:
        return 0

    async def fetch_deal(self, deal_id: str) -> dict[str, Any]:
        raise NotImplementedError(f"{self.source_system} does not support deals")

    # ------------------------------------------------------------------
    # QUERY and ACTION via MCP client
    # ------------------------------------------------------------------

    def _mcp_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def get_schema(self) -> list[dict[str, Any]]:
        """Return MCP tools as schema entries for the agent."""
        if not self.mcp_server_url:
            return []
        try:
            token: str
            token, _ = await self.get_oauth_token()
            tools = await list_tools(self.mcp_server_url, headers=self._mcp_headers(token))
            return [
                {
                    "entity": t.get("name", ""),
                    "fields": list((t.get("inputSchema") or {}).get("properties", {}).keys()),
                    "description": t.get("description", ""),
                }
                for t in tools
            ]
        except MCPClientError as e:
            logger.warning("MCP get_schema failed: %s", e)
            return []

    async def query(self, request: str) -> dict[str, Any]:
        """
        Interpret request as a tool name (and optional JSON args), call MCP tool, return result.

        Supports: "tool_name" or "tool_name {...}" for JSON arguments.
        """
        if not self.mcp_server_url:
            return {"error": "MCP server URL not configured", "query": request}
        req = (request or "").strip()
        tool_name: str
        arguments: dict[str, Any] = {}
        if req:
            parts = req.split(maxsplit=1)
            tool_name = parts[0]
            if len(parts) > 1:
                rest = parts[1].strip()
                if rest.startswith("{"):
                    try:
                        arguments = json.loads(rest)
                    except json.JSONDecodeError:
                        arguments = {}
                else:
                    arguments = {}
        else:
            tool_name = "list_meetings"
        try:
            token, _ = await self.get_oauth_token()
            result = await call_tool(
                self.mcp_server_url,
                tool_name=tool_name,
                arguments=arguments,
                headers=self._mcp_headers(token),
            )
            return {"results": result, "query": request}
        except MCPClientError as e:
            return {"error": str(e), "query": request}

    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call the MCP tool with the given name and params."""
        if not self.mcp_server_url:
            return {"error": "MCP server URL not configured"}
        try:
            token, _ = await self.get_oauth_token()
            result = await call_tool(
                self.mcp_server_url,
                tool_name=action,
                arguments=params,
                headers=self._mcp_headers(token),
            )
            return result
        except MCPClientError as e:
            return {"error": str(e), "is_error": True}
