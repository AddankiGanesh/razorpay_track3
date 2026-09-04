"""Poll Razorpay API for payment-link status — works without webhooks on localhost."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.execution.executor import attribute_recovery
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.services.razorpay_client import get_razorpay_client

logger = logging.getLogger(__name__)


def _payment_id_from_link(link: dict[str, Any]) -> str | None:
    payments = link.get("payments")
    if not payments:
        return None
    first = payments[0]
    if isinstance(first, dict):
        return first.get("payment_id") or first.get("id")
    if isinstance(first, str):
        return first
    return None


def _record_synced_payment(
    db: Session,
    *,
    intervention: Intervention,
    link: dict[str, Any],
    amount_paise: int,
    payment_id: str | None,
) -> AuditEvent:
    audit = db.get(AuditEvent, intervention.audit_event_id)
    audit_event = AuditEvent(
        event_type="payment_link.paid",
        category="payment_success",
        payment_id=payment_id,
        order_id=link.get("order_id") or (audit.order_id if audit else None),
        amount_paise=amount_paise,
        customer_email=audit.customer_email if audit else None,
        customer_contact=audit.customer_contact if audit else None,
        diagnosis_path="razorpay_api_sync",
        recommended_action="recovery_attributed",
        status="recovered",
        raw_payload=json.dumps({"source": "payment_link_sync", "link": link}),
    )
    db.add(audit_event)
    db.commit()
    db.refresh(audit_event)
    return audit_event


def sync_payment_link_for_intervention(db: Session, intervention: Intervention) -> dict[str, Any]:
    """Check Razorpay for payment-link status and attribute recovery if paid."""
    if not intervention.payment_link_id:
        return {"intervention_id": intervention.id, "ok": False, "reason": "no_link_id"}

    if intervention.status == "recovered" or intervention.amount_recovered_paise:
        return {
            "intervention_id": intervention.id,
            "ok": True,
            "synced": "already_recovered",
            "amount_rupees": (intervention.amount_recovered_paise or 0) / 100,
        }

    client = get_razorpay_client()
    try:
        link = client.payment_link.fetch(intervention.payment_link_id)
    except Exception as exc:
        logger.warning("Failed to fetch payment link %s: %s", intervention.payment_link_id, exc)
        return {"intervention_id": intervention.id, "ok": False, "reason": str(exc)[:200]}

    status = link.get("status")
    amount_paid = int(link.get("amount_paid") or 0)

    if status == "paid" and amount_paid > 0:
        payment_id = _payment_id_from_link(link)
        was_recovered = intervention.status == "recovered" or intervention.amount_recovered_paise
        attributed = attribute_recovery(
            db,
            order_id=link.get("order_id"),
            payment_id=payment_id,
            amount_paise=amount_paid,
            payment_link_id=intervention.payment_link_id,
        )
        if attributed and not was_recovered:
            logger.info(
                "Synced paid link %s → intervention %s Rs %.2f",
                intervention.payment_link_id,
                attributed.id,
                amount_paid / 100,
            )
            return {
                "intervention_id": attributed.id,
                "ok": True,
                "synced": "paid",
                "amount_rupees": amount_paid / 100,
                "payment_link_id": intervention.payment_link_id,
            }
        if attributed:
            return {
                "intervention_id": attributed.id,
                "ok": True,
                "synced": "already_recovered",
                "amount_rupees": (attributed.amount_recovered_paise or amount_paid) / 100,
                "payment_link_id": intervention.payment_link_id,
            }

    return {
        "intervention_id": intervention.id,
        "ok": True,
        "synced": "pending",
        "razorpay_status": status,
        "payment_link_id": intervention.payment_link_id,
    }


def sync_payment_link_by_id(db: Session, payment_link_id: str) -> dict[str, Any]:
    """Sync by Razorpay payment-link id (callback return URL)."""
    row = (
        db.query(Intervention)
        .filter(Intervention.payment_link_id == payment_link_id)
        .order_by(Intervention.created_at.desc())
        .first()
    )
    if not row:
        return {"ok": False, "reason": "no_intervention_for_link", "payment_link_id": payment_link_id}
    return sync_payment_link_for_intervention(db, row)


def sync_all_open_payment_links(db: Session, limit: int = 50) -> dict[str, Any]:
    """Poll all unpaid interventions that have a Razorpay payment-link id."""
    rows = (
        db.query(Intervention)
        .filter(
            Intervention.payment_link_id.isnot(None),
            Intervention.amount_recovered_paise.is_(None),
        )
        .order_by(Intervention.created_at.desc())
        .limit(limit)
        .all()
    )
    results = [sync_payment_link_for_intervention(db, row) for row in rows]
    paid = sum(1 for r in results if r.get("synced") == "paid")
    return {"checked": len(results), "newly_recovered": paid, "results": results}
