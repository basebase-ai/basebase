"""Tests for GmailConnector live QUERY (``query_on_connector``)."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Optional

import pytest

from connectors.gmail import GmailConnector


@pytest.fixture
def connector(monkeypatch: pytest.MonkeyPatch) -> GmailConnector:
    c = GmailConnector(
        organization_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )

    async def _fake_get_oauth_token(*args: Any, **kwargs: Any) -> tuple[str, str]:
        return "fake-token", ""

    monkeypatch.setattr(c, "get_oauth_token", _fake_get_oauth_token)
    return c


def test_query_empty_returns_error(connector: GmailConnector) -> None:
    result: dict[str, Any] = asyncio.run(connector.query("   "))
    assert result.get("error") == "Empty query"


def test_query_passes_through_gmail_search_operators(
    connector: GmailConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _fake_make_request(
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        p: dict[str, Any] = dict(params or {})
        calls.append((endpoint, p))
        if endpoint == "/users/me/messages" and p.get("q") is not None:
            assert p["q"] == "from:dan@example.com newer_than:1d"
            assert p.get("maxResults") == 10
            return {"messages": [{"id": "m1"}]}
        if endpoint == "/users/me/messages/m1":
            assert p.get("format") == "metadata"
            return {
                "id": "m1",
                "threadId": "t1",
                "snippet": "snippet text",
                "internalDate": "1700000000000",
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Re: venture"},
                        {"name": "From", "value": "Dan <dan@example.com>"},
                        {"name": "To", "value": "you@example.com"},
                    ],
                    "parts": [],
                },
            }
        raise AssertionError(f"unexpected endpoint {endpoint} params={p}")

    monkeypatch.setattr(connector, "_make_request", _fake_make_request)

    result: dict[str, Any] = asyncio.run(
        connector.query("from:dan@example.com newer_than:1d")
    )
    assert result["count"] == 1
    msgs: list[dict[str, Any]] = result["messages"]
    assert len(msgs) == 1
    assert msgs[0]["id"] == "m1"
    assert msgs[0]["subject"] == "Re: venture"
    assert msgs[0]["from"] == "dan@example.com"
    assert len(calls) == 2


def test_query_max_clamp(connector: GmailConnector, monkeypatch: pytest.MonkeyPatch) -> None:
    list_params_captured: dict[str, Any] = {}

    async def _fake_make_request(
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        p: dict[str, Any] = dict(params or {})
        if endpoint == "/users/me/messages" and p.get("q") is not None:
            list_params_captured.clear()
            list_params_captured.update(p)
            return {"messages": [{"id": f"m{i}"} for i in range(30)]}
        if endpoint.startswith("/users/me/messages/m"):
            return {
                "id": p.get("id", endpoint.rsplit("/", 1)[-1]),
                "threadId": "t",
                "snippet": "s",
                "internalDate": "1700000000000",
                "labelIds": [],
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "S"},
                        {"name": "From", "value": "x@y.com"},
                    ],
                    "parts": [],
                },
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(connector, "_make_request", _fake_make_request)

    asyncio.run(connector.query("from:x max:500"))
    assert list_params_captured["q"] == "from:x"
    assert list_params_captured["maxResults"] == 25


def test_query_message_prefix_returns_body_text(
    connector: GmailConnector, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain: bytes = b"Hello decoded body"
    b64: str = base64.urlsafe_b64encode(plain).decode("ascii").rstrip("=")

    async def _fake_make_request(
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        p: dict[str, Any] = dict(params or {})
        if endpoint == "/users/me/messages/abc123" and p.get("format") == "full":
            return {
                "id": "abc123",
                "threadId": "th1",
                "snippet": "snip",
                "internalDate": "1700000000000",
                "labelIds": ["SENT"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": "Hi"},
                        {"name": "From", "value": "me@example.com"},
                    ],
                    "body": {"data": b64},
                },
            }
        raise AssertionError(f"{endpoint} {p}")

    monkeypatch.setattr(connector, "_make_request", _fake_make_request)

    result: dict[str, Any] = asyncio.run(connector.query("message:abc123"))
    assert result["count"] == 1
    body: str = result["messages"][0].get("body_text", "")
    assert "Hello decoded body" in body
