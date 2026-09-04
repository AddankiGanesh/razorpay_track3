"""Hinglish voice recovery — ElevenLabs agent preferred, Twilio/IVR fallback."""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.services.elevenlabs_voice import trigger_elevenlabs_outbound_call

logger = logging.getLogger(__name__)

VOICE_MIN_AMOUNT_PAISE = 10000


def should_use_voice(*, amount_paise: int, action: str) -> bool:
    if action == "halted_revival_job":
        return True
    if action == "regenerate_payment_link" and amount_paise >= VOICE_MIN_AMOUNT_PAISE:
        return True
    return False


def build_hinglish_ivr_script(
    *,
    amount_rupees: float,
    payment_link_url: str | None,
    customer_name: str = "Customer",
) -> str:
    link = payment_link_url or "payment link SMS mein bhej diya hai"
    return (
        f"Namaste {customer_name}. Aapki subscription band ho gayi hai. "
        f"Service restore karne ke liye bas {amount_rupees:.0f} rupaye pay karein. "
        f"Pay karne ke liye 1 dabaye. Link: {link}. "
        f"Abhi nahi to 2 dabaye — hum baad mein yaad dilayenge."
    )


def trigger_voice_recovery(
    *,
    to_phone: str | None,
    amount_paise: int,
    payment_link_url: str | None,
    customer_name: str = "Customer",
    action: str,
) -> dict[str, Any]:
    if not should_use_voice(amount_paise=amount_paise, action=action):
        return {"queued": False, "reason": "below_threshold_or_wrong_action"}

    # 1) ElevenLabs AI agent call (requires ElevenLabs + Twilio-linked number)
    el = trigger_elevenlabs_outbound_call(
        to_phone=to_phone,
        amount_rupees=amount_paise / 100,
        customer_name=customer_name,
        payment_link_url=payment_link_url,
    )
    if el and el.get("queued"):
        return el

    script = build_hinglish_ivr_script(
        amount_rupees=amount_paise / 100,
        payment_link_url=payment_link_url,
        customer_name=customer_name,
    )
    settings = get_settings()
    twilio_sid = settings.twilio_account_sid or ""
    if twilio_sid and settings.twilio_from_number:
        try:
            import httpx

            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Calls.json",
                    auth=(twilio_sid, settings.twilio_auth_token),
                    data={
                        "To": to_phone,
                        "From": settings.twilio_from_number,
                        "Twiml": f"<Response><Say>{script[:500]}</Say></Response>",
                    },
                )
            if resp.status_code < 400:
                data = resp.json()
                return {
                    "queued": True,
                    "simulated": False,
                    "channel": "voice",
                    "provider": "twilio",
                    "destination": to_phone,
                    "call_sid": data.get("sid"),
                }
        except Exception as exc:
            logger.warning("Twilio voice failed: %s", exc)

    logger.info("[VOICE:HINGLISH] to=%s (simulated)\n%s", to_phone or "unknown", script)
    return {
        "queued": True,
        "simulated": True,
        "channel": "voice",
        "destination": to_phone,
        "script": script,
        "note": "Add ELEVENLABS_* or TWILIO_* for live calls",
    }
