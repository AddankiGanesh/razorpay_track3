"""Customer intelligence — local history + demo personas + optional Razorpay fetch."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from app.models.audit import AuditEvent
from app.models.intervention import Intervention

logger = logging.getLogger(__name__)

_RZ_PAYMENT_CACHE: dict[str, int] = {}


def clear_customer_cache() -> None:
    """Clear Razorpay payment count cache after demo reset."""
    _RZ_PAYMENT_CACHE.clear()

_PROFILES_PATH = PROJECT_ROOT / "app" / "data" / "demo_customers.json"


@dataclass
class CustomerContext:
    email: str | None
    contact: str | None
    name: str
    successful_payments: int
    subscription_months: int
    prior_failures_30d: int
    prior_failures_72h: int
    prior_recoveries: int
    nudges_sent_72h: int
    reminders_ignored: int
    checkout_visits: int
    engagement: str
    persona: str
    razorpay_payments_found: int
    positive_notes: list[str] = field(default_factory=list)
    negative_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "contact": self.contact,
            "name": self.name,
            "successful_payments": self.successful_payments,
            "subscription_months": self.subscription_months,
            "prior_failures_30d": self.prior_failures_30d,
            "prior_failures_72h": self.prior_failures_72h,
            "prior_recoveries": self.prior_recoveries,
            "nudges_sent_72h": self.nudges_sent_72h,
            "reminders_ignored": self.reminders_ignored,
            "checkout_visits": self.checkout_visits,
            "engagement": self.engagement,
            "persona": self.persona,
            "razorpay_payments_found": self.razorpay_payments_found,
            "positive_notes": self.positive_notes,
            "negative_notes": self.negative_notes,
        }


def _load_demo_profiles() -> dict[str, dict[str, Any]]:
    if not _PROFILES_PATH.exists():
        return {}
    try:
        data = json.loads(_PROFILES_PATH.read_text(encoding="utf-8"))
        return data.get("profiles", {})
    except Exception as exc:
        logger.warning("Failed to load demo customer profiles: %s", exc)
        return {}


def _fetch_razorpay_payment_count(email: str | None) -> int:
    if not email:
        return 0
    if email in _RZ_PAYMENT_CACHE:
        return _RZ_PAYMENT_CACHE[email]
    try:
        from app.services.razorpay_client import get_razorpay_client

        client = get_razorpay_client()
        result = client.payment.all({"email": email, "count": 100})
        items = result.get("items", []) if isinstance(result, dict) else []
        captured = sum(1 for p in items if p.get("status") == "captured")
        _RZ_PAYMENT_CACHE[email] = captured
        return captured
    except Exception as exc:
        logger.debug("Razorpay payment history fetch skipped: %s", exc)
        return 0


def build_customer_context(
    db: Session,
    *,
    email: str | None,
    contact: str | None = None,
    exclude_audit_id: str | None = None,
) -> CustomerContext:
    now = datetime.now(timezone.utc)
    since_72h = now - timedelta(hours=72)
    since_30d = now - timedelta(days=30)

    profiles = _load_demo_profiles()
    profile = profiles.get(email or "", {})

    q_fail_72 = db.query(func.count(AuditEvent.id)).filter(
        AuditEvent.customer_email == email,
        AuditEvent.event_type.in_(
            ["payment.failed", "subscription.pending", "subscription.halted", "payment_link.expired"]
        ),
        AuditEvent.created_at >= since_72h,
    )
    if exclude_audit_id:
        q_fail_72 = q_fail_72.filter(AuditEvent.id != exclude_audit_id)
    prior_failures_72h = int(q_fail_72.scalar() or 0)

    q_fail_30 = db.query(func.count(AuditEvent.id)).filter(
        AuditEvent.customer_email == email,
        AuditEvent.event_type.in_(
            ["payment.failed", "subscription.pending", "subscription.halted", "payment_link.expired"]
        ),
        AuditEvent.created_at >= since_30d,
    )
    if exclude_audit_id:
        q_fail_30 = q_fail_30.filter(AuditEvent.id != exclude_audit_id)
    prior_failures_30d = int(q_fail_30.scalar() or 0)

    prior_recoveries = int(
        db.query(func.count(Intervention.id))
        .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
        .filter(AuditEvent.customer_email == email, Intervention.status == "recovered")
        .scalar()
        or 0
    )

    nudges_sent_72h = int(
        db.query(func.count(Intervention.id))
        .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
        .filter(AuditEvent.customer_email == email, Intervention.created_at >= since_72h)
        .scalar()
        or 0
    )

    rz_captured = _fetch_razorpay_payment_count(email)
    successful = max(
        int(profile.get("successful_payments", 0)),
        prior_recoveries,
        rz_captured,
    )

    ctx = CustomerContext(
        email=email,
        contact=contact,
        name=str(profile.get("name", email or "Customer")),
        successful_payments=successful,
        subscription_months=int(profile.get("subscription_months", 0)),
        prior_failures_30d=max(prior_failures_30d, int(profile.get("prior_failures_30d", 0))),
        prior_failures_72h=prior_failures_72h,
        prior_recoveries=prior_recoveries,
        nudges_sent_72h=nudges_sent_72h,
        reminders_ignored=int(profile.get("reminders_ignored", 0)),
        checkout_visits=int(profile.get("checkout_visits", 0)),
        engagement=str(profile.get("engagement", "medium")),
        persona=str(profile.get("persona", "standard")),
        razorpay_payments_found=rz_captured,
    )

    if ctx.successful_payments >= 8:
        ctx.positive_notes.append(f"{ctx.successful_payments} previous successful payments")
    if ctx.subscription_months >= 6:
        ctx.positive_notes.append(f"{ctx.subscription_months} months subscription tenure")
    if ctx.prior_recoveries > 0:
        ctx.positive_notes.append(f"{ctx.prior_recoveries} prior recoveries on record")
    if ctx.checkout_visits >= 2:
        ctx.positive_notes.append("High checkout intent (multiple visits)")
    if ctx.engagement == "high":
        ctx.positive_notes.append("High historical engagement")

    if ctx.prior_failures_30d >= 3:
        ctx.negative_notes.append(f"{ctx.prior_failures_30d} failures in last 30 days")
    if ctx.reminders_ignored >= 2:
        ctx.negative_notes.append(f"{ctx.reminders_ignored} reminders ignored")
    if ctx.nudges_sent_72h >= 2:
        ctx.negative_notes.append(f"{ctx.nudges_sent_72h} nudges already sent (72h)")
    if ctx.engagement == "low":
        ctx.negative_notes.append("Low engagement customer")

    return ctx
