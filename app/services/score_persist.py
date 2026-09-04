"""Persist recovery score on audit events."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.diagnosis.engine import DiagnosisResult, diagnosis_engine
from app.execution.stopping import evaluate_stopping_rules
from app.models.audit import AuditEvent
from app.services.customer_context import build_customer_context
from app.services.discount import evaluate_discount
from app.services.llm_reasoning import explain_recovery_decision
from app.services.ml_recovery import predict_recovery_probability
from app.services.recovery_score import compute_recovery_score


def _primary_channel(diagnosis: DiagnosisResult) -> str:
    if diagnosis.channels:
        ch = diagnosis.channels[0]
        if diagnosis.action == "halted_revival_job":
            return "voice"
        return ch
    return "email"


def score_and_persist(
    db: Session,
    audit: AuditEvent,
    diagnosis: DiagnosisResult | None = None,
) -> dict[str, Any]:
    if diagnosis is None:
        diagnosis = diagnosis_engine.diagnose(audit.error_reason, audit.error_source, audit.error_step)

    customer = build_customer_context(
        db,
        email=audit.customer_email,
        contact=audit.customer_contact,
        exclude_audit_id=audit.id,
    )
    stop = evaluate_stopping_rules(db, audit=audit, action=diagnosis.action)
    channel = _primary_channel(diagnosis)

    hour = audit.created_at.hour if audit.created_at else None
    ml_prob = predict_recovery_probability(
        amount_paise=audit.amount_paise or 0,
        error_reason=audit.error_reason,
        diagnosis=diagnosis,
        customer=customer,
        channel=channel,
        payment_method=audit.payment_method,
        event_hour=hour,
    )

    result = compute_recovery_score(
        amount_paise=audit.amount_paise or 0,
        error_reason=audit.error_reason,
        diagnosis=diagnosis,
        customer=customer,
        channel=channel,
        will_stop=not stop.allow,
        ml_probability=ml_prob,
    )

    discount = evaluate_discount(
        amount_paise=audit.amount_paise or 0,
        recovery_score=result.score,
        error_reason=audit.error_reason,
        expected_recovery_paise=result.expected_recovery_paise,
    )

    payload = {
        "customer": customer.to_dict(),
        "channel": channel,
        "stopped": not stop.allow,
        "stop_reason": stop.reason if not stop.allow else None,
        "discount": discount,
        "diagnosis_path": diagnosis.path,
        **result.to_dict(),
    }
    ai_note = explain_recovery_decision(
        {
            "score": result.score,
            "pursue": result.pursue,
            "reason": audit.error_reason,
            "action": diagnosis.action,
            "persona": customer.persona,
            "ml_probability": result.ml_probability_percent,
        }
    )
    if ai_note:
        payload["ai_explanation"] = ai_note
    audit.recovery_score = result.score
    audit.recovery_score_json = json.dumps(payload)
    return payload
