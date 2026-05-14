"""
Generic MCP connector.

Lets users connect any MCP-compatible server by URL. On connect, performs
an MCP handshake and discovers available tools. The agent can then invoke
those tools via the standard run_on_connector / query_on_connector dispatch.

Uses raw Streamable HTTP transport (JSON-RPC 2.0 over HTTP POST) — same
pattern as the Granola connector, no MCP SDK dependency required.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy import select

from connectors.base import BaseConnector
from connectors.registry import (
    AuthField,
    AuthType,
    Capability,
    ConnectorAction,
    ConnectorMeta,
    ConnectorScope,
)
from models.database import get_session
from models.integration import Integration

logger = logging.getLogger(__name__)

MCP_JSONRPC_VERSION: str = "2.0"
MCP_PROTOCOL_VERSION: str = "2025-03-26"
MCP_CLIENT_INFO: dict[str, str] = {"name": "basebase", "version": "1.0.0"}
DEFAULT_TIMEOUT: float = 60.0

# Common aliases the LLM may use when calling the `call_tool` action.
# The canonical names are the first entry of each tuple.
_TOOL_NAME_ALIASES: tuple[str, ...] = ("tool", "tool_name", "name")
_ARGUMENTS_ALIASES: tuple[str, ...] = (
    "arguments",
    "args",
    "tool_args",
    "parameters",
    "input",
)


# ---------------------------------------------------------------------------
# Generic MCP client (Streamable HTTP transport, JSON-RPC 2.0)
# ---------------------------------------------------------------------------


class GenericMcpClient:
    """Reusable JSON-RPC 2.0 client for any MCP server over Streamable HTTP."""

    def __init__(self, endpoint_url: str, auth_header: str | None = None) -> None:
        self._endpoint_url: str = endpoint_url
        self._auth_header: tuple[str, str] | None = self._parse_auth(auth_header)
        self._request_id: int = 0
        self._session_id: str | None = None

    @staticmethod
    def _parse_auth(raw: str | None) -> tuple[str, str] | None:
        """Parse an auth string into a (header_name, header_value) tuple.

        Supports two formats:
          - "header-name: value"  →  custom header  (e.g. "api-key: abc123")
          - "raw-token"           →  Authorization: Bearer raw-token
        """
        if not raw:
            return None
        raw = raw.strip()
        if ": " in raw:
            name, _, value = raw.partition(": ")
            return (name.strip(), value.strip())
        return ("Authorization", f"Bearer {raw}")

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._auth_header:
            headers[self._auth_header[0]] = self._auth_header[1]
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send a JSON-RPC 2.0 request and return the result."""
        payload: dict[str, Any] = {
            "jsonrpc": MCP_JSONRPC_VERSION,
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response: httpx.Response = await client.post(
                self._endpoint_url,
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()

            session_id: str | None = response.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id

            content_type: str = response.headers.get("content-type", "")

            if "text/event-stream" in content_type:
                return self._parse_sse(response.text)

            data: dict[str, Any] = response.json()
            if "error" in data:
                error_info: dict[str, Any] = data["error"]
                raise RuntimeError(
                    f"MCP error {error_info.get('code')}: {error_info.get('message')}"
                )
            return data.get("result")

    @staticmethod
    def _parse_sse(raw_text: str) -> Any:
        """Extract the last JSON-RPC result from an SSE stream."""
        last_result: Any = None
        for line in raw_text.splitlines():
            if line.startswith("data: "):
                try:
                    event_data: dict[str, Any] = json.loads(line[6:])
                    if "result" in event_data:
                        last_result = event_data["result"]
                    elif "error" in event_data:
                        error_info: dict[str, Any] = event_data["error"]
                        raise RuntimeError(
                            f"MCP error {error_info.get('code')}: {error_info.get('message')}"
                        )
                except json.JSONDecodeError:
                    continue
        return last_result

    async def initialize(self) -> dict[str, Any]:
        """Perform MCP initialize handshake."""
        result: Any = await self._rpc("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": MCP_CLIENT_INFO,
        })
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                self._endpoint_url,
                headers=self._headers(),
                json={
                    "jsonrpc": MCP_JSONRPC_VERSION,
                    "method": "notifications/initialized",
                },
            )
        return result if isinstance(result, dict) else {}

    async def list_tools(self) -> list[dict[str, Any]]:
        """Call tools/list and return the tool descriptors."""
        result: Any = await self._rpc("tools/list")
        if isinstance(result, dict):
            tools: Any = result.get("tools", [])
            return tools if isinstance(tools, list) else []
        return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Call an MCP tool and return the result content."""
        params: dict[str, Any] = {
            "name": tool_name,
            "arguments": arguments if arguments is not None else {},
        }
        return await self._rpc("tools/call", params)


def _extract_text_from_content(result: Any) -> str:
    """Pull text out of MCP content blocks (same format as tools/call responses)."""
    if isinstance(result, dict):
        content: Any = result.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text: Any = block.get("text", "")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "\n".join(parts)
        if isinstance(result.get("result"), str):
            return result["result"]
    if isinstance(result, str):
        return result
    return json.dumps(result, default=str)


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


class McpConnector(BaseConnector):
    """Generic connector for any MCP-compatible server."""

    source_system: str = "mcp"

    meta = ConnectorMeta(
        name="MCP Server",
        slug="mcp",
        description="Connect any MCP-compatible server by URL",
        auth_type=AuthType.CUSTOM,
        scope=ConnectorScope.USER,
        entity_types=[],
        capabilities=[Capability.QUERY, Capability.ACTION],
        actions=[
            ConnectorAction(
                name="call_tool",
                description=(
                    "Call a tool on the connected MCP server. "
                    "Pass params={'tool': '<tool_name>', 'arguments': {…}} where "
                    "<tool_name> is one of the MCP tools discovered via list_tools, "
                    "and 'arguments' is an object matching that tool's inputSchema "
                    "(use {} if the tool takes no arguments). "
                    "Example: params={'tool': 'search_docs', 'arguments': {'query': 'hello'}}."
                ),
                parameters=[
                    {"name": "tool", "type": "string", "required": True,
                     "description": "Name of the MCP tool to call (from list_tools)"},
                    {"name": "arguments", "type": "object", "required": False,
                     "description": "Object matching the tool's inputSchema. Pass {} if the tool takes no arguments. Do NOT inline the inner tool's fields at the top level of params."},
                ],
            ),
        ],
        query_description="Query 'list_tools' to see available tools on the MCP server, or pass a tool name to get its schema.",
        auth_fields=[
            AuthField(
                name="endpoint_url",
                label="MCP Endpoint URL",
                type="url",
                required=True,
                help_text="Full URL of the MCP server (e.g. https://mcp.example.com/mcp)",
            ),
            AuthField(
                name="auth_header",
                label="Auth Header / Token",
                type="password",
                required=False,
                help_text="e.g. 'api-key: abc123' or a raw Bearer token",
            ),
        ],
        usage_guide=(
            "This connector lets you interact with a remote MCP server.\n\n"
            "1. Use query_on_connector(connector='<SLUG>', query='list_tools') to "
            "see available tools and their inputSchemas.\n"
            "2. Use run_on_connector(connector='<SLUG>', action='call_tool', "
            "params={'tool': '<tool_name>', 'arguments': {…}}) to invoke a tool.\n\n"
            "IMPORTANT: there are two parameter layers — do not conflate them.\n"
            "  - OUTER (the wrapper): params must be exactly {'tool': ..., 'arguments': ...}.\n"
            "  - INNER (passed to the MCP tool): the 'arguments' object must match the\n"
            "    tool's own inputSchema (e.g. {'type': 'X (Twitter) Trending', 'limit': 15}).\n"
            "Do NOT inline the inner tool's fields (like 'type', 'limit') at the top level of params.\n"
            "Do NOT use 'tool_name' / 'tool_args' / 'args' — the canonical wrapper keys are\n"
            "'tool' and 'arguments' (other variants are accepted for robustness but discouraged).\n\n"
            "Replace <SLUG> with the actual connector slug (e.g. mcp_deepwiki).\n"
            "The available tools depend on which MCP server the user has connected."
        ),
    )

    async def _get_mcp_config(self) -> tuple[str, str | None, list[dict[str, Any]]]:
        """Load endpoint URL, auth header, and cached tools from integration extra_data."""
        if not self._integration:
            await self._load_integration()
        if not self._integration:
            raise ValueError("No active MCP integration found")

        extra: dict[str, Any] = self._integration.extra_data or {}
        endpoint_url: str | None = extra.get("endpoint_url")
        if not endpoint_url:
            raise ValueError("MCP integration missing endpoint_url in extra_data")

        auth_header: str | None = extra.get("auth_header") or extra.get("bearer_token")
        cached_tools: list[dict[str, Any]] = extra.get("tools", [])
        return endpoint_url, auth_header, cached_tools

    def _make_client(self, endpoint_url: str, auth_header: str | None) -> GenericMcpClient:
        return GenericMcpClient(endpoint_url=endpoint_url, auth_header=auth_header)

    # ------------------------------------------------------------------
    # QUERY capability
    # ------------------------------------------------------------------

    async def query(self, request: str) -> dict[str, Any]:
        """List available tools or describe a specific tool."""
        endpoint_url, auth_header, cached_tools = await self._get_mcp_config()

        query_lower: str = request.strip().lower()

        if query_lower in ("list_tools", "list", "tools", ""):
            if cached_tools:
                tool_summaries: list[dict[str, Any]] = [
                    {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "inputSchema": t.get("inputSchema"),
                    }
                    for t in cached_tools
                ]
                return {"tools": tool_summaries, "count": len(tool_summaries)}

            client: GenericMcpClient = self._make_client(endpoint_url, auth_header)
            await client.initialize()
            tools: list[dict[str, Any]] = await client.list_tools()
            return {"tools": tools, "count": len(tools)}

        for tool in cached_tools:
            if isinstance(tool, dict) and tool.get("name", "").lower() == query_lower:
                return {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "inputSchema": tool.get("inputSchema"),
                }

        return {"error": f"Unknown query '{request}'. Use 'list_tools' to see available tools."}

    # ------------------------------------------------------------------
    # ACTION capability
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_tool_and_arguments(
        params: dict[str, Any],
    ) -> tuple[str | None, dict[str, Any], list[str]]:
        """Pull the tool name + arguments out of ``params``, accepting common aliases.

        Returns ``(tool_name, arguments, alias_warnings)``. ``tool_name`` is None
        when no canonical or alias key holds a non-empty string. ``alias_warnings``
        is a list of human-readable notes about non-canonical keys the caller used.
        """
        tool_name: str | None = None
        tool_alias_used: str | None = None
        for key in _TOOL_NAME_ALIASES:
            candidate: Any = params.get(key)
            if isinstance(candidate, str) and candidate.strip():
                tool_name = candidate.strip()
                tool_alias_used = key
                break

        arguments: dict[str, Any] = {}
        arg_alias_used: str | None = None
        for key in _ARGUMENTS_ALIASES:
            candidate = params.get(key)
            if isinstance(candidate, dict):
                arguments = candidate
                arg_alias_used = key
                break

        warnings: list[str] = []
        if tool_alias_used and tool_alias_used != _TOOL_NAME_ALIASES[0]:
            warnings.append(
                f"Used non-canonical key '{tool_alias_used}' for the tool name; "
                f"prefer '{_TOOL_NAME_ALIASES[0]}'."
            )
        if arg_alias_used and arg_alias_used != _ARGUMENTS_ALIASES[0]:
            warnings.append(
                f"Used non-canonical key '{arg_alias_used}' for the tool arguments; "
                f"prefer '{_ARGUMENTS_ALIASES[0]}'."
            )
        return tool_name, arguments, warnings

    async def execute_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        if action != "call_tool":
            raise ValueError(f"Unknown action: {action}. Use 'call_tool'.")

        tool_name, arguments, alias_warnings = self._resolve_tool_and_arguments(params)
        if not tool_name:
            return {
                "error": (
                    "Missing required parameter 'tool' (the name of the MCP tool to call). "
                    "Call run_on_connector with params={'tool': '<tool_name>', 'arguments': {…}}. "
                    "Use query_on_connector(query='list_tools') first to see the available tool names."
                ),
                "received_keys": sorted(params.keys()),
            }

        for note in alias_warnings:
            logger.warning("[McpConnector] %s", note)

        endpoint_url, auth_header, _cached_tools = await self._get_mcp_config()
        client: GenericMcpClient = self._make_client(endpoint_url, auth_header)
        await client.initialize()

        try:
            result: Any = await client.call_tool(tool_name, arguments)
        except RuntimeError as exc:
            return {"error": f"MCP tool '{tool_name}' failed: {exc}"}
        except httpx.HTTPStatusError as exc:
            return {"error": f"HTTP error calling MCP tool '{tool_name}': {exc.response.status_code}"}

        text_output: str = _extract_text_from_content(result)
        response: dict[str, Any] = {"tool": tool_name, "output": text_output}
        if alias_warnings:
            response["warning"] = (
                "Non-canonical parameter keys were used and remapped. "
                + " ".join(alias_warnings)
            )
        return response

    # ------------------------------------------------------------------
    # Stubs for abstract methods (MCP connector does not sync CRM data)
    # ------------------------------------------------------------------

    async def sync_deals(self) -> list[Any]:
        return []

    async def sync_accounts(self) -> list[Any]:
        return []

    async def sync_contacts(self) -> list[Any]:
        return []

    async def sync_activities(self) -> list[Any]:
        return []

    async def fetch_deal(self, deal_id: str) -> dict[str, Any]:
        raise NotImplementedError("MCP connector does not support fetch_deal")
