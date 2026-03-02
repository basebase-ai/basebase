import asyncio
from types import SimpleNamespace

from connectors.slack import SlackConnector


def test_execute_action_send_message_can_initiate_dm_with_user_id(monkeypatch) -> None:
    connector = SlackConnector(organization_id="00000000-0000-0000-0000-000000000001")
    captured: dict[str, str] = {}

    async def _fake_send_direct_message(slack_user_id: str, text: str):
        captured["slack_user_id"] = slack_user_id
        captured["text"] = text
        return {"ok": True}

    monkeypatch.setattr(connector, "send_direct_message", _fake_send_direct_message)

    result = asyncio.run(
        connector.execute_action(
            "send_message",
            {"user_id": "U123", "text": "Hi from Penny"},
        )
    )

    assert result == {"ok": True}
    assert captured == {"slack_user_id": "U123", "text": "Hi from Penny"}


def test_execute_action_send_message_accepts_legacy_message_param(monkeypatch) -> None:
    connector = SlackConnector(organization_id="00000000-0000-0000-0000-000000000001")
    captured: dict[str, str] = {}

    async def _fake_post_message(channel: str, text: str, thread_ts: str | None = None):
        captured["channel"] = channel
        captured["text"] = text
        captured["thread_ts"] = thread_ts or ""
        return {"ok": True}

    monkeypatch.setattr(connector, "post_message", _fake_post_message)

    result = asyncio.run(
        connector.execute_action(
            "send_message",
            {"channel": "C123", "message": "Legacy text", "thread_ts": "111.222"},
        )
    )

    assert result == {"ok": True}
    assert captured == {"channel": "C123", "text": "Legacy text", "thread_ts": "111.222"}


def test_get_oauth_token_uses_inferred_team_bot_install(monkeypatch) -> None:
    connector = SlackConnector(organization_id="00000000-0000-0000-0000-000000000001")

    async def _fake_load_integration() -> None:
        connector._integration = SimpleNamespace(extra_data={"team_id": "T999"})

    async def _fake_get_slack_bot_token(organization_id: str, team_id: str) -> str | None:
        assert organization_id == "00000000-0000-0000-0000-000000000001"
        assert team_id == "T999"
        return "xoxb-bot-token"

    async def _fake_base_get_oauth_token() -> tuple[str, str]:
        raise AssertionError("base token fallback should not be used when bot token exists")

    monkeypatch.setattr(connector, "_load_integration", _fake_load_integration)
    monkeypatch.setattr("services.slack_bot_install.get_slack_bot_token", _fake_get_slack_bot_token)
    monkeypatch.setattr("connectors.base.BaseConnector.get_oauth_token", _fake_base_get_oauth_token)

    token, _ = asyncio.run(connector.get_oauth_token())

    assert token == "xoxb-bot-token"
    assert connector.team_id == "T999"


def test_post_message_retries_across_team_ids_on_channel_not_found(monkeypatch) -> None:
    connector = SlackConnector(organization_id="00000000-0000-0000-0000-000000000001")
    attempts: list[str] = []
    connector.team_id = None

    async def _fake_list_org_team_ids() -> list[str]:
        return ["T_WRONG", "T_RIGHT"]

    async def _fake_make_request(_method: str, endpoint: str, *, json_data=None, params=None):
        assert endpoint == "chat.postMessage"
        attempts.append(str(connector.team_id))
        if connector.team_id != "T_RIGHT":
            raise ValueError("Slack API error: channel_not_found")
        return {"ok": True, "channel": "C0AEA4J556F", "ts": "123.456", "message": {"text": "ok"}}

    monkeypatch.setattr(connector, "_list_org_team_ids", _fake_list_org_team_ids)
    monkeypatch.setattr(connector, "_make_request", _fake_make_request)

    result = asyncio.run(connector.post_message("C0AEA4J556F", "hello"))

    assert result["ok"] is True
    assert result["channel"] == "C0AEA4J556F"
    assert attempts == ["None", "T_WRONG", "T_RIGHT"]
    assert connector.team_id == "T_RIGHT"


def test_post_message_no_retry_when_team_id_already_set(monkeypatch) -> None:
    connector = SlackConnector(
        organization_id="00000000-0000-0000-0000-000000000001",
        team_id="T123",
    )

    async def _fake_make_request(_method: str, _endpoint: str, *, json_data=None, params=None):
        raise ValueError("Slack API error: channel_not_found")

    monkeypatch.setattr(connector, "_make_request", _fake_make_request)

    try:
        asyncio.run(connector.post_message("C0AEA4J556F", "hello"))
    except ValueError as exc:
        assert "channel_not_found" in str(exc)
    else:
        raise AssertionError("Expected channel_not_found to be raised")
