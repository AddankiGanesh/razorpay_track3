"""Stopping rules — compliant nudge caps and suppress-after-recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.models.promise import active_promise_blocks_nudge

ACTION_MAX_NUDGES: dict[str, int] = {
    "soft_nudge_once": 1,
    "retry_with_new_otp": 2,
    "retry_immediate": 2,
    "retry_delayed": 2,
    "retry_with_urgency": 2,
    "suggest_alternate_method": 2,
    "delay_retry": 2,
    "proactive_customer_nudge": 2,
    "halted_revival_job": 2,
    "regenerate_payment_link": 2,
    "mandate_retry_sequence": 3,
    "educational_nudge": 1,
}

DEFAULT_MAX_NUDGES = 2
LOOKBACK_HOURS = 72
SOFT_ONCE_ACTIONS = {"soft_nudge_once"}


@dataclass
class StoppingDecision:
    allow: bool
    reason: str
    prior_count: int = 0
    max_allowed: int = DEFAULT_MAX_NUDGES


def _window_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)


def evaluate_stopping_rules(
    db: Session,
    *,
    audit: AuditEvent | None = None,
    action: str,
    customer_email: str | None = None,
    customer_contact: str | None = None,
    amount_paise: int | None = None,
) -> StoppingDecision:
    """Return whether a new intervention is allowed."""
    max_allowed = ACTION_MAX_NUDGES.get(action, DEFAULT_MAX_NUDGES)
    since = _window_start()
    settings = get_settings()

    order_id = audit.order_id if audit else None
    email = (audit.customer_email if audit else None) or customer_email
    contact = (audit.customer_contact if audit else None) or customer_contact
    amount = (audit.amount_paise if audit else None) or amount_paise

    # Promise-to-pay: suppress until promised date
    promise = active_promise_blocks_nudge(db, customer_email=email, customer_contact=contact)
    if promise:
        return StoppingDecision(
            allow=False,
            reason=f"promise_to_pay_until_{promise.promised_date.isoformat()}",
            prior_count=0,
            max_allowed=0,
        )

    # Never nudge if this order already recovered
    if order_id:
        recovered = (
            db.query(Intervention)
            .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
            .filter(AuditEvent.order_id == order_id, Intervention.status == "recovered")
            .first()
        )
        if recovered:
            return StoppingDecision(
                allow=False,
                reason="order_already_recovered",
                prior_count=1,
                max_allowed=max_allowed,
            )

    # Soft nudge once per customer (any order)
    if email and action in SOFT_ONCE_ACTIONS:
        soft = (
            db.query(Intervention)
            .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
            .filter(
                AuditEvent.customer_email == email,
                Intervention.action.in_(list(SOFT_ONCE_ACTIONS)),
                Intervention.created_at >= since,
            )
            .count()
        )
        if soft >= 1:
            return StoppingDecision(
                allow=False,
                reason="soft_nudge_already_sent",
                prior_count=soft,
                max_allowed=1,
            )

    q = (
        db.query(Intervention)
        .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
        .filter(Intervention.created_at >= since)
    )

    # Per-order limits — each Lab payment failure gets a unique order_id
    if order_id and settings.stopping_use_per_order_limits:
        prior = q.filter(AuditEvent.order_id == order_id).count()
        if prior >= max_allowed:
            return StoppingDecision(
                allow=False,
                reason=f"max_nudges_reached ({prior}/{max_allowed})",
                prior_count=prior,
                max_allowed=max_allowed,
            )
        return StoppingDecision(
            allow=True,
            reason="allowed",
            prior_count=prior,
            max_allowed=max_allowed,
        )

    if email and amount is not None:
        prior = q.filter(
            AuditEvent.customer_email == email,
            AuditEvent.amount_paise == amount,
            Intervention.action == action,
        ).count()
    elif email:
        prior = q.filter(AuditEvent.customer_email == email).count()
    elif contact and amount is not None:
        prior = q.filter(
            AuditEvent.customer_contact == contact,
            AuditEvent.amount_paise == amount,
            Intervention.action == action,
        ).count()
    else:
        prior = 0

    # Global customer cap (subscription/B2B without order_id)
    if email:
        customer_total = (
            db.query(Intervention)
            .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
            .filter(AuditEvent.customer_email == email, Intervention.created_at >= since)
            .count()
        )
        if customer_total >= settings.stopping_global_email_cap:
            return StoppingDecision(
                allow=False,
                reason=f"max_nudges_reached_{settings.stopping_global_email_cap}",
                prior_count=customer_total,
                max_allowed=settings.stopping_global_email_cap,
            )

    if prior >= max_allowed:
        return StoppingDecision(
            allow=False,
            reason=f"max_nudges_reached ({prior}/{max_allowed})",
            prior_count=prior,
            max_allowed=max_allowed,
        )

    return StoppingDecision(
        allow=True,
        reason="allowed",
        prior_count=prior,
        max_allowed=max_allowed,
    )
