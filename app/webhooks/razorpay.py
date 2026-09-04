from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.diagnosis.engine import DiagnosisResult, diagnosis_engine
from app.execution.executor import attribute_recovery, execute_recovery
from app.models.audit import AuditEvent
from app.services.auto_capture import try_auto_capture
from app.services.llm_diagnosis import llm_enrich_diagnosis
from app.services.mandate_sequencer import plan_for_intervention
from app.services.reconciliation import is_duplicate_webhook, reconcile_state
from app.webhooks.verify import verify_razorpay_signature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _entity_from_payload(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    block = payload.get(key)
    if isinstance(block, dict):
        entity = block.get("entity")
        if isinstance(entity, dict):
            return entity
    return None


def _category_for_event(event_type: str) -> str:
    mapping = {
        "payment.failed": "payment_failure",
        "payment.authorized": "authorized_not_captured",
        "payment.captured": "payment_success",
        "payment.pending": "late_auth_pending",
        "order.paid": "checkout_success",
        "subscription.pending": "subscription_pending",
        "subscription.halted": "subscription_halted",
        "subscription.charged": "subscription_success",
        "payment_link.paid": "b2b_success",
        "payment_link.expired": "b2b_expired",
    }
    return mapping.get(event_type, "unknown")


def _persist_audit(
    db: Session,
    *,
    event_type: str,
    payload: dict[str, Any],
    diagnosis_path: str | None = None,
    recommended_action: str | None = None,
    status: str = "detected",
) -> AuditEvent:
    payment = _entity_from_payload(payload, "payment") or {}
    order = _entity_from_payload(payload, "order") or {}
    subscription = _entity_from_payload(payload, "subscription") or {}
    payment_link = _entity_from_payload(payload, "payment_link") or {}

    audit = AuditEvent(
        event_type=event_type,
        category=_category_for_event(event_type),
        payment_id=payment.get("id"),
        order_id=payment.get("order_id") or order.get("id"),
        subscription_id=subscription.get("id"),
        error_reason=payment.get("error_reason"),
        error_source=payment.get("error_source"),
        error_step=payment.get("error_step"),
        payment_method=payment.get("method"),
        amount_paise=payment.get("amount") or order.get("amount") or payment_link.get("amount"),
        customer_email=payment.get("email") or order.get("email"),
        customer_contact=payment.get("contact") or order.get("contact"),
        diagnosis_path=diagnosis_path,
        recommended_action=recommended_action,
        status=status,
        raw_payload=json.dumps(payload),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def _run_recovery(
    db: Session,
    audit: AuditEvent,
    diagnosis: DiagnosisResult | None = None,
) -> dict[str, Any] | None:
    intervention = execute_recovery(db, audit, diagnosis)
    db.refresh(audit)
    intended = diagnosis.action if diagnosis else audit.recommended_action
    if not intervention:
        stop_reason = audit.recommended_action or ""
        if stop_reason.startswith("stopped:"):
            stop_reason = stop_reason.removeprefix("stopped:")
        return {
            "intervention_id": None,
            "channel": None,
            "payment_link_url": None,
            "message_preview": None,
            "status": audit.status,
            "recommended_action": audit.recommended_action,
            "intended_action": intended,
            "stop_reason": stop_reason if audit.status == "skipped_stopping_rule" else None,
            "stopped": audit.status == "skipped_stopping_rule",
        }
    return {
        "intervention_id": intervention.id,
        "channel": intervention.channel,
        "payment_link_url": intervention.payment_link_url or f"/pay/{intervention.id}",
        "razorpay_payment_link": intervention.payment_link_url,
        "demo_pay_url": f"/pay/{intervention.id}",
        "link_error": intervention.link_error,
        "message_preview": (intervention.message or "")[:160],
        "status": intervention.status,
        "recommended_action": audit.recommended_action,
        "intended_action": intended,
        "stopped": False,
        "delayed": intervention.status == "delayed",
        "mandate_plan": plan_for_intervention(db, intervention, audit),
    }


def _handle_payment_failed(db: Session, payload: dict[str, Any]) -> tuple[AuditEvent, dict[str, Any] | None]:
    payment = _entity_from_payload(payload, "payment") or {}
    diagnosis = diagnosis_engine.diagnose(
        error_reason=payment.get("error_reason"),
        error_source=payment.get("error_source"),
        error_step=payment.get("error_step"),
    )
    diagnosis = llm_enrich_diagnosis(
        diagnosis, amount_paise=int(payment.get("amount") or 0)
    )

    logger.info(
        "Payment failed: id=%s reason=%s action=%s path=%s",
        payment.get("id"),
        diagnosis.reason,
        diagnosis.action,
        diagnosis.path,
    )

    audit = _persist_audit(
        db,
        event_type="payment.failed",
        payload=payload,
        diagnosis_path=diagnosis.path,
        recommended_action=diagnosis.action,
        status="diagnosed",
    )
    recovery = _run_recovery(db, audit, diagnosis)
    return audit, recovery


def _handle_payment_authorized(db: Session, payload: dict[str, Any]) -> tuple[AuditEvent, dict[str, Any] | None]:
    from app.config import get_settings

    payment = _entity_from_payload(payload, "payment") or {}
    payment_id = payment.get("id")
    amount = payment.get("amount") or 0
    logger.info("Payment authorized: id=%s amount=%s", payment_id, amount)
    audit = _persist_audit(
        db,
        event_type="payment.authorized",
        payload=payload,
        diagnosis_path="known_rule",
        recommended_action="auto_capture",
        status="detected",
    )
    recovery = None
    if get_settings().auto_capture_enabled and payment_id and amount:
        capture_result = try_auto_capture(
            db, audit=audit, payment_id=payment_id, amount_paise=int(amount)
        )
        recovery = capture_result
    return audit, recovery


def _handle_subscription_event(
    db: Session, event_type: str, payload: dict[str, Any]
) -> tuple[AuditEvent, dict[str, Any] | None]:
    action_map = {
        "subscription.pending": "proactive_customer_nudge",
        "subscription.halted": "halted_revival_job",
        "subscription.charged": "none_recovered",
    }
    action = action_map.get(event_type, "review")
    audit = _persist_audit(
        db,
        event_type=event_type,
        payload=payload,
        diagnosis_path="known_rule",
        recommended_action=action,
        status="diagnosed" if event_type != "subscription.charged" else "recovered",
    )
    recovery = None
    if event_type in {"subscription.pending", "subscription.halted"}:
        diagnosis = diagnosis_engine.diagnose(None, "customer", "payment_authorization")
        diagnosis.action = action
        # Halted subscriptions: Razorpay will not auto-charge again — recovery must be explicit
        if event_type == "subscription.halted":
            diagnosis.channels = ["email", "sms"]
            diagnosis.priority = "high"
            diagnosis.check_downtime = False
        recovery = _run_recovery(db, audit, diagnosis)
    return audit, recovery


def _handle_recovery_success(db: Session, event_type: str, payload: dict[str, Any]) -> tuple[AuditEvent, dict[str, Any] | None]:
    if is_duplicate_webhook(db, event_type, payload):
        payment = _entity_from_payload(payload, "payment") or {}
        order = _entity_from_payload(payload, "order") or {}
        logger.info("Duplicate success webhook ignored: %s order=%s", event_type, order.get("id") or payment.get("order_id"))
        audit = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.order_id == (payment.get("order_id") or order.get("id")),
                AuditEvent.status == "recovered",
            )
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
        if audit:
            return audit, {"duplicate": True, "note": "Already recovered — no double attribution"}
        audit = _persist_audit(db, event_type=event_type, payload=payload, status="recovered")
        return audit, {"duplicate": True, "note": "Duplicate webhook logged only"}

    payment = _entity_from_payload(payload, "payment") or {}
    order = _entity_from_payload(payload, "order") or {}
    payment_link = _entity_from_payload(payload, "payment_link") or {}
    audit = _persist_audit(db, event_type=event_type, payload=payload, status="recovered")
    attributed = attribute_recovery(
        db,
        order_id=payment.get("order_id") or order.get("id"),
        payment_id=payment.get("id"),
        amount_paise=payment.get("amount") or order.get("amount") or payment_link.get("amount") or 0,
        payment_link_id=payment_link.get("id"),
    )
    recovery = {"attributed_intervention_id": attributed.id} if attributed else None
    return audit, recovery


def _handle_payment_pending(db: Session, payload: dict[str, Any]) -> tuple[AuditEvent, dict[str, Any] | None]:
    payment = _entity_from_payload(payload, "payment") or {}
    amount = payment.get("amount") or 0
    audit = _persist_audit(
        db,
        event_type="payment.pending",
        payload=payload,
        diagnosis_path="known_rule",
        recommended_action="wait_and_poll_late_auth",
        status="detected",
    )
    recovery = handle_late_auth(
        db,
        audit=audit,
        payment_id=payment.get("id"),
        amount_paise=int(amount or 0),
    )
    return audit, {
        "intervention_id": recovery.get("intervention_id"),
        "channel": "system",
        "payment_link_url": None,
        "message_preview": recovery.get("note") or "Late auth watch — no customer nudge",
        "status": "watching",
        "recommended_action": "wait_and_poll_late_auth",
        "stopped": False,
        "delayed": False,
    }


def _handle_payment_link_expired(db: Session, payload: dict[str, Any]) -> tuple[AuditEvent, dict[str, Any] | None]:
    audit = _persist_audit(
        db,
        event_type="payment_link.expired",
        payload=payload,
        diagnosis_path="known_rule",
        recommended_action="regenerate_payment_link",
        status="diagnosed",
    )
    audit.error_reason = "payment_link.expired"
    diagnosis = diagnosis_engine.diagnose(None, "customer", "payment_authorization")
    diagnosis.action = "regenerate_payment_link"
    recovery = _run_recovery(db, audit, diagnosis)
    return audit, recovery


EVENT_HANDLERS = {
    "payment.failed": _handle_payment_failed,
    "payment.authorized": _handle_payment_authorized,
    "payment.pending": _handle_payment_pending,
    "payment.captured": lambda db, p: _handle_recovery_success(db, "payment.captured", p),
    "order.paid": lambda db, p: _handle_recovery_success(db, "order.paid", p),
    "subscription.pending": lambda db, p: _handle_subscription_event(db, "subscription.pending", p),
    "subscription.halted": lambda db, p: _handle_subscription_event(db, "subscription.halted", p),
    "subscription.charged": lambda db, p: _handle_subscription_event(db, "subscription.charged", p),
    "payment_link.paid": lambda db, p: _handle_recovery_success(db, "payment_link.paid", p),
    "payment_link.expired": _handle_payment_link_expired,
}


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
):
    settings = get_settings()
    body = await request.body()

    if settings.razorpay_webhook_secret:
        if not x_razorpay_signature or not verify_razorpay_signature(
            body, x_razorpay_signature, settings.razorpay_webhook_secret
        ):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
    else:
        logger.warning("RAZORPAY_WEBHOOK_SECRET not set — skipping signature verification (dev only)")

    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    event_type = event.get("event", "unknown")
    payload = event.get("payload", {})

    handler = EVENT_HANDLERS.get(event_type)
    if handler:
        audit, recovery = handler(db, payload)
        return {
            "ok": True,
            "event": event_type,
            "audit_id": audit.id,
            "category": audit.category,
            "recommended_action": audit.recommended_action,
            "diagnosis_path": audit.diagnosis_path,
            "recovery": recovery,
        }

    audit = _persist_audit(db, event_type=event_type, payload=payload, status="logged_unhandled")
    return {"ok": True, "event": event_type, "audit_id": audit.id, "handled": False}


@router.get("/reconcile")
def webhook_reconcile(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Reconcile recovered interventions vs success webhooks (demo helper)."""
    return reconcile_state(db)
