"""Downtime-aware retry — pause customer nudges during bank/gateway outages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# In-memory downtime flags for demo (replace with Razorpay Downtime API later)
_ACTIVE_OUTAGES: dict[str, datetime] = {}


@dataclass
class DowntimeDecision:
    delay: bool
    reason: str
    retry_after: datetime | None = None


def mark_outage(source: str, hours: float = 4.0) -> None:
    """Mark a payment source as down (demo / webhook hook)."""
    _ACTIVE_OUTAGES[source.lower()] = datetime.now(timezone.utc) + timedelta(hours=hours)
    logger.info("Marked outage for %s until %s", source, _ACTIVE_OUTAGES[source.lower()])


def clear_outage(source: str) -> None:
    _ACTIVE_OUTAGES.pop(source.lower(), None)


def get_active_outages() -> dict[str, str]:
    """Return active outage sources and ISO retry-after times (for UI)."""
    now = datetime.now(timezone.utc)
    return {
        source: until.isoformat()
        for source, until in _ACTIVE_OUTAGES.items()
        if until > now
    }


def get_outage_status() -> dict:
    """Structured outage info for dashboard."""
    now = datetime.now(timezone.utc)
    active = []
    for source, until in list(_ACTIVE_OUTAGES.items()):
        if until > now:
            active.append(
                {
                    "source": source,
                    "retry_after": until.isoformat(),
                    "retry_after_local": until.astimezone().strftime("%Y-%m-%d %H:%M"),
                    "message": f"{source.title()} outage — nudges delayed until retry window ends",
                }
            )
        else:
            _ACTIVE_OUTAGES.pop(source, None)
    return {"active": active, "count": len(active), "any_active": bool(active)}


def should_delay_for_downtime(
    *,
    error_reason: str | None,
    error_source: str | None,
    check_downtime: bool,
) -> DowntimeDecision:
    """
    If diagnosis says check_downtime (bank/gateway tech error), delay customer nudge.
    Demo: auto-delay bank_technical_error / gateway_technical_error for 4 hours
    unless outage cleared.
    """
    if not check_downtime:
        return DowntimeDecision(delay=False, reason="no_downtime_check")

    reason = (error_reason or "").lower()
    source = (error_source or "bank").lower()
    tech_reasons = {"bank_technical_error", "gateway_technical_error", "server_error"}

    # Auto-treat known tech errors as downtime windows for demo
    if reason in tech_reasons and source not in _ACTIVE_OUTAGES:
        mark_outage(source, hours=4.0)

    until = _ACTIVE_OUTAGES.get(source)
    if until and datetime.now(timezone.utc) < until:
        return DowntimeDecision(
            delay=True,
            reason=f"active_outage:{source}",
            retry_after=until,
        )

    return DowntimeDecision(delay=False, reason="clear")
