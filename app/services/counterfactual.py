"""Counterfactual recovery simulator — naive remind-all vs smart rules (whole ₹, no ML score)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.services.dashboard_display import AUTO_RETRY_ACTIONS, rule_recoverable_paise
from app.services.recovery_economics import get_intelligence_metrics
from app.services.score_cache import get_scored_audit, RISK_EVENT_TYPES

SMS_COST_PAISE = 60  # ₹0.60 per naive nudge


def simulate_strategies(db: Session) -> dict[str, Any]:
    """Compare naive 'remind everyone' vs RevRecover smart pursuit."""
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type.in_(list(RISK_EVENT_TYPES)))
        .all()
    )

    total_at_risk = sum(e.amount_paise or 0 for e in events)
    baseline_recovery = 0
    smart_recovery = 0
    smart_cost = 0
    baseline_cost = 0
    naive_nudged = 0
    smart_nudged = 0
    smart_stopped = 0
    smart_delayed = 0

    for e in events:
        amt = e.amount_paise or 0
        baseline_recovery += int(round((amt / 100) * 0.35) * 100)
        baseline_cost += SMS_COST_PAISE
        naive_nudged += 1

        scored = get_scored_audit(db, e)
        if scored.get("stopped"):
            smart_stopped += 1
            continue
        if e.status == "delayed_for_downtime":
            smart_delayed += 1
            continue
        if e.status in {"watching", "watching_late_auth"}:
            continue
        if not scored.get("pursue"):
            smart_stopped += 1
            continue

        smart_nudged += 1
        smart_recovery += rule_recoverable_paise(amt, e.error_reason)
        action = scored.get("diagnosis_action") or e.recommended_action or ""
        if action in AUTO_RETRY_ACTIONS or scored.get("channel") == "sms":
            smart_cost += 50
        elif scored.get("channel") == "voice":
            smart_cost += 500
        else:
            smart_cost += 10

    incremental = smart_recovery - baseline_recovery
    smart_roi = round(smart_recovery / max(smart_cost, 1), 1)
    baseline_roi = round(baseline_recovery / max(baseline_cost, 1), 1)

    intel = get_intelligence_metrics(db)

    return {
        "events_analyzed": len(events),
        "total_at_risk_rupees": total_at_risk // 100,
        "baseline_strategy": {
            "name": "Remind everyone (naive)",
            "description": "Send 1 SMS to every failed case — assume 35% recover (industry rough average).",
            "cases_nudged": naive_nudged,
            "cases_stopped": 0,
            "expected_recovery_rupees": baseline_recovery // 100,
            "estimated_cost_rupees": round(baseline_cost / 100, 1),
            "roi": baseline_roi,
        },
        "smart_strategy": {
            "name": "RevRecover (smart rules)",
            "description": "Nudge only pursue cases; STOP spam, DELAY on outage, WATCH late auth.",
            "cases_nudged": smart_nudged,
            "cases_stopped": smart_stopped,
            "cases_delayed": smart_delayed,
            "expected_recovery_rupees": smart_recovery // 100,
            "realistically_recoverable_rupees": intel["realistically_recoverable_rupees"],
            "estimated_cost_rupees": round(smart_cost / 100, 1),
            "roi": smart_roi,
        },
        "incremental_recovery_rupees": incremental // 100,
        "incremental_roi": round(smart_roi - baseline_roi, 1),
        "headline": (
            f"Smart: nudge {smart_nudged} cases (stop {smart_stopped}, delay {smart_delayed}) "
            f"vs naive: blast {naive_nudged} cases"
        ),
        "display_method": "rule_priors_whole_rupees",
    }
