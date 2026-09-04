"""Auto-capture differentiator — capture authorized payments that merchants miss."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.services.razorpay_client import get_razorpay_client

logger = logging.getLogger(__name__)


def try_auto_capture(
    db: Session,
    *,
    audit: AuditEvent,
    payment_id: str,
    amount_paise: int,
) -> dict[str, Any]:
    """
    When payment.authorized fires, attempt capture via Razorpay API.
    This recovers money that would otherwise sit authorized-but-uncaptured.
    """
    client = get_razorpay_client()
    result: dict[str, Any] = {
        "action": "auto_capture",
        "payment_id": payment_id,
        "ok": False,
    }
    try:
        captured = client.payment.capture(payment_id, amount_paise)
        result["ok"] = True
        result["status"] = captured.get("status")
        result["captured_amount"] = captured.get("amount")
        logger.info("Auto-captured payment %s amount=%s", payment_id, amount_paise)
        audit.recommended_action = "auto_capture_succeeded"
        audit.status = "recovered"
        iv = Intervention(
            audit_event_id=audit.id,
            action="auto_capture",
            channel="system",
            message=f"Auto-captured Rs {amount_paise / 100:.0f} for payment {payment_id}",
            status="recovered",
            amount_at_risk_paise=amount_paise,
            amount_recovered_paise=amount_paise,
            recovered_payment_id=payment_id,
        )
        db.add(iv)
        db.commit()
        result["intervention_id"] = iv.id
    except Exception as exc:
        # Already captured or capture not allowed — log and watch
        msg = str(exc).lower()
        if "already" in msg or "captured" in msg:
            audit.recommended_action = "already_captured"
            audit.status = "recovered"
            result["ok"] = True
            result["note"] = "already_captured"
        else:
            audit.recommended_action = "auto_capture_failed_watch"
            audit.status = "detected"
            result["error"] = str(exc)
            logger.warning("Auto-capture failed for %s: %s", payment_id, exc)
            iv = Intervention(
                audit_event_id=audit.id,
                action="auto_capture",
                channel="system",
                message=f"Auto-capture failed for {payment_id}: {exc}",
                status="sent_no_link",
                amount_at_risk_paise=amount_paise,
            )
            db.add(iv)
        db.commit()
    return result
