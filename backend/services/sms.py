"""
SMS service for sending text messages.

Uses Twilio for SMS delivery. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
and TWILIO_PHONE_NUMBER in environment.
"""
from __future__ import annotations

import base64
import json
from typing import Optional
from urllib.parse import urlencode

import httpx

from config import settings

# #region agent log
_DEBUG_LOG_PATH: str = "/Users/teg/Documents/basebase/basebase/.cursor/debug-f1ce5e.log"
# #endregion


async def send_sms(
    to: str,
    body: str,
    from_number: Optional[str] = None,
    media_urls: Optional[list[str]] = None,
    whatsapp: bool = False,
    allow_unverified: bool = False,
) -> dict[str, str | bool]:
    """
    Send an SMS (or MMS with media) via Twilio.

    Args:
        to: Recipient phone number (E.164 format, e.g., +14155551234)
        body: Message text (max 1600 characters)
        from_number: Optional from number (defaults to TWILIO_PHONE_NUMBER)
        media_urls: Optional list of public URLs for MMS media (up to 10)
        allow_unverified: If False, refuse to send when "to" is a user's unverified profile number.

    Returns:
        Dict with status, message_sid on success, or error on failure
    """
    account_sid = settings.TWILIO_ACCOUNT_SID if hasattr(settings, 'TWILIO_ACCOUNT_SID') else None
    auth_token = settings.TWILIO_AUTH_TOKEN if hasattr(settings, 'TWILIO_AUTH_TOKEN') else None
    default_from = settings.TWILIO_PHONE_NUMBER if hasattr(settings, 'TWILIO_PHONE_NUMBER') else None
    
    if not account_sid or not auth_token:
        print(f"[SMS] Twilio not configured, skipping SMS to {to}")
        return {
            "success": False,
            "error": "Twilio not configured. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN.",
        }
    
    from_phone = from_number or default_from
    if not from_phone:
        return {
            "success": False,
            "error": "No from number specified and TWILIO_PHONE_NUMBER not set.",
        }

    if not allow_unverified:
        to_stripped: str = (to or "").strip()
        if to_stripped:
            from models.database import get_admin_session
            from models.user import User
            from sqlalchemy import select
            async with get_admin_session() as session:
                result = await session.execute(
                    select(User).where(User.phone_number == to_stripped)
                )
                user_with_number = result.scalar_one_or_none()
                if user_with_number is not None and user_with_number.phone_number_verified_at is None:
                    return {
                        "success": False,
                        "error": "That phone number has not been verified. The recipient must verify their number in Profile → Notification preferences before receiving SMS from Basebase.",
                    }
    # #region agent log
    try:
        _dig: str = "".join(c for c in from_phone if c.isdigit())
        _last4: str = _dig[-4:] if len(_dig) >= 4 else _dig
        open(_DEBUG_LOG_PATH, "a").write(
            json.dumps(
                {
                    "sessionId": "f1ce5e",
                    "hypothesisId": "A,B,D,E",
                    "location": "services/sms.py:send_sms",
                    "message": "SMS send attempt",
                    "data": {
                        "from_last4": _last4,
                        "used_default_from": from_number is None,
                        "from_len": len(from_phone),
                        "from_has_plus": from_phone.startswith("+"),
                    },
                    "timestamp": __import__("time").time() * 1000,
                }
            ) + "\n"
        )
    except Exception:
        pass
    # #endregion

    # Truncate body if too long
    if len(body) > 1600:
        body = body[:1597] + "..."
    
    # Build auth header
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    
    async with httpx.AsyncClient() as client:
        try:
            # Build form params — use list of tuples + urlencode(doseq=True)
            # so we can repeat the MediaUrl key for multiple MMS attachments
            to_value: str = f"whatsapp:{to}" if whatsapp else to
            from_value: str = f"whatsapp:{from_phone}" if whatsapp else from_phone
            params: list[tuple[str, str]] = [
                ("To", to_value),
                ("From", from_value),
                ("Body", body),
            ]
            # Twilio accepts up to 10 repeated MediaUrl params for MMS
            if media_urls:
                for murl in media_urls[:10]:
                    params.append(("MediaUrl", murl))

            response = await client.post(
                url,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                content=urlencode(params, doseq=True),
                timeout=10.0,
            )
            
            if response.status_code in (200, 201):
                data = response.json()
                print(f"[SMS] Sent to {to}: {data.get('sid')}")
                return {
                    "success": True,
                    "message_sid": data.get("sid"),
                    "status": data.get("status"),
                }
            else:
                error_data = response.json()
                error_msg = error_data.get("message", response.text)
                # #region agent log
                try:
                    open(_DEBUG_LOG_PATH, "a").write(
                        json.dumps(
                            {
                                "sessionId": "f1ce5e",
                                "hypothesisId": "C",
                                "location": "services/sms.py:send_sms",
                                "message": "Twilio API error",
                                "data": {
                                    "status_code": response.status_code,
                                    "error_code": error_data.get("code"),
                                    "error_message": error_msg,
                                },
                                "timestamp": __import__("time").time() * 1000,
                            }
                        ) + "\n"
                    )
                except Exception:
                    pass
                # #endregion
                print(f"[SMS] Failed to send to {to}: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                }
                
        except Exception as e:
            print(f"[SMS] Error sending to {to}: {e}")
            return {
                "success": False,
                "error": str(e),
            }
