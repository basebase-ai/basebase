"""
MCP (Model Context Protocol) client for Streamable HTTP transport.

Provides a thin wrapper over the official `mcp` Python SDK to connect to MCP
servers (e.g. Granola MCP), initialize, list tools, and call tools. Used by
MCP-backed connectors (BaseMCPConnector, Granola MCP).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default timeouts for MCP operations
MCP_CONNECT_TIMEOUT: float = 15.0
MCP_READ_TIMEOUT: float = 60.0


class MCPClientError(Exception):
    """Raised when an MCP client operation fails."""

    pass


async def _run_with_session(
    url: str,
    headers: dict[str, str],
    *,
    operation: str,
    tool_name: str | None = None,
    tool_arguments: dict[str, Any] | None = None,
) -> Any:
    """Open Streamable HTTP connection, initialize, run one operation, return result."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    http_headers: dict[str, str] = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        **headers,
    }
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(MCP_CONNECT_TIMEOUT, read=MCP_READ_TIMEOUT),
        headers=http_headers,
    )
    try:
        async with streamable_http_client(url, http_client=client, terminate_on_close=True) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=MCP_READ_TIMEOUT) as session:
                await session.initialize()
                if operation == "list_tools":
                    result: Any = await session.list_tools()
                    return result
                if operation == "call_tool" and tool_name is not None:
                    call_result = await session.call_tool(
                        tool_name,
                        arguments=tool_arguments or {},
                        read_timeout_seconds=MCP_READ_TIMEOUT,
                    )
                    return call_result
                raise ValueError(f"Unknown operation: {operation}")
    except Exception as exc:
        logger.warning("MCP client operation failed: %s", exc, exc_info=True)
        raise MCPClientError(str(exc)) from exc
    finally:
        await client.aclose()


async def list_tools(url: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """
    Connect to an MCP server, initialize, and return the list of tools.

    Args:
        url: MCP endpoint URL (e.g. https://mcp.granola.ai/mcp).
        headers: Optional HTTP headers (e.g. Authorization: Bearer <token>).

    Returns:
        List of tool descriptors: [{"name": str, "description": str, "inputSchema": dict}, ...].

    Raises:
        MCPClientError: On connection or protocol errors.
    """
    result = await _run_with_session(url or "", headers or {}, operation="list_tools")
    tools: list[dict[str, Any]] = []
    for t in getattr(result, "tools", []):
        tools.append({
            "name": getattr(t, "name", ""),
            "description": getattr(t, "description", None) or "",
            "inputSchema": getattr(t, "input_schema", None) or {},
        })
    return tools


async def call_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Connect to an MCP server, initialize, call one tool, and return its result.

    Args:
        url: MCP endpoint URL.
        tool_name: Name of the MCP tool to invoke.
        arguments: Optional dict of tool arguments.
        headers: Optional HTTP headers (e.g. Authorization: Bearer <token>).

    Returns:
        Dict with "content" (list of content items, e.g. text), "is_error", and raw fields.
        Content items are normalized to {"type": "text", "text": str} for convenience.

    Raises:
        MCPClientError: On connection or protocol errors.
    """
    result = await _run_with_session(
        url or "",
        headers or {},
        operation="call_tool",
        tool_name=tool_name,
        tool_arguments=arguments or {},
    )
    out: dict[str, Any] = {"is_error": getattr(result, "is_error", False)}
    content: list[dict[str, Any]] = []
    for c in getattr(result, "content", []) or []:
        if hasattr(c, "type") and hasattr(c, "text"):
            content.append({"type": getattr(c, "type", "text"), "text": getattr(c, "text", "")})
        elif isinstance(c, dict):
            content.append(c)
        else:
            content.append({"type": "text", "text": str(c)})
    out["content"] = content
    if getattr(result, "structured_content", None) is not None:
        out["structured_content"] = result.structured_content
    return out
