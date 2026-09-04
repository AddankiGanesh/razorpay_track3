"""Outbound notifications — Resend email when configured, else clear log stub."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_recovery_notification(
    *,
    channel: str,
    to_email: str | None,
    to_phone: str | None,
    subject: str,
    body: str,
    payment_link_url: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    destination = to_email if channel == "email" else (to_phone or to_email)

    if channel == "sms" and to_phone and settings.twilio_account_sid and settings.twilio_auth_token:
        return _send_twilio_sms(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            from_number=settings.twilio_from_number,
            to_phone=to_phone,
            body=body,
        )

    # Prefer email delivery when we have an address (even if channel is sms in rules)
    email_to = to_email
    if email_to and settings.resend_api_key:
        result = _send_resend(
            api_key=settings.resend_api_key,
            from_email=settings.resend_from_email,
            to_email=email_to,
            subject=subject,
            body=body,
            payment_link_url=payment_link_url,
        )
        return result

    logger.info(
        "[NOTIFY:%s] to=%s subject=%s link=%s (simulated — set RESEND_API_KEY or TWILIO_* for live delivery)",
        channel.upper(),
        destination or "unknown",
        subject,
        payment_link_url or "none",
    )
    logger.info("[NOTIFY:BODY] %s", (body or "")[:500])
    note = (
        "Logged only — add TWILIO_* for SMS or RESEND_API_KEY for email"
        if channel == "sms"
        else "Logged only — add RESEND_API_KEY to .env for real email delivery"
    )
    return {
        "sent": False,
        "simulated": True,
        "channel": channel,
        "destination": destination,
        "note": note,
    }


def _send_resend(
    *,
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    payment_link_url: str | None,
) -> dict[str, Any]:
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto">
      <h2 style="color:#0f172a">RevRecover</h2>
      <p style="white-space:pre-wrap;color:#334155">{body}</p>
      {f'<p><a href="{payment_link_url}" style="background:#0ea5e9;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;display:inline-block">Complete payment</a></p>' if payment_link_url else ''}
      <p style="color:#94a3b8;font-size:12px">Automated recovery message from RevRecover (Razorpay Buildathon).</p>
    </div>
    """
    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html,
        "text": body,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        if resp.status_code >= 400:
            logger.error("Resend failed %s: %s", resp.status_code, resp.text)
            return {
                "sent": False,
                "simulated": False,
                "channel": "email",
                "destination": to_email,
                "error": resp.text,
            }
        data = resp.json()
        logger.info("[NOTIFY:EMAIL] sent to=%s id=%s", to_email, data.get("id"))
        return {
            "sent": True,
            "simulated": False,
            "channel": "email",
            "destination": to_email,
            "provider_id": data.get("id"),
        }
    except Exception as exc:
        logger.exception("Resend error: %s", exc)
        return {
            "sent": False,
            "simulated": False,
            "channel": "email",
            "destination": to_email,
            "error": str(exc),
        }


def _send_twilio_sms(
    *,
    account_sid: str,
    auth_token: str,
    from_number: str,
    to_phone: str,
    body: str,
) -> dict[str, Any]:
    if not from_number:
        logger.warning("[NOTIFY:SMS] TWILIO_FROM_NUMBER missing — logging only")
        return {
            "sent": False,
            "simulated": True,
            "channel": "sms",
            "destination": to_phone,
            "note": "Set TWILIO_FROM_NUMBER for live SMS",
        }
    try:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                auth=(account_sid, auth_token),
                data={"From": from_number, "To": to_phone, "Body": (body or "")[:1500]},
            )
        if resp.status_code >= 400:
            logger.error("Twilio SMS failed %s: %s", resp.status_code, resp.text)
            return {
                "sent": False,
                "simulated": False,
                "channel": "sms",
                "destination": to_phone,
                "error": resp.text,
            }
        data = resp.json()
        logger.info("[NOTIFY:SMS] sent to=%s sid=%s", to_phone, data.get("sid"))
        return {
            "sent": True,
            "simulated": False,
            "channel": "sms",
            "destination": to_phone,
            "provider_id": data.get("sid"),
        }
    except Exception as exc:
        logger.exception("Twilio SMS error: %s", exc)
        return {
            "sent": False,
            "simulated": False,
            "channel": "sms",
            "destination": to_phone,
            "error": str(exc),
        }
