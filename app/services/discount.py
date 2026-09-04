"""Selective discount / incentive tier — only when ROI positive."""

from __future__ import annotations

from typing import Any

MAX_DISCOUNT_PAISE = 50_000  # ₹500 policy cap


def evaluate_discount(
    *,
    amount_paise: int,
    recovery_score: int,
    error_reason: str | None,
    expected_recovery_paise: int,
) -> dict[str, Any]:
    """Return discount recommendation or none."""
    reason = (error_reason or "").lower()
    eligible_reason = any(
        k in reason for k in ("cancel", "abandon", "timeout", "timed_out")
    ) or recovery_score in range(45, 72)

    if recovery_score < 45 or amount_paise < 50_000:
        return {"apply": False, "discount_paise": 0, "note": "Score or amount too low for incentive"}

    discount_paise = min(MAX_DISCOUNT_PAISE, int(amount_paise * 0.02))
    if not eligible_reason and amount_paise < 200_000:
        return {"apply": False, "discount_paise": 0, "note": "No hesitation signal — skip discount"}

    net_recovery = expected_recovery_paise - discount_paise
    if net_recovery <= 0:
        return {"apply": False, "discount_paise": 0, "note": "Discount exceeds expected recovery"}

    return {
        "apply": True,
        "discount_paise": discount_paise,
        "discount_rupees": round(discount_paise / 100, 2),
        "net_expected_recovery_rupees": round(net_recovery / 100, 2),
        "note": f"Offer ₹{discount_paise/100:.0f} off — expected net recovery positive",
        "action": "incentive_nudge",
    }
