"""Judge-friendly dashboard numbers — whole ₹, rule-based priors (no ML score math)."""

from __future__ import annotations

from app.services.ml_recovery import REASON_RECOVERY_PRIORS

# Playbook actions treated as urgent retry (OTP, funds, mandate, alternate method)
AUTO_RETRY_ACTIONS = frozenset(
    {
        "retry_with_new_otp",
        "retry_immediate",
        "retry_delayed",
        "mandate_retry_sequence",
        "suggest_alternate_method",
        "retry_with_guidance",
        "retry_with_urgency",
    }
)

DEFAULT_RECOVERABLE_PRIOR = 0.35


def rule_recoverable_paise(amount_paise: int, error_reason: str | None) -> int:
    """Whole-rupee recoverable estimate from Razorpay reason priors (not ML score)."""
    prior = REASON_RECOVERY_PRIORS.get((error_reason or "").strip(), DEFAULT_RECOVERABLE_PRIOR)
    rupees = round((amount_paise / 100) * prior)
    return int(rupees * 100)


def rule_recoverable_rupees(amount_paise: int, error_reason: str | None) -> int:
    return rule_recoverable_paise(amount_paise, error_reason) // 100
