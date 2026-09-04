"""Recovery budget allocator — spend at most ₹X on recovery actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.audit import AuditEvent
from app.services.score_cache import get_scored_audit


def allocate_recovery_budget(
    db: Session,
    *,
    budget_rupees: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    budget_paise = int((budget_rupees or settings.recovery_budget_rupees) * 100)

    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.status.in_(["intervention_sent", "detected", "delayed_for_downtime"]))
        .order_by(AuditEvent.created_at.desc())
        .limit(500)
        .all()
    )

    candidates: list[dict[str, Any]] = []
    for e in events:
        scored = get_scored_audit(db, e)
        if not scored["pursue"]:
            continue
        candidates.append(
            {
                "audit_id": e.id,
                "amount_rupees": (e.amount_paise or 0) / 100,
                "score": scored.get("score", 0),
                "expected_recovery_paise": scored.get("expected_recovery_paise", 0),
                "cost_paise": scored.get("recovery_cost_paise", 0),
                "roi": scored.get("expected_roi", 0),
                "channel": scored.get("channel", "email"),
                "action": scored.get("diagnosis_action") or scored.get("action"),
            }
        )

    candidates.sort(key=lambda x: (x["roi"], x["score"]), reverse=True)

    buckets = {
        "retries": 0,
        "messaging": 0,
        "incentives": 0,
        "voice_escalation": 0,
        "human_escalation": 0,
    }
    allocated: list[dict[str, Any]] = []
    spent = 0

    for c in candidates:
        cost = c["cost_paise"]
        if spent + cost > budget_paise:
            continue
        spent += cost
        action = c["action"] or ""
        ch = c["channel"] or "email"
        if "retry" in action:
            buckets["retries"] += cost
        elif ch == "voice":
            buckets["voice_escalation"] += cost
        elif "discount" in action or "incentive" in action:
            buckets["incentives"] += cost
        elif c["amount_rupees"] >= 25_000:
            buckets["human_escalation"] += cost
        else:
            buckets["messaging"] += cost
        allocated.append(c)

    return {
        "budget_rupees": budget_rupees or settings.recovery_budget_rupees,
        "budget_paise": budget_paise,
        "spent_paise": spent,
        "spent_rupees": round(spent / 100, 2),
        "remaining_rupees": round((budget_paise - spent) / 100, 2),
        "allocated_cases": len(allocated),
        "deferred_cases": max(0, len(candidates) - len(allocated)),
        "allocation": {k: round(v / 100, 2) for k, v in buckets.items()},
        "top_allocations": allocated[:10],
        "policy": {
            "max_discount_rupees": 500,
            "max_retries": 2,
            "max_messages": 3,
            "recovery_window_days": 14,
            "human_approval_above_rupees": 25_000,
        },
    }
