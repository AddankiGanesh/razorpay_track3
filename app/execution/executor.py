from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.diagnosis.engine import DiagnosisResult, diagnosis_engine
from app.execution.messages import build_recovery_message
from app.execution.stopping_rules import evaluate_stopping_rules
from app.models.audit import AuditEvent
from app.models.escalation import maybe_queue_escalation
from app.models.intervention import Intervention
from app.services.downtime import should_delay_for_downtime
from app.services.link_pool import (
    classify_link_error,
    find_reusable_link,
    link_error_label,
    mark_link_created,
    throttle_before_create,
)
from app.services.mandate_sequencer import format_sequence_message, plan_for_attempt
from app.services.notifications import send_recovery_notification
from app.services.razorpay_client import get_razorpay_client
from app.services.customer_context import build_customer_context
from app.services.llm_messages import personalize_recovery_message
from app.services.score_persist import score_and_persist
from app.services.voice import trigger_voice_recovery

logger = logging.getLogger(__name__)

SKIP_ACTIONS = {"wait_and_poll", "watch_for_auto_capture", "none_recovered"}
LINK_RETRY_DELAYS_SEC = (0.0, 2.0, 5.0, 10.0)


def _primary_channel(diagnosis: DiagnosisResult) -> str:
    if diagnosis.channels:
        return diagnosis.channels[0]
    return "email"


def _create_payment_link(
    *,
    amount_paise: int,
    description: str,
    customer_email: str | None,
    customer_contact: str | None,
    reference_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Create a Razorpay payment link. Returns (link_id, short_url, error_code)."""
    settings = get_settings()
    client = get_razorpay_client()
    payload: dict[str, Any] = {
        "amount": amount_paise,
        "currency": "INR",
        "description": description,
        "notify": {"sms": True, "email": True},
        "callback_url": f"http://127.0.0.1:{settings.app_port}/razorpay/return",
        "callback_method": "get",
    }
    if customer_email:
        payload["customer"] = {"email": customer_email}
        if customer_contact:
            payload["customer"]["contact"] = customer_contact
    payload["reference_id"] = f"rr_{uuid.uuid4().hex[:16]}"

    last_exc: Exception | None = None
    for attempt, delay in enumerate(LINK_RETRY_DELAYS_SEC, start=1):
        if delay:
            time.sleep(delay)
        throttle_before_create()
        try:
            link = client.payment_link.create(payload)
            mark_link_created()
            return link.get("id"), link.get("short_url"), None
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            error_code = classify_link_error(exc)
            retryable = (
                error_code == "rate_limited"
                and attempt < len(LINK_RETRY_DELAYS_SEC)
            )
            if retryable:
                logger.warning("Payment link rate-limited, retry %s/%s", attempt, len(LINK_RETRY_DELAYS_SEC))
                continue
            logger.warning("Failed to create payment link (%s): %s", error_code, exc)
            return None, None, error_code
    if last_exc:
        logger.error("Payment link creation failed after retries: %s", last_exc)
        return None, None, classify_link_error(last_exc)
    return None, None, "api_error"


def _resolve_payment_link(
    db: Session,
    *,
    amount_paise: int,
    description: str,
    customer_email: str | None,
    customer_contact: str | None,
    reference_id: str | None,
) -> tuple[str | None, str | None, str | None, bool]:
    """Try create, then reuse unpaid links from DB or Razorpay API."""
    link_id, link_url, link_error = _create_payment_link(
        amount_paise=amount_paise,
        description=description,
        customer_email=customer_email,
        customer_contact=customer_contact,
        reference_id=reference_id,
    )
    if link_url:
        return link_id, link_url, None, False

    reused_id, reused_url = find_reusable_link(db, amount_paise)
    if reused_url:
        return reused_id, reused_url, link_error, True
    return None, None, link_error, False


def refresh_intervention_link(db: Session, intervention: Intervention) -> bool:
    """Re-attempt link resolution for sent_no_link interventions."""
    if intervention.payment_link_url or intervention.status == "recovered":
        return bool(intervention.payment_link_url)

    audit = db.get(AuditEvent, intervention.audit_event_id)
    if not audit:
        return False

    amount = intervention.amount_at_risk_paise or audit.amount_paise or 0
    diagnosis = diagnosis_engine.diagnose(audit.error_reason, audit.error_source, audit.error_step)
    diagnosis.action = intervention.action

    link_id, link_url, link_error, link_reused = _resolve_payment_link(
        db,
        amount_paise=amount,
        description=f"RevRecover retry for {audit.order_id or audit.payment_id or 'payment'}",
        customer_email=audit.customer_email,
        customer_contact=audit.customer_contact,
        reference_id=audit.order_id or audit.payment_id,
    )

    if link_url:
        intervention.payment_link_id = link_id
        intervention.payment_link_url = link_url
        intervention.status = "reused_link" if link_reused else "sent"
        intervention.link_error = None
        intervention.message = build_recovery_message(
            diagnosis=diagnosis,
            amount_rupees=amount / 100,
            payment_link_url=link_url,
        )
        send_recovery_notification(
            channel=intervention.channel,
            to_email=audit.customer_email,
            to_phone=audit.customer_contact,
            subject=f"Complete your Rs {amount / 100:.0f} payment",
            body=intervention.message or "",
            payment_link_url=link_url,
        )
        db.commit()
        db.refresh(intervention)
        return True

    if link_error and not intervention.link_error:
        intervention.link_error = link_error
        db.commit()
    return False


def execute_recovery(db: Session, audit: AuditEvent, diagnosis: DiagnosisResult | None = None) -> Intervention | None:
    if audit.status in {"recovered", "intervention_sent", "skipped_stopping_rule"}:
        return None

    if diagnosis is None:
        diagnosis = diagnosis_engine.diagnose(audit.error_reason, audit.error_source, audit.error_step)

    if diagnosis.action in SKIP_ACTIONS:
        audit.status = "skipped"
        db.commit()
        return None

    settings = get_settings()
    if not audit.customer_email:
        audit.customer_email = settings.demo_customer_email
    if not audit.customer_contact:
        audit.customer_contact = settings.demo_customer_contact

    score_payload = score_and_persist(db, audit, diagnosis)

    downtime = should_delay_for_downtime(
        error_reason=diagnosis.reason or audit.error_reason,
        error_source=diagnosis.fault or audit.error_source,
        check_downtime=diagnosis.check_downtime,
    )
    if downtime.delay:
        audit.status = "delayed_for_downtime"
        audit.recommended_action = f"delay_retry:{downtime.reason}"
        db.commit()
        message = (
            f"Bank/gateway outage detected ({downtime.reason}). "
            f"Customer nudge deferred until {downtime.retry_after}."
        )
        intervention = Intervention(
            audit_event_id=audit.id,
            action="delay_retry",
            channel="system",
            message=message,
            status="delayed",
            amount_at_risk_paise=audit.amount_paise or 0,
        )
        db.add(intervention)
        db.commit()
        db.refresh(intervention)
        logger.info("Downtime delay for audit %s: %s", audit.id, downtime.reason)
        return intervention

    stop = evaluate_stopping_rules(
        db,
        audit=audit,
        action=diagnosis.action,
    )
    if not stop.allow:
        audit.status = "skipped_stopping_rule"
        audit.recommended_action = f"stopped:{stop.reason}"
        db.commit()
        logger.info(
            "Stopping rule blocked intervention: %s (prior=%s)",
            stop.reason,
            stop.prior_count,
        )
        return None

    amount_paise = audit.amount_paise or 0
    channel = _primary_channel(diagnosis)
    mandate_plan: dict[str, Any] | None = None
    if diagnosis.action == "mandate_retry_sequence":
        mandate_plan = plan_for_attempt(stop.prior_count + 1)
        channel = mandate_plan["current"]["channel"]

    link_id, link_url, link_error, link_reused = _resolve_payment_link(
        db,
        amount_paise=amount_paise,
        description=f"RevRecover retry for {audit.order_id or audit.payment_id or 'payment'}",
        customer_email=audit.customer_email,
        customer_contact=audit.customer_contact,
        reference_id=audit.order_id or audit.payment_id,
    )

    message = build_recovery_message(
        diagnosis=diagnosis,
        amount_rupees=amount_paise / 100,
        payment_link_url=link_url,
    )
    discount = score_payload.get("discount") or {}
    if discount.get("apply"):
        message += (
            f"\n\nLimited-time offer: complete payment with "
            f"₹{discount.get('discount_rupees', 0)} off (net recovery still positive)."
        )
    if mandate_plan:
        message = format_sequence_message(
            amount_rupees=amount_paise / 100,
            payment_link_url=link_url,
            attempt=mandate_plan["attempt"],
        )

    customer = build_customer_context(
        db,
        email=audit.customer_email,
        contact=audit.customer_contact,
        exclude_audit_id=audit.id,
    )
    message, message_source = personalize_recovery_message(
        message,
        diagnosis=diagnosis,
        customer=customer,
        amount_rupees=amount_paise / 100,
        recovery_score=score_payload.get("score", 50),
        payment_link_url=link_url,
    )
    if message_source == "llm":
        message = f"[AI-personalized]\n{message}"

    if link_url and link_reused:
        iv_status = "reused_link"
    elif link_url:
        iv_status = "sent"
    else:
        iv_status = "sent_no_link"

    notify = send_recovery_notification(
        channel=channel,
        to_email=audit.customer_email,
        to_phone=audit.customer_contact,
        subject=f"Complete your Rs {amount_paise / 100:.0f} payment",
        body=message,
        payment_link_url=link_url,
    )

    voice = trigger_voice_recovery(
        to_phone=audit.customer_contact,
        amount_paise=amount_paise,
        payment_link_url=link_url,
        action=diagnosis.action,
    )
    if voice.get("queued"):
        if diagnosis.action == "halted_revival_job":
            channel = "voice"
            if voice.get("script"):
                message = f"{message}\n\n[IVR SCRIPT]\n{voice['script']}"

    intervention = Intervention(
        audit_event_id=audit.id,
        action=diagnosis.action,
        channel=channel,
        message=message,
        payment_link_id=link_id,
        payment_link_url=link_url,
        link_error=link_error,
        status=iv_status,
        amount_at_risk_paise=amount_paise,
    )
    db.add(intervention)

    audit.status = "intervention_sent"
    audit.recommended_action = diagnosis.action
    db.commit()
    db.refresh(intervention)

    maybe_queue_escalation(
        db,
        audit_event_id=audit.id,
        intervention_id=intervention.id,
        customer_email=audit.customer_email,
        amount_paise=amount_paise,
        recovery_score=score_payload.get("score") or audit.recovery_score or 0,
        error_reason=audit.error_reason,
    )
    db.commit()

    logger.info(
        "[%s] Intervention %s | action=%s | link=%s | reused=%s | error=%s | notify_sent=%s | voice=%s",
        channel.upper(),
        intervention.id,
        diagnosis.action,
        link_url or "none",
        link_reused,
        link_error,
        notify.get("sent"),
        voice.get("queued"),
    )
    return intervention


def attribute_recovery(
    db: Session,
    *,
    order_id: str | None,
    payment_id: str | None,
    amount_paise: int,
    payment_link_id: str | None = None,
) -> Intervention | None:
    if not order_id and not payment_id and not payment_link_id:
        return None

    # Idempotent: already attributed for this order/payment/link
    if order_id:
        existing = (
            db.query(Intervention)
            .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
            .filter(AuditEvent.order_id == order_id, Intervention.status == "recovered")
            .first()
        )
        if existing:
            logger.info("Recovery already attributed for order %s — skipping duplicate", order_id)
            return existing
    if payment_link_id:
        existing = (
            db.query(Intervention)
            .filter(Intervention.payment_link_id == payment_link_id, Intervention.status == "recovered")
            .first()
        )
        if existing:
            return existing

    query = db.query(Intervention).filter(Intervention.amount_recovered_paise.is_(None))
    candidates = query.order_by(Intervention.created_at.desc()).limit(50).all()

    for intervention in candidates:
        if intervention.status == "recovered":
            continue
        if payment_link_id and intervention.payment_link_id == payment_link_id:
            pass
        else:
            audit = db.get(AuditEvent, intervention.audit_event_id)
            if not audit:
                continue
            if order_id and audit.order_id == order_id:
                pass
            elif payment_id and audit.payment_id == payment_id:
                pass
            else:
                continue

        intervention.amount_recovered_paise = amount_paise
        intervention.recovered_payment_id = payment_id
        intervention.status = "recovered"
        audit = db.get(AuditEvent, intervention.audit_event_id)
        if audit:
            audit.status = "recovered"
            from app.models.escalation import resolve_escalations_for_audit

            resolve_escalations_for_audit(
                db,
                audit.id,
                note="High-value case — auto-resolved when payment completed",
            )
        db.commit()
        db.refresh(intervention)
        logger.info("Recovered Rs %.2f attributed to intervention %s", amount_paise / 100, intervention.id)
        return intervention

    return None


def retry_failed_links(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    """Re-attempt link creation for interventions without a Razorpay URL."""
    rows = (
        db.query(Intervention)
        .filter(Intervention.status == "sent_no_link")
        .order_by(Intervention.created_at.desc())
        .limit(limit)
        .all()
    )
    results: list[dict[str, Any]] = []
    for iv in rows:
        ok = refresh_intervention_link(db, iv)
        db.refresh(iv)
        results.append(
            {
                "intervention_id": iv.id,
                "ok": ok,
                "payment_link_url": iv.payment_link_url,
                "status": iv.status,
                "link_error": iv.link_error,
            }
        )
    return results
