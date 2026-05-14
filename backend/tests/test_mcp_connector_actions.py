"""Tests for McpConnector.execute_action wrapper-param handling.

The MCP connector exposes a single ``call_tool`` action whose ``params`` dict
wraps the MCP tool name + arguments. The LLM frequently guesses at the wrapper
key names (``tool_name`` / ``tool_args`` / ``args``), so the connector accepts
common aliases and surfaces a clear error when the tool name is missing.
"""

from __future__ import annotations

from typing import Any

import pytest

from connectors.mcp import GenericMcpClient, McpConnector


def _connector() -> McpConnector:
    return McpConnector(
        "00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )


def _patch_mcp_io(
    monkeypatch: pytest.MonkeyPatch,
    recorded: list[tuple[str, dict[str, Any]]],
    *,
    result: Any = None,
) -> None:
    """Stub out config loading, client construction, and the actual RPC calls."""

    async def fake_get_mcp_config(
        self: McpConnector,
    ) -> tuple[str, str | None, list[dict[str, Any]]]:
        return ("https://mcp.example.com/mcp", None, [])

    async def fake_initialize(self: GenericMcpClient) -> dict[str, Any]:
        return {}

    async def fake_call_tool(
        self: GenericMcpClient,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        recorded.append((tool_name, arguments or {}))
        return result if result is not None else {
            "content": [{"type": "text", "text": "ok"}]
        }

    monkeypatch.setattr(McpConnector, "_get_mcp_config", fake_get_mcp_config)
    monkeypatch.setattr(GenericMcpClient, "initialize", fake_initialize)
    monkeypatch.setattr(GenericMcpClient, "call_tool", fake_call_tool)


@pytest.mark.asyncio
async def test_execute_action_unknown_raises() -> None:
    c: McpConnector = _connector()
    with pytest.raises(ValueError, match="Unknown action"):
        await c.execute_action("not_a_real_action", {})


@pytest.mark.asyncio
async def test_execute_action_canonical_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical {'tool', 'arguments'} shape works without warnings."""
    recorded: list[tuple[str, dict[str, Any]]] = []
    _patch_mcp_io(monkeypatch, recorded)

    c: McpConnector = _connector()
    out: dict[str, Any] = await c.execute_action(
        "call_tool",
        {"tool": "search_docs", "arguments": {"query": "hello"}},
    )

    assert recorded == [("search_docs", {"query": "hello"})]
    assert out["tool"] == "search_docs"
    assert out["output"] == "ok"
    assert "warning" not in out


@pytest.mark.asyncio
async def test_execute_action_accepts_tool_name_and_tool_args_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM-guessed 'tool_name' + 'tool_args' should be normalised and forwarded."""
    recorded: list[tuple[str, dict[str, Any]]] = []
    _patch_mcp_io(monkeypatch, recorded)

    c: McpConnector = _connector()
    out: dict[str, Any] = await c.execute_action(
        "call_tool",
        {
            "tool_name": "get_top_trends",
            "tool_args": {"type": "X (Twitter) Trending", "limit": 15},
        },
    )

    assert recorded == [
        ("get_top_trends", {"type": "X (Twitter) Trending", "limit": 15})
    ]
    assert out["tool"] == "get_top_trends"
    warning: str = out["warning"]
    assert "tool_name" in warning
    assert "tool_args" in warning


@pytest.mark.asyncio
async def test_execute_action_accepts_args_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """{'tool', 'args'} should forward the args dict through, not drop it.

    This is the precise failure mode observed in the wild: when 'args' was
    silently ignored, the remote MCP server returned a confusing
    'missing required field' error because it received no arguments.
    """
    recorded: list[tuple[str, dict[str, Any]]] = []
    _patch_mcp_io(monkeypatch, recorded)

    c: McpConnector = _connector()
    out: dict[str, Any] = await c.execute_action(
        "call_tool",
        {"tool": "get_top_trends", "args": {"type": "X (Twitter) Trending"}},
    )

    assert recorded == [("get_top_trends", {"type": "X (Twitter) Trending"})]
    assert "warning" in out


@pytest.mark.asyncio
async def test_execute_action_prefers_canonical_when_both_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both canonical and alias keys are present, prefer the canonical key."""
    recorded: list[tuple[str, dict[str, Any]]] = []
    _patch_mcp_io(monkeypatch, recorded)

    c: McpConnector = _connector()
    out: dict[str, Any] = await c.execute_action(
        "call_tool",
        {
            "tool": "real_tool",
            "tool_name": "wrong_tool",
            "arguments": {"a": 1},
            "args": {"a": 999},
        },
    )

    assert recorded == [("real_tool", {"a": 1})]
    assert "warning" not in out


@pytest.mark.asyncio
async def test_execute_action_missing_tool_returns_helpful_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing tool name returns an error that points the LLM at the right shape."""
    recorded: list[tuple[str, dict[str, Any]]] = []
    _patch_mcp_io(monkeypatch, recorded)

    c: McpConnector = _connector()
    out: dict[str, Any] = await c.execute_action(
        "call_tool",
        {"arguments": {"query": "hello"}},
    )

    assert recorded == []
    error_text: str = out["error"]
    assert "tool" in error_text
    assert "'tool'" in error_text
    assert "arguments" in error_text
    assert out["received_keys"] == ["arguments"]


@pytest.mark.asyncio
async def test_execute_action_empty_arguments_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tool with no arguments still resolves to an empty dict."""
    recorded: list[tuple[str, dict[str, Any]]] = []
    _patch_mcp_io(monkeypatch, recorded)

    c: McpConnector = _connector()
    out: dict[str, Any] = await c.execute_action(
        "call_tool",
        {"tool": "ping"},
    )

    assert recorded == [("ping", {})]
    assert out["tool"] == "ping"
    assert out["output"] == "ok"
