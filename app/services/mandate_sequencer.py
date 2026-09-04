"""Mandate retry sequencer — Track 03 official example direction.

Razorpay already retries failed subscription debits on T+1/T+2/T+3.
We add a *bounded* customer-facing sequence for mandate/bank-decline cases:
SMS → email → re-registration link → stop.

Does NOT replace Razorpay's auto-retry loop; layers diagnosis + stopping on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.intervention import Intervention


@dataclass(frozen=True)
class MandateStep:
    index: int
    delay_hours: int
    channel: str
    intent: str
    copy: str


# Bounded 3-step sequence (compliant — then stop)
MANDATE_SEQUENCE: tuple[MandateStep, ...] = (
    MandateStep(
        index=1,
        delay_hours=0,
        channel="sms",
        intent="immediate_debit_retry",
        copy="Aapka auto-debit fail ho gaya. Abhi retry karein ya bank balance check karein.",
    ),
    MandateStep(
        index=2,
        delay_hours=24,
        channel="email",
        intent="mandate_reminder",
        copy="Reminder: subscription debit still unpaid. Update card/UPI mandate if needed.",
    ),
    MandateStep(
        index=3,
        delay_hours=72,
        channel="email",
        intent="mandate_re_registration",
        copy="Final step: re-register eMandate / payment method. After this we stop nudging.",
    ),
)


def plan_for_attempt(attempt: int = 1) -> dict[str, Any]:
    """Return current step + full plan for audit/demo visibility."""
    total = len(MANDATE_SEQUENCE)
    idx = max(1, min(attempt, total))
    current = MANDATE_SEQUENCE[idx - 1]
    return {
        "action": "mandate_retry_sequence",
        "attempt": idx,
        "total_steps": total,
        "current": {
            "step": current.index,
            "delay_hours": current.delay_hours,
            "channel": current.channel,
            "intent": current.intent,
            "copy": current.copy,
        },
        "schedule": [
            {
                "step": s.index,
                "delay_hours": s.delay_hours,
                "channel": s.channel,
                "intent": s.intent,
            }
            for s in MANDATE_SEQUENCE
        ],
        "stop_after_step": total,
        "note": "Bounded sequencer - does not spam past step 3; Razorpay T+n retries stay separate.",
    }


def format_sequence_message(
    *,
    amount_rupees: float,
    payment_link_url: str | None,
    attempt: int = 1,
    customer_name: str = "Customer",
) -> str:
    plan = plan_for_attempt(attempt)
    cur = plan["current"]
    link = f"\n\nUpdate / pay: {payment_link_url}" if payment_link_url else ""
    schedule_lines = "\n".join(
        f"  Step {s['step']}: T+{s['delay_hours']}h · {s['channel']} · {s['intent']}"
        for s in plan["schedule"]
    )
    return (
        f"Hi {customer_name}, mandate/auto-debit failed for Rs {amount_rupees:.0f}.\n"
        f"[MANDATE SEQUENCE {cur['step']}/{plan['total_steps']} · {cur['channel']}]\n"
        f"{cur['copy']}{link}\n\n"
        f"Full plan (then stop):\n{schedule_lines}"
    )


def plan_for_intervention(db: Session, intervention: Intervention, audit: AuditEvent) -> dict[str, Any] | None:
    """Resolve which sequencer step this intervention represents."""
    if intervention.action != "mandate_retry_sequence":
        return None
    since = datetime.now(timezone.utc) - timedelta(hours=72)
    q = (
        db.query(Intervention)
        .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
        .filter(
            Intervention.action == "mandate_retry_sequence",
            Intervention.created_at >= since,
            Intervention.created_at <= intervention.created_at,
        )
    )
    if audit.customer_email:
        q = q.filter(AuditEvent.customer_email == audit.customer_email)
    elif audit.customer_contact:
        q = q.filter(AuditEvent.customer_contact == audit.customer_contact)
    attempt = max(1, q.count())
    return plan_for_attempt(attempt)
