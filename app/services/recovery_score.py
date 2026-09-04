"""Recovery Score (0–100) + expected recovery economics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.diagnosis.engine import DiagnosisResult
from app.services.customer_context import CustomerContext
from app.services.learn_loop import learned_score_boost
from app.config import get_settings

# Paise — estimated recovery channel cost for ROI demo
CHANNEL_COST_PAISE: dict[str, int] = {
    "email": 10,
    "sms": 50,
    "voice": 500,
    "system": 0,
    "whatsapp": 80,
}

HIGH_RECOVERY_REASONS = frozenset(
    {
        "incorrect_otp",
        "otp_expired",
        "insufficient_funds",
        "bank_technical_error",
        "gateway_technical_error",
        "payment_timed_out",
        "debit_declined",
    }
)
LOW_RECOVERY_REASONS = frozenset(
    {
        "payment_cancelled",
        "otp_attempts_exceeded",
        "payment_risk_check_failed",
        "invalid_vpa",
    }
)

PRIORITY_BOOST = {"critical": 15, "high": 10, "medium": 0, "low": -10}


@dataclass
class RecoveryScoreResult:
    score: int
    probability_percent: float
    recommended_strategy: str
    pursue: bool
    positive_factors: list[str]
    negative_factors: list[str]
    recovery_cost_paise: int
    expected_recovery_paise: int
    expected_roi: float
    explanation: str
    heuristic_score: int = 0
    ml_probability_percent: float | None = None
    scoring_method: str = "heuristic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "probability_percent": self.probability_percent,
            "recommended_strategy": self.recommended_strategy,
            "pursue": self.pursue,
            "positive_factors": self.positive_factors,
            "negative_factors": self.negative_factors,
            "recovery_cost_paise": self.recovery_cost_paise,
            "recovery_cost_rupees": round(self.recovery_cost_paise / 100, 2),
            "expected_recovery_paise": self.expected_recovery_paise,
            "expected_recovery_rupees": round(self.expected_recovery_paise / 100, 2),
            "expected_roi": self.expected_roi,
            "explanation": self.explanation,
            "heuristic_score": self.heuristic_score,
            "ml_probability_percent": self.ml_probability_percent,
            "scoring_method": self.scoring_method,
        }


def compute_recovery_score(
    *,
    amount_paise: int,
    error_reason: str | None,
    diagnosis: DiagnosisResult,
    customer: CustomerContext,
    channel: str,
    will_stop: bool = False,
    ml_probability: float | None = None,
) -> RecoveryScoreResult:
    score = 50.0
    positive: list[str] = list(customer.positive_notes)
    negative: list[str] = list(customer.negative_notes)

    reason = (error_reason or diagnosis.reason or "").strip()

    if reason in HIGH_RECOVERY_REASONS:
        score += 18
        positive.append(f"Recoverable failure reason: {reason}")
    elif reason in LOW_RECOVERY_REASONS:
        score -= 12
        negative.append(f"Low-intent failure: {reason}")

    score += PRIORITY_BOOST.get(diagnosis.priority, 0)

    if customer.successful_payments >= 10:
        score += 15
    elif customer.successful_payments >= 5:
        score += 8
    elif customer.successful_payments <= 1:
        score -= 8

    if customer.prior_failures_30d >= 4:
        score -= 20
    elif customer.prior_failures_30d >= 2:
        score -= 8
    elif customer.prior_failures_30d == 0:
        score += 5

    if customer.reminders_ignored >= 3:
        score -= 25
    elif customer.reminders_ignored >= 1:
        score -= 8

    if customer.nudges_sent_72h >= 3:
        score -= 15
    elif customer.nudges_sent_72h >= 1:
        score -= 5

    if amount_paise >= 500_000:  # ₹5000+
        score += 12
        positive.append("High transaction value")
    elif amount_paise >= 100_000:
        score += 6

    if diagnosis.check_downtime:
        score -= 5
        negative.append("Bank/gateway downtime — defer nudge")

    if will_stop:
        score = min(score, 20)
        negative.append("Stopping rules would block pursuit")

    score += learned_score_boost(reason, diagnosis.action)
    heuristic_score = max(0, min(100, int(round(score))))

    settings = get_settings()
    ml_prob = ml_probability
    scoring_method = "heuristic"
    if ml_prob is not None and settings.ml_scoring_enabled:
        ml_score = max(0, min(100, int(round(ml_prob))))
        blend = settings.ml_blend_weight
        score = int(round((1 - blend) * heuristic_score + blend * ml_score))
        scoring_method = "ml_blend"
        positive.append(f"ML recovery probability {ml_prob:.0f}%")
    else:
        score = heuristic_score

    score = max(0, min(100, score))
    probability = float(score)

    cost = CHANNEL_COST_PAISE.get(channel, 30)
    expected_recovery = int(amount_paise * (probability / 100.0))
    roi = round(expected_recovery / max(cost, 1), 2)

    pursue = score >= 40 and not will_stop and expected_recovery > cost

    if score >= 75:
        strategy = f"Pursue — {diagnosis.action} via {channel}"
    elif score >= 40:
        strategy = f"Selective pursue — {diagnosis.action}"
    else:
        strategy = "STOP — recovery ROI too low"

    if not pursue and score < 40:
        strategy = "STOP — do not pursue"

    explanation = (
        f"Recovery score {score}/100 ({scoring_method}) · expected ₹{expected_recovery/100:.0f} "
        f"vs cost ₹{cost/100:.2f} · ROI {roi}×"
    )
    if ml_prob is not None:
        explanation += f" · ML {ml_prob:.0f}% · heuristic {heuristic_score}"

    return RecoveryScoreResult(
        score=score,
        probability_percent=probability,
        recommended_strategy=strategy,
        pursue=pursue,
        positive_factors=positive[:6],
        negative_factors=negative[:6],
        recovery_cost_paise=cost,
        expected_recovery_paise=expected_recovery,
        expected_roi=roi,
        explanation=explanation,
        heuristic_score=heuristic_score,
        ml_probability_percent=ml_prob,
        scoring_method=scoring_method,
    )
