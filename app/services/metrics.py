from __future__ import annotations

from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.services.downtime import get_outage_status


def get_metrics_summary(db: Session) -> dict[str, Any]:
    # Interventions that got a recovery action
    intervention_at_risk = (
        db.query(func.coalesce(func.sum(Intervention.amount_at_risk_paise), 0))
        .filter(Intervention.amount_at_risk_paise.isnot(None))
        .scalar()
        or 0
    )
    # All detected failures / at-risk events (including stopped-before-execute)
    detected_at_risk = (
        db.query(func.coalesce(func.sum(AuditEvent.amount_paise), 0))
        .filter(
            AuditEvent.event_type.in_(
                [
                    "payment.failed",
                    "payment.pending",
                    "subscription.pending",
                    "subscription.halted",
                    "payment_link.expired",
                ]
            ),
            AuditEvent.amount_paise.isnot(None),
        )
        .scalar()
        or 0
    )
    total_at_risk = max(int(intervention_at_risk), int(detected_at_risk))
    total_recovered = (
        db.query(func.coalesce(func.sum(Intervention.amount_recovered_paise), 0))
        .filter(Intervention.amount_recovered_paise.isnot(None))
        .scalar()
        or 0
    )
    intervention_count = db.query(func.count(Intervention.id)).scalar() or 0
    recovered_count = (
        db.query(func.count(Intervention.id)).filter(Intervention.status == "recovered").scalar() or 0
    )
    delayed_count = (
        db.query(func.count(Intervention.id)).filter(Intervention.status == "delayed").scalar() or 0
    )
    stopped_count = (
        db.query(func.count(AuditEvent.id))
        .filter(AuditEvent.status == "skipped_stopping_rule")
        .scalar()
        or 0
    )
    # Interventions with a real Razorpay short URL
    razorpay_link_count = (
        db.query(func.count(Intervention.id))
        .filter(Intervention.payment_link_url.isnot(None), Intervention.payment_link_url != "")
        .scalar()
        or 0
    )
    # Rate-limited but recoverable via /pay/{id}
    demo_pay_count = (
        db.query(func.count(Intervention.id)).filter(Intervention.status == "sent_no_link").scalar() or 0
    )
    # Truly no pay path (stopped before execute, or delayed with no link)
    no_pay_path_count = stopped_count + delayed_count

    detected_events = (
        db.query(func.count(AuditEvent.id))
        .filter(
            AuditEvent.event_type.in_(
                [
                    "payment.failed",
                    "payment.pending",
                    "subscription.pending",
                    "subscription.halted",
                    "payment_link.expired",
                ]
            )
        )
        .scalar()
        or 0
    )

    by_category_rows = (
        db.query(AuditEvent.category, func.count(AuditEvent.id))
        .group_by(AuditEvent.category)
        .all()
    )
    by_reason_rows = (
        db.query(AuditEvent.error_reason, func.count(AuditEvent.id))
        .filter(AuditEvent.error_reason.isnot(None))
        .group_by(AuditEvent.error_reason)
        .order_by(func.count(AuditEvent.id).desc())
        .limit(10)
        .all()
    )

    recovery_rate = round((total_recovered / total_at_risk) * 100, 2) if total_at_risk else 0.0

    return {
        "total_at_risk_paise": int(total_at_risk),
        "total_recovered_paise": int(total_recovered),
        "total_at_risk_rupees": round(total_at_risk / 100, 2),
        "total_recovered_rupees": round(total_recovered / 100, 2),
        "recovery_rate_percent": recovery_rate,
        "interventions_sent": intervention_count,
        "interventions_recovered": recovered_count,
        "delayed_for_downtime": delayed_count,
        "stopped_by_rules": stopped_count,
        "detected_events": int(detected_events),
        "with_razorpay_link": int(razorpay_link_count),
        "with_demo_pay": int(demo_pay_count),
        "with_pay_path": int(razorpay_link_count + demo_pay_count),
        "no_pay_path": int(no_pay_path_count),
        # legacy alias — was misleading (counted demo-pay as "missing")
        "missing_payment_links": int(demo_pay_count),
        "detected_at_risk_rupees": round(int(detected_at_risk) / 100, 2),
        "intervention_at_risk_rupees": round(int(intervention_at_risk) / 100, 2),
        "outages": get_outage_status(),
        "reconciliation": {
            "note": "Events = all detected failures. Pay path = Razorpay link OR Demo pay. "
            "Stopped/Delayed = no customer link by design.",
            "events_equals": "detected_events",
            "pay_path_equals": "with_razorpay_link + with_demo_pay",
            "no_link_expected": "stopped_by_rules + delayed_for_downtime (and late-auth watch)",
        },
        "events_by_category": {cat: count for cat, count in by_category_rows},
        "top_failure_reasons": {reason: count for reason, count in by_reason_rows},
    }


def get_batch_metrics(db: Session) -> dict[str, Any]:
    """Measured recovery across categories — Track 03 batch bar."""
    # At-risk from audit (detected) per category
    detected_rows = (
        db.query(
            AuditEvent.category,
            func.coalesce(func.sum(AuditEvent.amount_paise), 0),
            func.count(AuditEvent.id),
        )
        .filter(
            AuditEvent.event_type.in_(
                [
                    "payment.failed",
                    "payment.pending",
                    "subscription.pending",
                    "subscription.halted",
                    "payment_link.expired",
                ]
            )
        )
        .group_by(AuditEvent.category)
        .all()
    )
    detected_by_cat = {cat: (int(amt or 0), int(cnt or 0)) for cat, amt, cnt in detected_rows}

    status_rows = (
        db.query(AuditEvent.category, AuditEvent.status, func.count(AuditEvent.id))
        .filter(
            AuditEvent.event_type.in_(
                [
                    "payment.failed",
                    "payment.pending",
                    "subscription.pending",
                    "subscription.halted",
                    "payment_link.expired",
                ]
            )
        )
        .group_by(AuditEvent.category, AuditEvent.status)
        .all()
    )
    status_by_cat: dict[str, dict[str, int]] = {}
    for cat, status, cnt in status_rows:
        key = cat or "unknown"
        status_by_cat.setdefault(key, {})[status or "unknown"] = int(cnt)

    pay_path_rows = (
        db.query(
            AuditEvent.category,
            func.sum(case((Intervention.payment_link_url.isnot(None), 1), else_=0)),
            func.sum(case((Intervention.status == "sent_no_link", 1), else_=0)),
        )
        .join(Intervention, Intervention.audit_event_id == AuditEvent.id)
        .group_by(AuditEvent.category)
        .all()
    )
    pay_by_cat = {
        cat or "unknown": {"razorpay_links": int(rz or 0), "demo_pay": int(demo or 0)}
        for cat, rz, demo in pay_path_rows
    }

    rows = (
        db.query(
            AuditEvent.category,
            func.coalesce(func.sum(Intervention.amount_at_risk_paise), 0),
            func.coalesce(func.sum(Intervention.amount_recovered_paise), 0),
            func.count(func.distinct(AuditEvent.id)),
            func.sum(case((Intervention.status == "recovered", 1), else_=0)),
        )
        .outerjoin(Intervention, Intervention.audit_event_id == AuditEvent.id)
        .group_by(AuditEvent.category)
        .all()
    )

    by_category: dict[str, dict[str, Any]] = {}
    total_at_risk = 0
    total_recovered = 0
    total_events = 0
    total_recovered_count = 0

    for category, at_risk, recovered, events, recovered_n in rows:
        det_amt, det_events = detected_by_cat.get(category or "unknown", (0, 0))
        at_risk_i = max(int(at_risk or 0), det_amt)
        recovered_i = int(recovered or 0)
        events_i = max(int(events or 0), det_events)
        recovered_n_i = int(recovered_n or 0)
        rate = round((recovered_i / at_risk_i) * 100, 2) if at_risk_i else 0.0
        cat_key = category or "unknown"
        st = status_by_cat.get(cat_key, {})
        pay = pay_by_cat.get(cat_key, {"razorpay_links": 0, "demo_pay": 0})
        stopped_n = st.get("skipped_stopping_rule", 0)
        delayed_n = st.get("delayed_for_downtime", 0)
        by_category[cat_key] = {
            "events": events_i,
            "at_risk_paise": at_risk_i,
            "recovered_paise": recovered_i,
            "at_risk_rupees": round(at_risk_i / 100, 2),
            "recovered_rupees": round(recovered_i / 100, 2),
            "recovery_rate_percent": rate,
            "interventions_recovered": recovered_n_i,
            "with_razorpay_link": pay["razorpay_links"],
            "with_demo_pay": pay["demo_pay"],
            "with_pay_path": pay["razorpay_links"] + pay["demo_pay"],
            "stopped": stopped_n,
            "delayed": delayed_n,
            "no_pay_path": stopped_n + delayed_n,
            "status_breakdown": st,
        }
        total_at_risk += at_risk_i
        total_recovered += recovered_i
        total_events += events_i
        total_recovered_count += recovered_n_i

    # Categories detected but with no intervention row yet
    seen = set(by_category.keys())
    for cat, (det_amt, det_events) in detected_by_cat.items():
        key = cat or "unknown"
        if key in seen:
            continue
        rate = 0.0
        by_category[key] = {
            "events": det_events,
            "at_risk_paise": det_amt,
            "recovered_paise": 0,
            "at_risk_rupees": round(det_amt / 100, 2),
            "recovered_rupees": 0.0,
            "recovery_rate_percent": rate,
            "interventions_recovered": 0,
            "with_razorpay_link": 0,
            "with_demo_pay": 0,
            "with_pay_path": 0,
            "stopped": status_by_cat.get(key, {}).get("skipped_stopping_rule", 0),
            "delayed": status_by_cat.get(key, {}).get("delayed_for_downtime", 0),
            "no_pay_path": status_by_cat.get(key, {}).get("skipped_stopping_rule", 0)
            + status_by_cat.get(key, {}).get("delayed_for_downtime", 0),
            "status_breakdown": status_by_cat.get(key, {}),
        }
        total_at_risk += det_amt
        total_events += det_events

    by_action_rows = (
        db.query(
            Intervention.action,
            func.count(Intervention.id),
            func.coalesce(func.sum(Intervention.amount_recovered_paise), 0),
        )
        .group_by(Intervention.action)
        .order_by(func.count(Intervention.id).desc())
        .limit(12)
        .all()
    )

    total_stopped = sum(v.get("stopped", 0) for v in by_category.values())
    total_delayed = sum(v.get("delayed", 0) for v in by_category.values())
    total_pay_path = sum(v.get("with_pay_path", 0) for v in by_category.values())

    return {
        "total_events": total_events,
        "total_at_risk_paise": total_at_risk,
        "total_recovered_paise": total_recovered,
        "total_at_risk_rupees": round(total_at_risk / 100, 2),
        "total_recovered_rupees": round(total_recovered / 100, 2),
        "recovery_rate_percent": round((total_recovered / total_at_risk) * 100, 2) if total_at_risk else 0.0,
        "interventions_recovered": total_recovered_count,
        "with_pay_path": total_pay_path,
        "stopped": total_stopped,
        "delayed": total_delayed,
        "no_pay_path": total_stopped + total_delayed,
        "outages": get_outage_status(),
        "by_category": by_category,
        "by_action": {
            action: {"count": int(count), "recovered_paise": int(recovered or 0)}
            for action, count, recovered in by_action_rows
            if action
        },
    }


def reset_demo_data(db: Session) -> dict[str, int]:
    """Clear interventions + audit events + promises for a clean judge demo."""
    from app.models.escalation import EscalationCase
    from app.models.promise import PromiseToPay
    from app.models.scheduled_action import ScheduledAction

    esc_count = db.query(EscalationCase).delete()
    iv_count = db.query(Intervention).delete()
    ev_count = db.query(AuditEvent).delete()
    pr_count = db.query(PromiseToPay).delete()
    sch_count = db.query(ScheduledAction).delete()
    db.commit()
    return {
        "escalations_deleted": esc_count,
        "interventions_deleted": iv_count,
        "events_deleted": ev_count,
        "promises_deleted": pr_count,
        "scheduled_deleted": sch_count,
    }
