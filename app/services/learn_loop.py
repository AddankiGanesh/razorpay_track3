"""Learn from historical recovery outcomes — heuristic learning loop (no ML training required)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.intervention import Intervention

# Learned multipliers applied to base recovery score (demo-safe heuristics)
_LEARNED_CACHE: dict[str, float] = {}


def refresh_learned_rates(db: Session) -> dict[str, Any]:
    """Aggregate recovery rate by failure reason + action from stored outcomes."""
    global _LEARNED_CACHE
    rows = (
        db.query(
            AuditEvent.error_reason,
            Intervention.action,
            func.count(Intervention.id),
            func.sum(case((Intervention.status == "recovered", 1), else_=0)),
        )
        .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
        .filter(AuditEvent.error_reason.isnot(None))
        .group_by(AuditEvent.error_reason, Intervention.action)
        .all()
    )

    insights: list[dict[str, Any]] = []
    _LEARNED_CACHE.clear()

    for reason, action, total, recovered in rows:
        total_i = int(total or 0)
        rec_i = int(recovered or 0)
        if total_i < 1:
            continue
        rate = round((rec_i / total_i) * 100, 1)
        key = f"{reason}:{action}"
        # Map rate to score boost -50..+15
        boost = int((rate - 50) * 0.3)
        boost = max(-15, min(15, boost))
        _LEARNED_CACHE[key] = boost
        insights.append(
            {
                "reason": reason,
                "action": action,
                "attempts": total_i,
                "recovered": rec_i,
                "recovery_rate_percent": rate,
                "score_adjustment": boost,
                "insight": _insight_text(reason, action, rate),
            }
        )

    insights.sort(key=lambda x: x["recovery_rate_percent"], reverse=True)

    from app.services.ml_recovery import train_recovery_model

    ml_train = train_recovery_model(db)

    return {
        "patterns_learned": len(insights),
        "insights": insights[:20],
        "top_winning_playbook": insights[0] if insights else None,
        "ml_model": ml_train,
        "note": "SQL aggregates + sklearn model retrain on each refresh.",
    }


def _insight_text(reason: str, action: str, rate: float) -> str:
    if rate >= 65:
        return f"When `{reason}` → prefer `{action}` ({rate}% recovered in our data)"
    if rate <= 25:
        return f"Low win rate for `{reason}` + `{action}` ({rate}%) — consider STOP earlier"
    return f"Moderate recovery for `{reason}` via `{action}` ({rate}%)"


def learned_score_boost(error_reason: str | None, action: str) -> int:
    if not error_reason:
        return 0
    return int(_LEARNED_CACHE.get(f"{error_reason}:{action}", 0))
