from __future__ import annotations

from uuid import uuid4

import pytest

from messengers.base import InboundMessage, MessageType
from messengers.slack import SlackMessenger
from services.context_cache import conversation_context, slack_channel_context


def test_slack_channel_context_eligibility_public_only() -> None:
    assert slack_channel_context.is_public_slack_channel_context_eligible(
        channel_id="C123",
        channel_type="channel",
        message_type=MessageType.MENTION,
    )
    assert not slack_channel_context.is_public_slack_channel_context_eligible(
        channel_id="D123",
        channel_type="im",
        message_type=MessageType.DIRECT,
    )
    assert not slack_channel_context.is_public_slack_channel_context_eligible(
        channel_id="G123",
        channel_type="group",
        message_type=MessageType.MENTION,
    )
    assert not slack_channel_context.is_public_slack_channel_context_eligible(
        channel_id="C123",
        channel_type="private_channel",
        message_type=MessageType.MENTION,
    )
    assert not slack_channel_context.is_public_slack_channel_context_eligible(
        channel_id="C123",
        channel_type="mpim",
        message_type=MessageType.MENTION,
    )


def test_slack_channel_payload_caps_messages_and_keeps_attachments() -> None:
    messages = [
        {
            "ts": f"1700000{i:03d}.000000",
            "thread_ts": f"1700000{i:03d}.000000",
            "user": "U123",
            "text": f"message {i}",
        }
        for i in range(260)
    ]
    messages[-1]["files"] = [
        {
            "id": "F123",
            "name": "deck.pdf",
            "url_private_download": "https://files.slack.com/file.pdf",
            "mimetype": "application/pdf",
            "expanded_document_text": "do not keep arbitrary expanded content",
        }
    ]

    payload = slack_channel_context.build_payload(
        organization_id=str(uuid4()),
        workspace_id="T123",
        channel_id="C123",
        messages=messages,
        formatted_context="context",
    )

    assert payload["message_count"] == 250
    assert payload["messages"][0]["text"] == "message 10"
    assert payload["messages"][-1]["files"][0]["id"] == "F123"
    assert "expanded_document_text" not in payload["messages"][-1]["files"][0]


def test_flatten_channel_payload_counts_thread_replies_in_same_cap() -> None:
    channel_messages = [
        {"ts": "1000.0", "thread_ts": "1000.0", "user": "U1", "text": "root"}
    ]
    thread_expansions = {
        "1000.0": [
            {"ts": f"1000.{i:06d}", "thread_ts": "1000.0", "user": "U1", "text": f"reply {i}"}
            for i in range(260)
        ]
    }

    flattened = slack_channel_context.flatten_channel_payload(
        channel_messages=channel_messages,
        thread_expansions=thread_expansions,
    )

    assert len(flattened) == 250
    assert all(message["thread_ts"] == "1000.0" for message in flattened)


def test_conversation_payload_omits_raw_attachment_bytes() -> None:
    payload = conversation_context.build_conversation_payload(
        organization_id=str(uuid4()),
        conversation_id=str(uuid4()),
        messages=[
            {
                "message_id": "m1",
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "title": "proposal.pdf",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": "abcdef",
                        },
                    },
                    {"type": "text", "text": "please read attachment_id=att1"},
                ],
            }
        ],
    )

    cached_content = payload["messages"][0]["content"]
    assert cached_content[0]["type"] == "text"
    assert "raw bytes omitted" in cached_content[0]["text"]
    assert "abcdef" not in str(cached_content)
    assert "attachment_id=att1" in str(cached_content)


@pytest.mark.asyncio
async def test_slack_inject_uses_redis_formatted_context(monkeypatch: pytest.MonkeyPatch) -> None:
    messenger = SlackMessenger()
    message = InboundMessage(
        external_user_id="U123",
        text="hi",
        message_type=MessageType.MENTION,
        message_id="1700000000.000000",
        messenger_context={
            "organization_id": str(uuid4()),
            "workspace_id": "T123",
            "channel_id": "C123",
            "channel_type": "channel",
        },
    )

    async def fake_get_cached_channel_context(**_kwargs: object) -> dict[str, object]:
        return {
            "formatted_context": "cached public channel context",
            "latest_ts": "1700000000.000000",
            "rendered_second": 9999999999,
            "dirty": False,
            "messages": [{"ts": "1700000000.000000", "text": "hi"}],
        }

    async def fail_activity_cache(**_kwargs: object) -> None:
        raise AssertionError("activity DB cache should not be read on Redis hit")

    monkeypatch.setattr(
        slack_channel_context,
        "get_cached_channel_context",
        fake_get_cached_channel_context,
    )
    monkeypatch.setattr(
        messenger,
        "_get_cached_channel_context_payload_from_activity",
        fail_activity_cache,
    )

    await messenger._inject_recent_channel_context(
        message=message,
        workspace_id="T123",
        channel_id="C123",
    )

    workflow_context = message.messenger_context["workflow_context"]
    assert workflow_context["slack_recent_channel_context"] == "cached public channel context"
    assert workflow_context["slack_recent_channel_latest_ts"] == "1700000000.000000"


@pytest.mark.asyncio
async def test_slack_inject_skips_private_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    messenger = SlackMessenger()
    message = InboundMessage(
        external_user_id="U123",
        text="hi",
        message_type=MessageType.MENTION,
        message_id="1700000000.000000",
        messenger_context={
            "organization_id": str(uuid4()),
            "workspace_id": "T123",
            "channel_id": "G123",
            "channel_type": "group",
        },
    )

    async def fail_get_cached_channel_context(**_kwargs: object) -> None:
        raise AssertionError("Redis should not be read for private/group channels")

    monkeypatch.setattr(
        slack_channel_context,
        "get_cached_channel_context",
        fail_get_cached_channel_context,
    )

    await messenger._inject_recent_channel_context(
        message=message,
        workspace_id="T123",
        channel_id="G123",
    )

    assert "workflow_context" not in message.messenger_context
