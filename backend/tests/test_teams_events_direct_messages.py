import asyncio

from api.routes import teams_events
from api.routes.teams_events import _build_inbound_message
from messengers.base import MessageType
from messengers.teams import TeamsMessenger


def test_build_inbound_message_sets_channel_type_for_personal_chat() -> None:
    activity = {
        "id": "activity-1",
        "text": "hello bot",
        "from": {"id": "29:user", "aadObjectId": "aad-1"},
        "recipient": {"id": "28:bot"},
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "conversation": {
            "id": "19:conversation",
            "conversationType": "personal",
            "isGroup": False,
        },
        "channelData": {"tenant": {"id": "tenant-1"}},
    }

    message = _build_inbound_message(activity, MessageType.DIRECT)

    assert message.message_type == MessageType.DIRECT
    assert message.messenger_context["channel_type"] == "personal"
    assert message.messenger_context["workspace_id"] == "tenant-1"


def test_process_message_activity_records_failure_when_processing_raises(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_process_inbound(self, _message):
        raise RuntimeError("teams forced failure")

    async def _fake_record_query_outcome(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(TeamsMessenger, "process_inbound", _fake_process_inbound)
    monkeypatch.setattr(
        "services.query_outcome_metrics.record_query_outcome",
        _fake_record_query_outcome,
    )

    activity = {
        "id": "activity-2",
        "type": "message",
        "text": "hello bot",
        "from": {"id": "29:user", "aadObjectId": "aad-1"},
        "recipient": {"id": "28:bot"},
        "conversation": {
            "id": "19:conversation",
            "conversationType": "personal",
            "isGroup": False,
        },
        "channelData": {"tenant": {"id": "tenant-1"}},
    }

    asyncio.run(teams_events._process_message_activity(activity))

    assert captured["platform"] == "teams"
    assert captured["was_success"] is False
    assert captured["conversation_id"] == "19:conversation:activity-2"
    assert captured["failure_reason"] == "teams forced failure"


def test_process_message_activity_persists_only_public_channel_messages(monkeypatch) -> None:
    persisted: list[str] = []

    async def _fake_persist_activity(message, _tenant_id: str) -> None:
        persisted.append(message.messenger_context.get("channel_type") or "")

    async def _fake_process_inbound(self, _message):
        return {"status": "success"}

    async def _run(activity: dict[str, object]) -> None:
        await teams_events._process_message_activity(activity)
        await asyncio.sleep(0)

    monkeypatch.setattr(teams_events, "_persist_activity", _fake_persist_activity)
    monkeypatch.setattr(TeamsMessenger, "process_inbound", _fake_process_inbound)

    standard_channel_activity = {
        "id": "activity-public-1",
        "type": "message",
        "text": "hello public channel",
        "from": {"id": "29:user", "aadObjectId": "aad-1"},
        "recipient": {"id": "28:bot"},
        "conversation": {
            "id": "19:conversation",
            "conversationType": "channel",
            "isGroup": True,
        },
        "channelData": {
            "tenant": {"id": "tenant-1"},
            "channel": {"membershipType": "standard"},
        },
    }
    private_channel_activity = {
        "id": "activity-private-1",
        "type": "message",
        "text": "hello private channel",
        "from": {"id": "29:user", "aadObjectId": "aad-1"},
        "recipient": {"id": "28:bot"},
        "conversation": {
            "id": "19:conversation-private",
            "conversationType": "channel",
            "isGroup": True,
        },
        "channelData": {
            "tenant": {"id": "tenant-1"},
            "channel": {"membershipType": "private"},
        },
    }
    personal_chat_activity = {
        "id": "activity-personal-1",
        "type": "message",
        "text": "hello direct chat",
        "from": {"id": "29:user", "aadObjectId": "aad-1"},
        "recipient": {"id": "28:bot"},
        "conversation": {
            "id": "19:conversation-personal",
            "conversationType": "personal",
            "isGroup": False,
        },
        "channelData": {"tenant": {"id": "tenant-1"}},
    }

    asyncio.run(_run(standard_channel_activity))
    asyncio.run(_run(private_channel_activity))
    asyncio.run(_run(personal_chat_activity))

    assert persisted == ["channel"]


def test_refresh_jwks_fetches_only_botframework_openid(monkeypatch) -> None:
    called_urls: list[str] = []

    async def _fake_fetch_jwks_from_openid(_client, openid_url: str):
        called_urls.append(openid_url)
        return [{"kid": "kid-1", "kty": "RSA", "n": "n", "e": "AQAB"}]

    async def _run() -> None:
        teams_events._merged_jwks_keys = []
        teams_events._jwks_fetched_at = 0.0
        await teams_events._refresh_jwks()

    monkeypatch.setattr(teams_events, "_fetch_jwks_from_openid", _fake_fetch_jwks_from_openid)
    asyncio.run(_run())

    assert called_urls == [teams_events.BOT_OPENID_URL]


def test_verify_teams_jwt_rejects_unexpected_issuer(monkeypatch) -> None:
    class _FakeJwk:
        def to_pem(self) -> bytes:
            return b"fake-pem"

    monkeypatch.setattr(teams_events.settings, "MICROSOFT_APP_ID", "app-id", raising=False)
    monkeypatch.setattr(teams_events.jwt, "get_unverified_header", lambda _token: {"kid": "kid-1"})
    monkeypatch.setattr(teams_events.jwk, "construct", lambda *_args, **_kwargs: _FakeJwk())
    monkeypatch.setattr(
        teams_events.jwt,
        "decode",
        lambda *_args, **_kwargs: {"aud": "app-id", "exp": 9999999999, "iss": "https://evil.example"},
    )

    teams_events._merged_jwks_keys = [{"kid": "kid-1"}]

    try:
        teams_events._verify_teams_jwt("fake-token")
        assert False, "Expected ValueError for unexpected issuer"
    except ValueError as exc:
        assert "Unexpected token issuer" in str(exc)
