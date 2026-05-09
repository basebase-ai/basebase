from __future__ import annotations

from uuid import uuid4

import pytest

from messengers.base import InboundMessage, MessageType
from messengers.slack import SlackMessenger
from services.context_cache import conversation_context, slack_channel_context


@pytest.mark.parametrize(
    ("channel_id", "channel_type", "message_type", "expected"),
    [
        ("C123", "channel", MessageType.MENTION, True),
        ("D123", "im", MessageType.DIRECT, False),
        ("G123", "group", MessageType.MENTION, False),
        ("C123", "private_channel", MessageType.MENTION, False),
        ("C123", "mpim", MessageType.MENTION, False),
    ],
)
def test_slack_channel_context_eligibility_public_only(
    channel_id: str,
    channel_type: str,
    message_type: MessageType,
    expected: bool,
) -> None:
    assert slack_channel_context.is_public_slack_channel_context_eligible(
        channel_id=channel_id,
        channel_type=channel_type,
        message_type=message_type,
    ) is expected


def test_slack_payload_caps_thread_replies_and_keeps_file_refs_only() -> None:
    channel_messages = [
        {"ts": "1000.0", "thread_ts": "1000.0", "user": "U1", "text": "root"}
    ]
    thread_expansions = {
        "1000.0": [
            {"ts": f"1000.{i:06d}", "thread_ts": "1000.0", "user": "U1", "text": f"reply {i}"}
            for i in range(259)
        ]
    }
    flattened = slack_channel_context.flatten_channel_payload(
        channel_messages=channel_messages,
        thread_expansions=thread_expansions,
    )
    flattened[-1]["files"] = [{
        "id": "F123",
        "name": "deck.pdf",
        "url_private_download": "https://files.slack.com/file.pdf",
        "mimetype": "application/pdf",
        "expanded_document_text": "omit me",
    }]

    payload = slack_channel_context.build_payload(
        organization_id=str(uuid4()),
        workspace_id="T123",
        channel_id="C123",
        messages=flattened + [{"ts": "9999.0", "thread_ts": "9999.0", "text": "newest"}],
    )

    assert payload["message_count"] == 250
    assert payload["messages"][-2]["files"][0]["id"] == "F123"
    assert "expanded_document_text" not in payload["messages"][-2]["files"][0]
    assert all(message["thread_ts"] for message in payload["messages"])


def test_conversation_payload_omits_raw_attachment_bytes() -> None:
    payload = conversation_context.build_conversation_payload(
        organization_id=str(uuid4()),
        conversation_id=str(uuid4()),
        messages=[{
            "message_id": "m1",
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "title": "proposal.pdf",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": "abcdef"},
                },
                {"type": "text", "text": "please read attachment_id=att1"},
            ],
        }],
    )

    cached_content = payload["messages"][0]["content"]
    assert cached_content[0]["type"] == "text"
    assert "raw bytes omitted" in cached_content[0]["text"]
    assert "abcdef" not in str(cached_content)
    assert "attachment_id=att1" in str(cached_content)


@pytest.mark.asyncio
async def test_slack_inject_uses_redis_and_skips_db(monkeypatch: pytest.MonkeyPatch) -> None:
    messenger = SlackMessenger()
    message = InboundMessage(
        external_user_id="U123",
        text="hi",
        message_type=MessageType.MENTION,
        message_id="1700000000.000000",
        messenger_context={"organization_id": str(uuid4()), "workspace_id": "T123", "channel_id": "C123", "channel_type": "channel"},
    )

    async def cached(**_kwargs: object) -> dict[str, object]:
        return {
            "formatted_context": "cached public channel context",
            "latest_ts": "1700000000.000000",
            "rendered_second": 9999999999,
            "dirty": False,
            "messages": [{"ts": "1700000000.000000", "text": "hi"}],
        }

    monkeypatch.setattr(slack_channel_context, "get_cached_channel_context", cached)
    monkeypatch.setattr(
        messenger,
        "_get_cached_channel_context_payload_from_activity",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("activity DB should not be read")),
    )

    await messenger._inject_recent_channel_context(message=message, workspace_id="T123", channel_id="C123")

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
        messenger_context={"organization_id": str(uuid4()), "workspace_id": "T123", "channel_id": "G123", "channel_type": "group"},
    )

    async def fail(**_kwargs: object) -> None:
        raise AssertionError("Redis should not be read for private/group channels")

    monkeypatch.setattr(slack_channel_context, "get_cached_channel_context", fail)
    await messenger._inject_recent_channel_context(message=message, workspace_id="T123", channel_id="G123")

    assert "workflow_context" not in message.messenger_context
