"""Reuse unpaid payment links when Razorpay blocks new link creation."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.intervention import Intervention

logger = logging.getLogger(__name__)

_last_link_created_at: float = 0.0


def throttle_before_create() -> None:
    settings = get_settings()
    global _last_link_created_at
    elapsed = time.monotonic() - _last_link_created_at
    wait = settings.payment_link_min_interval_sec - elapsed
    if wait > 0:
        logger.info("Throttling payment link API call for %.1fs", wait)
        time.sleep(wait)


def mark_link_created() -> None:
    global _last_link_created_at
    _last_link_created_at = time.monotonic()


def classify_link_error(exc: Exception | str | None) -> str:
    msg = str(exc or "").lower()
    if "limit of 30" in msg or "test mode limit" in msg:
        return "test_mode_cap_30"
    if "too many requests" in msg or "rate" in msg or "429" in msg:
        return "rate_limited"
    return "api_error"


def link_error_label(code: str | None, *, reused: bool = False) -> str:
    labels = {
        "test_mode_cap_30": "Razorpay test-mode cap (30 links reached)",
        "rate_limited": "Razorpay API rate limit",
        "api_error": "Razorpay payment-link API unavailable",
    }
    base = labels.get(code or "", labels["api_error"])
    if reused and code in {"test_mode_cap_30", "rate_limited"}:
        return f"{base} — reusing an existing unpaid link"
    return base


def demo_fallback_label(code: str | None, amount_rupees: float | None = None) -> str:
    """User-facing text when Execute finished but no Razorpay URL is available."""
    amt = f" for Rs {amount_rupees:.0f}" if amount_rupees else ""
    if code == "test_mode_cap_30":
        return f"30-link test cap — no unpaid Razorpay link{amt} to reuse · Demo pay ready"
    base = link_error_label(code, reused=False)
    return f"{base} · Demo pay ready"


def pay_path_explanation(
    *,
    amount_paise: int,
    status: str | None,
    has_razorpay_url: bool,
    link_error: str | None,
) -> str:
    """Explain why this scenario got Pay link vs Demo pay (amount-specific reuse)."""
    amount = amount_paise / 100
    if has_razorpay_url and status == "reused_link":
        return (
            f"Reused an unpaid Razorpay link for Rs {amount:.0f}. "
            "Test-mode 30-link cap blocks new links, but this amount already has unpaid links in Razorpay."
        )
    if has_razorpay_url:
        return f"New Razorpay payment link created for Rs {amount:.0f}."
    if status == "sent_no_link" and link_error == "test_mode_cap_30":
        return (
            f"No unpaid Razorpay link for Rs {amount:.0f} in your test account "
            "(30-link cap reached). Wrong OTP / Low balance amounts usually still work — "
            "B2B Rs 25000 often needs Demo pay."
        )
    if status == "sent_no_link":
        return f"No Razorpay pay link available for Rs {amount:.0f} — use Demo pay."
    return ""


def find_razorpay_unpaid_link(amount_paise: int) -> tuple[str | None, str | None]:
    """Find an unpaid payment link already created in Razorpay (survives DB resets)."""
    from app.services.razorpay_client import get_razorpay_client

    client = get_razorpay_client()
    try:
        data = client.payment_link.all({"count": 100})
        links = data.get("payment_links") or data.get("items") or []
        for pl in links:
            if (
                pl.get("amount") == amount_paise
                and pl.get("status") == "created"
                and not pl.get("amount_paid")
            ):
                logger.info(
                    "Reusing Razorpay link %s for Rs %.0f",
                    pl.get("id"),
                    amount_paise / 100,
                )
                return pl.get("id"), pl.get("short_url")
    except Exception:
        logger.exception("Failed to list Razorpay payment links for reuse")
    return None, None


def find_reusable_link(db: Session, amount_paise: int) -> tuple[str | None, str | None]:
    """Return an existing unpaid link from DB, then from Razorpay API."""
    from app.models.intervention import Intervention

    row = (
        db.query(Intervention)
        .filter(
            Intervention.amount_at_risk_paise == amount_paise,
            Intervention.payment_link_url.isnot(None),
            Intervention.amount_recovered_paise.is_(None),
        )
        .order_by(Intervention.created_at.desc())
        .first()
    )
    if row:
        logger.info(
            "Reusing DB payment link %s for amount Rs %.0f",
            row.payment_link_id,
            amount_paise / 100,
        )
        return row.payment_link_id, row.payment_link_url
    return find_razorpay_unpaid_link(amount_paise)
