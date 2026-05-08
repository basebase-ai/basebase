"""Unit tests for the Trello connector (state mapping, webhooks, verification)."""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

import pytest

from connectors.trello import (
    TRELLO_CARD_DONE_EVENT,
    TRELLO_CARD_UPDATED_EVENT,
    TrelloConnector,
    _list_name_implies_done,
    _resolve_state_type,
)


def test_resolve_state_type_done_list() -> None:
    assert _resolve_state_type(False, "Done") == "completed"


def test_resolve_state_type_in_progress() -> None:
    assert _resolve_state_type(False, "In Progress") == "started"


def test_resolve_state_type_due_complete() -> None:
    assert _resolve_state_type(True, "Doing") == "completed"


def test_list_name_implies_done() -> None:
    assert _list_name_implies_done("Done") is True
    assert _list_name_implies_done("Backlog") is False


def test_process_webhook_emits_updated_and_done() -> None:
    payload: dict[str, Any] = {
        "action": {
            "type": "updateCard",
            "data": {
                "card": {"id": "abc"},
                "listAfter": {"id": "l1", "name": "Done"},
                "listBefore": {"id": "l2", "name": "Doing"},
            },
        },
        "model": {},
    }
    events: list[tuple[str, dict[str, Any]]] = (
        TrelloConnector.process_webhook_payload(payload)
    )
    types: set[str] = {e[0] for e in events}
    assert TRELLO_CARD_UPDATED_EVENT in types
    assert TRELLO_CARD_DONE_EVENT in types


def test_verify_webhook_trello_signature() -> None:
    secret: str = "consumer_secret_test"
    body: bytes = b'{"hello":"world"}'
    url: str = "https://api.example.com/api/connectors/webhook/trello/org-1"
    msg: bytes = (body.decode("utf-8") + url).encode("utf-8")
    expected_b64: str = base64.b64encode(
        hmac.new(secret.encode("utf-8"), msg, hashlib.sha1).digest()
    ).decode("ascii")
    headers: dict[str, str] = {"x-trello-webhook": expected_b64}
    assert TrelloConnector.verify_webhook(
        body, headers, secret, request_url=url
    ) is True


def test_verify_webhook_rejects_bad_signature() -> None:
    assert (
        TrelloConnector.verify_webhook(
            b"{}",
            {"x-trello-webhook": "AAAA"},
            "secret",
            request_url="https://x/y",
        )
        is False
    )


@pytest.mark.asyncio
async def test_process_webhook_ignores_non_action_payload() -> None:
    assert TrelloConnector.process_webhook_payload({}) == []
