"""
Phone number verification via Twilio Verify API.

Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_VERIFY_SERVICE_SID.
"""
from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


def _verify_api_headers() -> Optional[dict[str, str]]:
    account_sid: Optional[str] = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    auth_token: Optional[str] = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    if not account_sid or not auth_token:
        return None
    credentials: str = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


async def request_phone_verification(phone_number: str) -> tuple[bool, str]:
    """
    Send a verification code via SMS to the given E.164 number.
    Returns (success, error_message).
    """
    service_sid: Optional[str] = getattr(settings, "TWILIO_VERIFY_SERVICE_SID", None)
    if not service_sid:
        return False, "Phone verification is not configured (TWILIO_VERIFY_SERVICE_SID)."
    headers: Optional[dict[str, str]] = _verify_api_headers()
    if not headers:
        return False, "Twilio is not configured."
    url: str = f"https://verify.twilio.com/v2/Services/{service_sid}/Verifications"
    payload: dict[str, str] = {"To": phone_number, "Channel": "sms"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, data=payload, timeout=10.0)
            if resp.status_code in (200, 201):
                return True, ""
            data = resp.json()
            msg: str = data.get("message", resp.text) or f"HTTP {resp.status_code}"
            return False, msg
        except Exception as e:
            logger.exception("Twilio Verify request failed: %s", e)
            return False, str(e)


async def check_phone_verification(phone_number: str, code: str) -> tuple[bool, str]:
    """
    Check the verification code for the given E.164 number.
    Returns (success, error_message).
    """
    service_sid: Optional[str] = getattr(settings, "TWILIO_VERIFY_SERVICE_SID", None)
    if not service_sid:
        return False, "Phone verification is not configured."
    headers: Optional[dict[str, str]] = _verify_api_headers()
    if not headers:
        return False, "Twilio is not configured."
    url = f"https://verify.twilio.com/v2/Services/{service_sid}/VerificationCheck"
    payload: dict[str, str] = {"To": phone_number, "Code": code.strip()}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, headers=headers, data=payload, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "approved":
                    return True, ""
                return False, data.get("message", "Verification failed.")
            data = resp.json()
            return False, data.get("message", resp.text) or f"HTTP {resp.status_code}"
        except Exception as e:
            logger.exception("Twilio Verify check failed: %s", e)
            return False, str(e)
