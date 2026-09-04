"""Seed synthetic revenue-loss events for batch demo + ML training pipeline."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.services.ml_recovery import REASON_RECOVERY_PRIORS

SEED_SCENARIOS = [
    ("incorrect_otp", "payment.failed", "payment_failure", "customer", "payment_authentication", 49900),
    ("otp_expired", "payment.failed", "payment_failure", "customer", "payment_authentication", 49900),
    ("insufficient_funds", "payment.failed", "payment_failure", "customer", "payment_authorization", 150000),
    ("payment_cancelled", "payment.failed", "payment_failure", "customer", "payment_authentication", 79900),
    ("bank_technical_error", "payment.failed", "payment_failure", "bank", "payment_authorization", 99900),
    ("gateway_technical_error", "payment.failed", "payment_failure", "gateway", "payment_authorization", 120000),
    ("payment_timed_out", "payment.failed", "payment_failure", "customer", "payment_authentication", 65000),
    ("checkout_abandoned", "payment.failed", "abandonment", "customer", "payment_authentication", 59900),
    ("debit_declined", "payment.failed", "subscription", "bank", "payment_authorization", 19900),
    ("otp_attempts_exceeded", "payment.failed", "payment_failure", "customer", "payment_authentication", 45000),
    ("subscription_halted", "subscription.halted", "subscription", None, None, 19900),
    ("mandate_debit", "payment.failed", "subscription", "bank", "payment_authorization", 19900),
    ("b2b_expired", "payment_link.expired", "b2b", None, None, 2500000),
    ("invalid_vpa", "payment.failed", "payment_failure", "customer", "payment_authorization", 35000),
]

PERSONA_EMAILS = [
    "ganeshsuraj29@gmail.com",
    "churned@demo.revrecover.test",
    "b2b@demo.revrecover.test",
    "loyal@demo.revrecover.test",
    "newuser@demo.revrecover.test",
]

PAYMENT_METHODS = ["upi", "card", "netbanking", "wallet", "emi"]

ACTION_BY_REASON: dict[str, str] = {
    "incorrect_otp": "retry_with_new_otp",
    "otp_expired": "retry_immediate",
    "insufficient_funds": "retry_delayed",
    "payment_cancelled": "soft_nudge_once",
    "bank_technical_error": "delay_retry",
    "gateway_technical_error": "delay_retry",
    "payment_timed_out": "retry_with_urgency",
    "checkout_abandoned": "soft_nudge_once",
    "debit_declined": "mandate_retry_sequence",
    "otp_attempts_exceeded": "suggest_alternate_method",
    "subscription_halted": "halted_revival_job",
    "mandate_debit": "mandate_retry_sequence",
    "b2b_expired": "regenerate_payment_link",
    "invalid_vpa": "suggest_alternate_method",
}

CHANNEL_BY_REASON: dict[str, str] = {
    "incorrect_otp": "sms",
    "otp_expired": "sms",
    "insufficient_funds": "sms",
    "payment_cancelled": "email",
    "bank_technical_error": "email",
    "gateway_technical_error": "email",
    "subscription_halted": "voice",
    "b2b_expired": "email",
    "debit_declined": "sms",
    "mandate_debit": "sms",
}


def _seed_timestamp(now: datetime, roll: float) -> datetime:
    """Bias UPI failures into 7–10 PM IST peak (+ morning window) for leakage demo."""
    ist = timezone(timedelta(hours=5, minutes=30))
    base = now.astimezone(ist)
    if roll < 0.35:
        hour = random.choice([19, 20, 21, 22])
    elif roll < 0.50:
        hour = random.choice([7, 8, 9, 10])
    else:
        hour = random.randint(0, 23)
    return base.replace(hour=hour, minute=random.randint(0, 59), second=0, microsecond=0).astimezone(timezone.utc)


def _seed_payment_method(roll: float) -> str:
    if roll < 0.41:
        return "upi"
    return random.choice(PAYMENT_METHODS)


def _recovery_probability(reason: str | None, *, training_mode: bool) -> float:
    """Reason-specific P(recovered) from Razorpay catalog priors."""
    if not reason:
        return 0.35
    base = REASON_RECOVERY_PRIORS.get(reason, 0.40)
    noise = random.uniform(-0.08, 0.08) if training_mode else random.uniform(-0.05, 0.05)
    return max(0.05, min(0.92, base + noise))


def seed_batch_events(
    db: Session,
    *,
    count: int = 60,
    simulate_some_recovered: bool = True,
    training_mode: bool = False,
) -> dict[str, Any]:
    """Insert synthetic audit (+ intervention) rows for ERR / funnel / ML training."""
    seed = 42 if not training_mode else 2026
    random.seed(seed)
    now = datetime.now(timezone.utc)
    created = 0
    recovered_n = 0
    interventions_n = 0

    for _ in range(count):
        reason, event_type, category, source, step, amount = random.choice(SEED_SCENARIOS)
        email = random.choice(PERSONA_EMAILS)
        order_id = f"order_seed_{uuid.uuid4().hex[:10]}"
        status_roll = random.random()

        if training_mode:
            # More intervention rows → richer ML training set
            if status_roll < 0.72:
                audit_status = "intervention_sent"
                recommended = ACTION_BY_REASON.get(reason, f"retry_{reason}")
            elif status_roll < 0.82:
                audit_status = "skipped_stopping_rule"
                recommended = "stopped:max_nudges_reached_2"
            elif status_roll < 0.91:
                audit_status = "delayed_for_downtime"
                recommended = "delay_retry:outage"
            else:
                audit_status = "watching"
                recommended = "wait_and_poll_late_auth"
        else:
            if status_roll < 0.15:
                audit_status = "skipped_stopping_rule"
                recommended = "stopped:max_nudges_reached_2"
            elif status_roll < 0.22:
                audit_status = "delayed_for_downtime"
                recommended = "delay_retry:outage"
            elif status_roll < 0.28:
                audit_status = "watching"
                recommended = "wait_and_poll_late_auth"
            else:
                audit_status = "intervention_sent"
                recommended = ACTION_BY_REASON.get(reason, f"retry_{reason}")

        time_roll = random.random()
        method_roll = random.random()
        audit = AuditEvent(
            id=str(uuid.uuid4()),
            event_type=event_type,
            category=category,
            order_id=order_id,
            error_reason=reason if source else reason,
            error_source=source,
            error_step=step,
            payment_method=_seed_payment_method(method_roll),
            amount_paise=amount,
            customer_email=email,
            customer_contact="+919876543210",
            diagnosis_path="seed_training_batch" if training_mode else "seed_batch",
            recommended_action=recommended,
            status=audit_status,
            created_at=_seed_timestamp(now, time_roll),
        )
        # Fast heuristic score so dashboards don't re-score thousands of rows
        if reason in {"incorrect_otp", "otp_expired"}:
            audit.recovery_score = 72
        elif reason in {"bank_technical_error", "gateway_technical_error"}:
            audit.recovery_score = 48
        elif reason in {"payment_cancelled", "checkout_abandoned"}:
            audit.recovery_score = 38
        elif reason == "subscription_halted":
            audit.recovery_score = 65
        elif category == "b2b":
            audit.recovery_score = 58
        else:
            audit.recovery_score = 50
        db.add(audit)
        created += 1

        if audit_status in {"intervention_sent", "skipped_stopping_rule", "delayed_for_downtime"}:
            iv_status = "delayed" if audit_status == "delayed_for_downtime" else "sent"
            channel = CHANNEL_BY_REASON.get(reason or "", random.choice(["email", "sms", "voice"]))

            if simulate_some_recovered and audit_status == "intervention_sent":
                p_recover = _recovery_probability(reason, training_mode=training_mode)
                if random.random() < p_recover:
                    iv_status = "recovered"
                    recovered_n += 1

            intervention = Intervention(
                id=str(uuid.uuid4()),
                audit_event_id=audit.id,
                action=recommended.split(":")[0] if ":" in recommended else recommended,
                channel=channel,
                message=f"[seed] Recovery for {reason}",
                status=iv_status,
                amount_at_risk_paise=amount,
                amount_recovered_paise=amount if iv_status == "recovered" else None,
                recovered_at=now if iv_status == "recovered" else None,
                created_at=audit.created_at,
            )
            db.add(intervention)
            interventions_n += 1
            if iv_status == "recovered":
                audit.status = "recovered"
                from app.models.escalation import resolve_escalations_for_audit

                resolve_escalations_for_audit(db, audit.id, note="Auto-resolved (simulated recovery)")

    db.commit()

    from app.services.learn_loop import refresh_learned_rates
    from app.services.ml_recovery import train_recovery_model

    learn = refresh_learned_rates(db)
    ml = train_recovery_model(db)

    result: dict[str, Any] = {
        "seeded_events": created,
        "interventions_created": interventions_n,
        "simulated_recoveries": recovered_n,
        "recovery_rate_percent": round((recovered_n / max(interventions_n, 1)) * 100, 1),
        "personas_used": PERSONA_EMAILS,
        "learn_loop": {"patterns_learned": learn.get("patterns_learned", 0)},
        "ml_model": ml,
        "training_mode": training_mode,
    }

    if training_mode:
        result["note"] = (
            f"ML training batch: {count} events with reason-weighted recoveries "
            f"(Razorpay catalog priors). Model trained on {ml.get('samples_real', 0)} real rows."
        )
    else:
        result["note"] = "Synthetic batch for ERR funnel + leakage (UPI evening peak) — reset demo to clear"

    return result


def seed_training_batch(db: Session, *, count: int = 2000) -> dict[str, Any]:
    """Primary ML training pipeline — 2000 events + simulated recoveries (judge-recommended)."""
    return seed_batch_events(
        db,
        count=count,
        simulate_some_recovered=True,
        training_mode=True,
    )
