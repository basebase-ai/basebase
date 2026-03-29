from __future__ import annotations

from urllib.parse import parse_qs

import pytest

from services.automated_agent_footer import AUTOMATED_AGENT_FOOTER
from services.email import send_email
from services.sms import send_sms


@pytest.mark.asyncio
async def test_send_email_applies_footer_right_before_send(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_payload: dict[str, object] = {}

    class _MockResponse:
        status_code = 200
        text = "ok"

    class _MockClient:
        async def __aenter__(self) -> _MockClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url: str, headers: dict[str, str], json: dict[str, object], timeout: float) -> _MockResponse:
            captured_payload.update(json)
            return _MockResponse()

    monkeypatch.setattr("services.email.settings.RESEND_API_KEY", "test-key")
    monkeypatch.setattr("services.email.httpx.AsyncClient", _MockClient)

    success = await send_email(
        to="test@example.com",
        subject="subject",
        body="Hello there",
    )

    assert success is True
    sent_text = str(captured_payload["text"])
    sent_html = str(captured_payload["html"])
    assert AUTOMATED_AGENT_FOOTER in sent_text
    assert AUTOMATED_AGENT_FOOTER in sent_html


@pytest.mark.asyncio
async def test_send_sms_applies_footer_right_before_send(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_content: str = ""

    class _MockResponse:
        status_code = 201

        @staticmethod
        def json() -> dict[str, str]:
            return {"sid": "SM123", "status": "queued"}

    class _MockClient:
        async def __aenter__(self) -> _MockClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, url: str, headers: dict[str, str], content: str, timeout: float) -> _MockResponse:
            nonlocal captured_content
            captured_content = content
            return _MockResponse()

    monkeypatch.setattr("services.sms.settings.TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr("services.sms.settings.TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setattr("services.sms.settings.TWILIO_PHONE_NUMBER", "+15550001111")
    monkeypatch.setattr("services.sms.httpx.AsyncClient", _MockClient)

    result = await send_sms(
        to="+15550002222",
        body="Hello via SMS",
        allow_unverified=True,
    )

    assert result["success"] is True
    body_values = parse_qs(captured_content).get("Body", [])
    assert body_values, "Body should be present in Twilio form payload"
    assert AUTOMATED_AGENT_FOOTER in body_values[0]
