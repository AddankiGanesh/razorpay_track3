"""Process due scheduled recovery actions (promise reminder emails)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.intervention import Intervention
from app.models.scheduled_action import ScheduledAction
from app.services.notifications import send_recovery_notification

logger = logging.getLogger(__name__)


def process_due_actions(db: Session, *, limit: int = 20) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    rows = (
        db.query(ScheduledAction)
        .filter(ScheduledAction.status == "pending", ScheduledAction.run_at <= now)
        .order_by(ScheduledAction.run_at.asc())
        .limit(limit)
        .all()
    )
    sent = 0
    cancelled = 0
    for row in rows:
        if row.action_type != "reminder_email":
            row.status = "cancelled"
            row.result_note = "unsupported_action"
            cancelled += 1
            continue

        payload = {}
        if row.payload_json:
            try:
                payload = json.loads(row.payload_json)
            except json.JSONDecodeError:
                payload = {}

        intervention = db.get(Intervention, row.intervention_id) if row.intervention_id else None
        if intervention and intervention.status == "recovered":
            row.status = "cancelled"
            row.result_note = "already_recovered"
            cancelled += 1
            continue

        result = send_recovery_notification(
            channel="email",
            to_email=payload.get("to_email"),
            to_phone=payload.get("to_phone"),
            subject=payload.get("subject", "Reminder: complete your payment"),
            body=payload.get("body", "Your promised payment date is here. Please complete payment."),
            payment_link_url=payload.get("payment_link_url"),
        )
        row.sent_at = now
        if result.get("sent"):
            row.status = "sent"
            row.result_note = f"email:{result.get('provider_id', 'ok')}"
            sent += 1
            if intervention:
                intervention.message = (intervention.message or "") + "\n\n[REMINDER SENT]"
        else:
            row.status = "sent"
            row.result_note = result.get("note") or result.get("error") or "logged_stub"
            sent += 1

    if sent or cancelled:
        db.commit()
    return {"processed": len(rows), "sent": sent, "cancelled": cancelled}
