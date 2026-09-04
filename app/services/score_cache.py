"""Fast recovery score lookup for dashboards — avoids re-scoring thousands of rows."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent

RISK_EVENT_TYPES = frozenset(
    {
        "payment.failed",
        "payment.pending",
        "subscription.pending",
        "subscription.halted",
        "payment_link.expired",
    }
)


def _heuristic_from_audit(audit: AuditEvent) -> dict[str, Any]:
    """Lightweight score when no persisted JSON exists (seed batch rows)."""
    score = audit.recovery_score
    if score is None:
        reason = (audit.error_reason or "").lower()
        if reason in {"incorrect_otp", "otp_expired"}:
            score = 72
        elif reason in {"bank_technical_error", "gateway_technical_error"}:
            score = 48
        elif reason in {"payment_cancelled", "checkout_abandoned"}:
            score = 38
        elif reason == "subscription_halted":
            score = 65
        elif "b2b" in (audit.category or ""):
            score = 58
        else:
            score = 50

    stopped = audit.status in {"skipped_stopping_rule", "skipped"} or (
        audit.recommended_action or ""
    ).startswith("stopped:")
    watching = audit.status in {"watching", "watching_late_auth"}
    delayed = audit.status == "delayed_for_downtime"
    amount = audit.amount_paise or 0
    pursue = (
        not stopped
        and not watching
        and not delayed
        and score >= 40
    )
    expected = int(amount * (score / 100.0) * (0.55 if pursue else 0.1))
    cost = 60 if pursue else 0
    action = (audit.recommended_action or "").split(":")[0]

    return {
        "score": score,
        "pursue": pursue,
        "stopped": stopped,
        "stop_reason": audit.recommended_action if stopped else None,
        "diagnosis_action": action,
        "channel": "voice" if action == "halted_revival_job" else "email",
        "expected_recovery_paise": expected,
        "recovery_cost_paise": cost,
        "expected_roi": round(expected / max(cost, 1), 2),
    }


def get_scored_audit(db: Session, audit: AuditEvent, *, allow_full_score: bool = False) -> dict[str, Any]:
    """Return score payload from cache, heuristic, or (optionally) full scoring."""
    if audit.recovery_score_json:
        try:
            data = json.loads(audit.recovery_score_json)
            if isinstance(data, dict) and "score" in data:
                base = _heuristic_from_audit(audit)
                base.update(data)
                if "diagnosis_action" not in base:
                    base["diagnosis_action"] = (
                        data.get("action")
                        or (audit.recommended_action or "").split(":")[0]
                    )
                if "recovery_cost_paise" not in base:
                    base["recovery_cost_paise"] = data.get("cost_paise", base["recovery_cost_paise"])
                if "expected_roi" not in base:
                    exp = base.get("expected_recovery_paise", 0)
                    cost = base.get("recovery_cost_paise", 1)
                    base["expected_roi"] = round(exp / max(cost, 1), 2)
                return base
        except json.JSONDecodeError:
            pass

    if audit.recovery_score is not None or audit.diagnosis_path in {"seed_batch", "seed_training_batch"}:
        return _heuristic_from_audit(audit)

    if allow_full_score:
        from app.services.recovery_economics import score_audit_event

        return score_audit_event(db, audit)

    return _heuristic_from_audit(audit)
