"""Late authorisation handler — wait/poll instead of customer spam."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.intervention import Intervention

logger = logging.getLogger(__name__)


def handle_late_auth(
    db: Session,
    *,
    audit: AuditEvent,
    payment_id: str | None,
    amount_paise: int,
) -> dict[str, Any]:
    """
    Razorpay late auth: payment may succeed after customer left.
    Do NOT nudge customer yet — watch for capture / order.paid.
    """
    audit.recommended_action = "wait_and_poll_late_auth"
    audit.status = "watching_late_auth"
    iv = Intervention(
        audit_event_id=audit.id,
        action="wait_and_poll",
        channel="system",
        message=(
            f"Late auth watch on {payment_id or 'payment'}: "
            f"Rs {amount_paise / 100:.0f}. Suppressing customer nudges; waiting for capture."
        ),
        status="watching",
        amount_at_risk_paise=amount_paise,
    )
    db.add(iv)
    db.commit()
    db.refresh(iv)
    logger.info("Late-auth watch started for payment %s", payment_id)
    return {
        "action": "wait_and_poll_late_auth",
        "intervention_id": iv.id,
        "ok": True,
        "note": "Customer nudge suppressed until capture or timeout",
    }
