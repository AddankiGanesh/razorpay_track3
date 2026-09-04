"""Promise-to-pay tracker — suppress nudges until promised date."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.services.promise_parser import parse_customer_promise


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromiseToPay(Base):
    __tablename__ = "promises_to_pay"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_event_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    intervention_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    customer_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    promised_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | fulfilled | broken | superseded | cleared
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def record_promise(
    db: Session,
    *,
    text: str,
    customer_email: str | None,
    customer_contact: str | None = None,
    audit_event_id: str | None = None,
    intervention_id: str | None = None,
    source_channel: str = "reply",
    payment_link_url: str | None = None,
    amount_rupees: float | None = None,
) -> tuple[PromiseToPay, dict]:
    parsed = parse_customer_promise(text)
    promised = parsed["promised_date"]

    q = db.query(PromiseToPay).filter(PromiseToPay.status == "active")
    if intervention_id:
        q = q.filter(PromiseToPay.intervention_id == intervention_id)
    elif customer_email:
        q = q.filter(PromiseToPay.customer_email == customer_email)
    elif customer_contact:
        q = q.filter(PromiseToPay.customer_contact == customer_contact)
    for row in q.all():
        row.status = "superseded"

    promise = PromiseToPay(
        audit_event_id=audit_event_id,
        intervention_id=intervention_id,
        customer_email=customer_email,
        customer_contact=customer_contact,
        promised_date=promised,
        raw_text=parsed.get("raw_text") or text,
        parsed_by=parsed.get("parsed_by"),
        source_channel=source_channel,
        status="active",
    )
    db.add(promise)
    db.flush()

    from app.models.scheduled_action import ScheduledAction

    reminder_body = (
        f"Hi, this is a reminder for your promised payment"
        f"{f' of Rs {amount_rupees:.0f}' if amount_rupees else ''}. "
        f"Please complete payment when ready."
    )
    scheduled = ScheduledAction(
        intervention_id=intervention_id,
        audit_event_id=audit_event_id,
        promise_id=promise.id,
        action_type="reminder_email",
        run_at=promised,
        status="pending",
        payload_json=json.dumps(
            {
                "to_email": customer_email,
                "to_phone": customer_contact,
                "subject": f"Reminder: complete your Rs {amount_rupees:.0f} payment" if amount_rupees else "Payment reminder",
                "body": reminder_body,
                "payment_link_url": payment_link_url,
            }
        ),
    )
    db.add(scheduled)
    db.commit()
    db.refresh(promise)
    return promise, {
        "parsed_by": parsed.get("parsed_by"),
        "confidence": parsed.get("confidence"),
        "scheduled_action_id": scheduled.id,
        "scheduled_at": scheduled.run_at.isoformat(),
    }


def active_promise_blocks_nudge(
    db: Session,
    *,
    customer_email: str | None,
    customer_contact: str | None = None,
    order_id: str | None = None,
    intervention_id: str | None = None,
) -> PromiseToPay | None:
    """Return active promise if nudges should be suppressed."""
    now = utcnow()
    q = db.query(PromiseToPay).filter(PromiseToPay.status == "active", PromiseToPay.promised_date > now)
    if intervention_id:
        q = q.filter(PromiseToPay.intervention_id == intervention_id)
    elif customer_email:
        q = q.filter(PromiseToPay.customer_email == customer_email)
    elif customer_contact:
        q = q.filter(PromiseToPay.customer_contact == customer_contact)
    else:
        return None
    return q.order_by(PromiseToPay.promised_date.desc()).first()
