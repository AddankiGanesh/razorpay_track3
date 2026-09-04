"""ElevenLabs Conversational AI outbound calls (via Twilio-linked number)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def trigger_elevenlabs_outbound_call(
    *,
    to_phone: str | None,
    amount_rupees: float,
    customer_name: str = "Customer",
    payment_link_url: str | None = None,
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.elevenlabs_api_key or not settings.elevenlabs_agent_id:
        return None
    if not to_phone:
        return {"queued": False, "error": "no_phone"}

    payload: dict[str, Any] = {
        "agent_id": settings.elevenlabs_agent_id,
        "to_number": to_phone,
    }
    if settings.elevenlabs_agent_phone_number_id:
        payload["agent_phone_number_id"] = settings.elevenlabs_agent_phone_number_id

    payload["conversation_initiation_client_data"] = {
        "dynamic_variables": {
            "customer_name": customer_name,
            "amount_rupees": str(int(amount_rupees)),
            "payment_link": payment_link_url or "",
        }
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.elevenlabs.io/v1/convai/twilio/outbound-call",
                headers={
                    "xi-api-key": settings.elevenlabs_api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if resp.status_code >= 400:
            logger.error("ElevenLabs outbound failed %s: %s", resp.status_code, resp.text[:300])
            return {"queued": False, "error": resp.text, "channel": "voice"}
        data = resp.json()
        logger.info("[VOICE:ELEVENLABS] call queued to=%s id=%s", to_phone, data.get("conversation_id"))
        return {
            "queued": True,
            "simulated": False,
            "channel": "voice",
            "provider": "elevenlabs",
            "destination": to_phone,
            "conversation_id": data.get("conversation_id"),
        }
    except Exception as exc:
        logger.exception("ElevenLabs error: %s", exc)
        return {"queued": False, "error": str(exc), "channel": "voice"}
