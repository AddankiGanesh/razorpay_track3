"""ERR, leak funnel, and batch recovery plan aggregates."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.diagnosis.engine import diagnosis_engine
from app.execution.stopping import evaluate_stopping_rules
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.config import get_settings
from app.services.customer_context import build_customer_context
from app.services.dashboard_display import AUTO_RETRY_ACTIONS, rule_recoverable_paise
from app.services.ml_recovery import predict_recovery_probability
from app.services.recovery_score import compute_recovery_score
from app.services.score_cache import get_scored_audit, RISK_EVENT_TYPES

_intelligence_cache: tuple[float, dict[str, Any]] | None = None
_INTELLIGENCE_CACHE_TTL_SEC = 30.0


def _primary_channel(diagnosis) -> str:
    if diagnosis.channels:
        return diagnosis.channels[0]
    return "email"


def score_audit_event(db: Session, audit: AuditEvent) -> dict[str, Any]:
    diagnosis = diagnosis_engine.diagnose(audit.error_reason, audit.error_source, audit.error_step)
    customer = build_customer_context(
        db, email=audit.customer_email, contact=audit.customer_contact, exclude_audit_id=audit.id
    )
    stop = evaluate_stopping_rules(db, audit=audit, action=diagnosis.action)
    channel = _primary_channel(diagnosis)
    if diagnosis.action == "halted_revival_job":
        channel = "voice"
    hour = audit.created_at.hour if audit.created_at else None
    ml_prob = None
    if get_settings().ml_scoring_enabled:
        ml_prob = predict_recovery_probability(
            amount_paise=audit.amount_paise or 0,
            error_reason=audit.error_reason,
            diagnosis=diagnosis,
            customer=customer,
            channel=channel,
            payment_method=audit.payment_method,
            event_hour=hour,
        )
    result = compute_recovery_score(
        amount_paise=audit.amount_paise or 0,
        error_reason=audit.error_reason,
        diagnosis=diagnosis,
        customer=customer,
        channel=channel,
        will_stop=not stop.allow,
        ml_probability=ml_prob,
    )
    return {
        "audit_id": audit.id,
        "customer": customer.to_dict(),
        "diagnosis_action": diagnosis.action,
        "channel": channel,
        "stopped": not stop.allow,
        "stop_reason": stop.reason if not stop.allow else None,
        **result.to_dict(),
    }


def get_intelligence_metrics(db: Session, *, use_cache: bool = True) -> dict[str, Any]:
    """ERR dashboard: at risk, recoverable, recovered, expected from active cases."""
    import time

    global _intelligence_cache
    if use_cache and _intelligence_cache is not None:
        cached_at, payload = _intelligence_cache
        if time.time() - cached_at < _INTELLIGENCE_CACHE_TTL_SEC:
            return payload

    risk_events = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type.in_(list(RISK_EVENT_TYPES)))
        .all()
    )

    recovered_ivs = (
        db.query(Intervention)
        .filter(Intervention.status == "recovered")
        .all()
    )
    recovered_audit_ids = {i.audit_event_id for i in recovered_ivs}
    total_recovered = sum(int(i.amount_recovered_paise or 0) for i in recovered_ivs)

    total_at_risk = 0
    rule_recoverable_total = 0
    pursuing_at_risk_paise = 0
    stopped_count = 0
    pursue_count = 0
    stop_low_score = 0

    plan_buckets: dict[str, int] = {
        "pursue_retry": 0,
        "pursue_message": 0,
        "escalate_voice": 0,
        "delay": 0,
        "stop_compliance": 0,
        "stop_low_score": 0,
        "watch": 0,
        "recovered": 0,
    }

    for audit in risk_events:
        amount = audit.amount_paise or 0
        total_at_risk += amount

        if audit.id in recovered_audit_ids:
            plan_buckets["recovered"] += 1
            continue

        scored = get_scored_audit(db, audit)
        rule_recoverable_total += rule_recoverable_paise(amount, audit.error_reason)

        if scored.get("stopped"):
            stopped_count += 1
            plan_buckets["stop_compliance"] += 1
            continue

        if audit.status == "delayed_for_downtime":
            plan_buckets["delay"] += 1
            continue

        if audit.status in {"watching", "watching_late_auth"}:
            plan_buckets["watch"] += 1
            continue

        if scored.get("pursue"):
            pursue_count += 1
            pursuing_at_risk_paise += amount
            action = scored.get("diagnosis_action") or audit.recommended_action or ""
            if action in {"delay_retry"}:
                plan_buckets["delay"] += 1
            elif scored.get("channel") == "voice" or action == "halted_revival_job":
                plan_buckets["escalate_voice"] += 1
            elif action in AUTO_RETRY_ACTIONS:
                plan_buckets["pursue_retry"] += 1
            else:
                plan_buckets["pursue_message"] += 1
        else:
            stop_low_score += 1
            plan_buckets["stop_low_score"] += 1

    opportunity_gap_paise = max(0, rule_recoverable_total - total_recovered)

    payload = {
        "total_at_risk_paise": total_at_risk,
        "total_at_risk_rupees": total_at_risk // 100,
        "realistically_recoverable_paise": rule_recoverable_total,
        "realistically_recoverable_rupees": rule_recoverable_total // 100,
        "total_recovered_paise": total_recovered,
        "total_recovered_rupees": total_recovered // 100,
        "recovery_opportunity_paise": opportunity_gap_paise,
        "recovery_opportunity_rupees": opportunity_gap_paise // 100,
        "pursuing_at_risk_paise": pursuing_at_risk_paise,
        "pursuing_at_risk_rupees": pursuing_at_risk_paise // 100,
        "expected_from_active_paise": pursuing_at_risk_paise,
        "expected_from_active_rupees": pursuing_at_risk_paise // 100,
        "events_analyzed": len(risk_events),
        "pursue_count": pursue_count,
        "stopped_count": stopped_count,
        "stop_low_score_count": stop_low_score,
        "recovery_plan": plan_buckets,
        "display_method": "rule_priors_whole_rupees",
        "err_formula": "rule_recoverable = sum(round(amount × reason_prior)) per open case",
    }
    _intelligence_cache = (time.time(), payload)
    return payload


def clear_intelligence_cache() -> None:
    global _intelligence_cache
    _intelligence_cache = None


def get_leak_funnel(db: Session) -> dict[str, Any]:
    """Revenue leak graph data for UI."""
    risk_events = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type.in_(list(RISK_EVENT_TYPES)))
        .all()
    )

    by_category: dict[str, int] = {}
    for e in risk_events:
        cat = e.category or "unknown"
        by_category[cat] = by_category.get(cat, 0) + (e.amount_paise or 0)

    recovered_ivs = (
        db.query(Intervention)
        .filter(Intervention.status == "recovered")
        .with_entities(Intervention.amount_recovered_paise, Intervention.audit_event_id)
        .all()
    )
    total_recovered = sum(int(r[0] or 0) for r in recovered_ivs)
    recovered_audit_ids = {r[1] for r in recovered_ivs}

    stopped_amt = 0
    delayed_amt = 0
    active_amt = 0
    for e in risk_events:
        amt = e.amount_paise or 0
        if e.id in recovered_audit_ids:
            continue
        if e.status == "skipped_stopping_rule":
            stopped_amt += amt
        elif e.status == "delayed_for_downtime":
            delayed_amt += amt
        else:
            scored = get_scored_audit(db, e)
            if scored.get("pursue"):
                active_amt += amt
            else:
                stopped_amt += amt

    total_at_risk = sum(by_category.values())

    return {
        "total_at_risk_paise": total_at_risk,
        "total_at_risk_rupees": round(total_at_risk / 100, 2),
        "total_recovered_paise": total_recovered,
        "total_recovered_rupees": round(total_recovered / 100, 2),
        "by_category_rupees": {k: round(v / 100, 2) for k, v in by_category.items()},
        "flows": {
            "at_risk": round(total_at_risk / 100, 2),
            "pursuing": round(active_amt / 100, 2),
            "stopped_or_low_score": round(stopped_amt / 100, 2),
            "delayed": round(delayed_amt / 100, 2),
            "recovered": round(total_recovered / 100, 2),
        },
        "nodes": [
            {"id": "at_risk", "label": "At risk", "value_rupees": round(total_at_risk / 100, 2)},
            {"id": "failed", "label": "Payment failed", "value_rupees": round(by_category.get("payment_failure", 0) / 100, 2)},
            {"id": "abandoned", "label": "Abandoned", "value_rupees": round(by_category.get("abandonment", 0) / 100, 2)},
            {"id": "subscription", "label": "Subscription", "value_rupees": round(by_category.get("subscription", 0) / 100, 2)},
            {"id": "b2b", "label": "B2B / invoice", "value_rupees": round(by_category.get("b2b", 0) / 100, 2)},
            {"id": "pursuing", "label": "Pursuing", "value_rupees": round(active_amt / 100, 2)},
            {"id": "stopped", "label": "Stopped", "value_rupees": round(stopped_amt / 100, 2)},
            {"id": "recovered", "label": "Recovered", "value_rupees": round(total_recovered / 100, 2)},
        ],
    }
