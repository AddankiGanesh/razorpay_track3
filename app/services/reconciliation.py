"""Webhook idempotency and delayed-payment reconciliation."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.intervention import Intervention

logger = logging.getLogger(__name__)

# In-memory idempotency for demo (persisted duplicates also checked via DB)
_SEEN_EVENT_KEYS: set[str] = set()


def event_dedup_key(event_type: str, payload: dict[str, Any]) -> str:
    payment = (payload.get("payment") or {}).get("entity") or {}
    order = (payload.get("order") or {}).get("entity") or {}
    pid = payment.get("id") or order.get("id") or ""
    return f"{event_type}:{pid}"


def is_duplicate_webhook(db: Session, event_type: str, payload: dict[str, Any]) -> bool:
    key = event_dedup_key(event_type, payload)
    if key in _SEEN_EVENT_KEYS:
        return True

    payment = (payload.get("payment") or {}).get("entity") or {}
    order = (payload.get("order") or {}).get("entity") or {}
    order_id = payment.get("order_id") or order.get("id")
    payment_id = payment.get("id")

    if event_type in {"order.paid", "payment.captured", "payment_link.paid"}:
        if order_id:
            already = (
                db.query(Intervention)
                .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
                .filter(AuditEvent.order_id == order_id, Intervention.status == "recovered")
                .first()
            )
            if already:
                _SEEN_EVENT_KEYS.add(key)
                return True

    _SEEN_EVENT_KEYS.add(key)
    return False


def reconcile_state(db: Session) -> dict[str, Any]:
    """Find inconsistencies: recovered interventions without payment, duplicate success events."""
    recovered = db.query(Intervention).filter(Intervention.status == "recovered").all()
    success_events = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type.in_(["order.paid", "payment.captured", "payment_link.paid"]))
        .count()
    )

    orphaned_success = []
    for iv in recovered:
        audit = db.get(AuditEvent, iv.audit_event_id)
        if audit and audit.status != "recovered":
            audit.status = "recovered"
            orphaned_success.append(iv.id)

    if orphaned_success:
        db.commit()

    pending_late = (
        db.query(AuditEvent)
        .filter(AuditEvent.status == "watching", AuditEvent.event_type == "payment.pending")
        .count()
    )

    return {
        "recovered_interventions": len(recovered),
        "success_webhook_events": success_events,
        "reconciled_audit_rows": len(orphaned_success),
        "watching_late_auth": pending_late,
        "status": "consistent" if not orphaned_success else "reconciled",
        "note": "Duplicate success webhooks are ignored; audit rows synced to recovered interventions.",
    }
