"""Rebuild pipeline + FireResult from stored audit events (real webhooks or lab fires)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.lab.scenarios import FireResult
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.services.link_pool import pay_path_explanation
from app.services.mandate_sequencer import plan_for_intervention


def fire_result_from_audit(
    db: Session,
    audit: AuditEvent,
    intervention: Intervention | None = None,
) -> FireResult:
    """Convert a persisted audit (+ optional intervention) into a FireResult for the UI pipeline."""
    stopped = audit.status == "skipped_stopping_rule"
    stop_reason: str | None = None
    if stopped and audit.recommended_action:
        stop_reason = audit.recommended_action.removeprefix("stopped:")

    delayed = audit.status == "delayed_for_downtime" or (
        intervention is not None and intervention.status == "delayed"
    )

    razorpay_link = intervention.payment_link_url if intervention else None
    intervention_id = intervention.id if intervention else None
    demo_url = f"/pay/{intervention_id}" if intervention_id else None

    if intervention and intervention.status == "recovered":
        status = "recovered"
    elif audit.event_type in {"order.paid", "payment.captured", "payment_link.paid"}:
        status = "recovered" if intervention and intervention.status == "recovered" else audit.status
    elif intervention:
        status = intervention.status
    else:
        status = audit.status

    label = audit.event_type.replace("_", " ").replace(".", " · ")
    if audit.error_reason:
        label = f"{audit.error_reason} ({audit.event_type})"

    mandate_plan = None
    if intervention and intervention.action == "mandate_retry_sequence":
        mandate_plan = plan_for_intervention(db, intervention, audit)

    intended = audit.recommended_action
    if stopped and intervention:
        intended = intervention.action

    iv_status = intervention.status if intervention else status
    path_note = pay_path_explanation(
        amount_paise=audit.amount_paise or 0,
        status=iv_status,
        has_razorpay_url=bool(razorpay_link),
        link_error=intervention.link_error if intervention else None,
    )

    return FireResult(
        scenario_id=audit.event_type,
        label=label,
        group=audit.category or "unknown",
        event=audit.event_type,
        order_id=audit.order_id,
        amount_paise=audit.amount_paise or 0,
        recommended_action=audit.recommended_action,
        payment_link_url=razorpay_link or demo_url,
        channel=intervention.channel if intervention else None,
        message_preview=(intervention.message or "")[:160] if intervention else None,
        ok=True,
        status=status,
        delayed=delayed,
        stopped=stopped,
        mandate_plan=mandate_plan,
        intervention_id=intervention_id,
        demo_pay_url=demo_url,
        razorpay_payment_link=razorpay_link,
        error_reason=audit.error_reason,
        diagnosis_path=audit.diagnosis_path,
        intended_action=intended,
        stop_reason=stop_reason,
        link_error=intervention.link_error if intervention else None,
        pay_path_note=path_note or None,
    )
