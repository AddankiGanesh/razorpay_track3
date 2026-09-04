"""Customer recovery journey — universal timeline for every failure scenario."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.lab.pipeline import build_recovery_pipeline
from app.lab.replay import fire_result_from_audit
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.models.promise import PromiseToPay
from app.models.scheduled_action import ScheduledAction
from app.services.score_cache import get_scored_audit
from app.services.voice import should_use_voice


def _stage_status(done: bool, current: bool, blocked: bool = False) -> str:
    if blocked:
        return "blocked"
    if current:
        return "current"
    if done:
        return "done"
    return "pending"


def compute_current_stage(
    *,
    audit: AuditEvent,
    intervention: Intervention | None,
    promise: PromiseToPay | None,
    scheduled: list[ScheduledAction],
) -> str:
    if intervention and intervention.status == "recovered":
        return "recovered"
    if audit.event_type in {"order.paid", "payment.captured", "payment_link.paid"}:
        return "recovered"
    if promise and promise.status == "active":
        pending_sched = any(s.status == "pending" for s in scheduled)
        if pending_sched:
            return "waiting_promise_date"
        return "promise_recorded"
    if audit.status == "skipped_stopping_rule":
        return "stopped"
    if audit.status == "delayed_for_downtime" or (intervention and intervention.status == "delayed"):
        return "delayed"
    if audit.status == "watching" or audit.recommended_action in {
        "wait_and_poll",
        "wait_and_poll_late_auth",
    }:
        return "watching"
    if intervention:
        if intervention.status in {"sent", "reused_link", "sent_no_link"}:
            return "awaiting_payment"
        return intervention.status
    if audit.status == "detected":
        return "detected"
    return audit.status or "unknown"


def build_customer_journey(
    db: Session,
    audit: AuditEvent,
    intervention: Intervention | None = None,
) -> dict[str, Any]:
    if intervention is None:
        intervention = (
            db.query(Intervention)
            .filter(Intervention.audit_event_id == audit.id)
            .order_by(Intervention.created_at.desc())
            .first()
        )

    promise = None
    if intervention:
        promise = (
            db.query(PromiseToPay)
            .filter(
                PromiseToPay.intervention_id == intervention.id,
                PromiseToPay.status == "active",
            )
            .order_by(PromiseToPay.created_at.desc())
            .first()
        )
    if not promise:
        promise = (
            db.query(PromiseToPay)
            .filter(
                PromiseToPay.audit_event_id == audit.id,
                PromiseToPay.status == "active",
            )
            .order_by(PromiseToPay.created_at.desc())
            .first()
        )

    scheduled: list[ScheduledAction] = []
    if intervention:
        scheduled = (
            db.query(ScheduledAction)
            .filter(ScheduledAction.intervention_id == intervention.id)
            .order_by(ScheduledAction.run_at.asc())
            .all()
        )

    current_stage = compute_current_stage(
        audit=audit, intervention=intervention, promise=promise, scheduled=scheduled
    )

    result = fire_result_from_audit(db, audit, intervention)
    pipeline = build_recovery_pipeline(result)

    recovery_intel: dict[str, Any]
    if audit.recovery_score_json:
        try:
            recovery_intel = json.loads(audit.recovery_score_json)
        except json.JSONDecodeError:
            recovery_intel = get_scored_audit(db, audit, allow_full_score=True)
    else:
        recovery_intel = get_scored_audit(db, audit, allow_full_score=True)

    action = intervention.action if intervention else (result.intended_action or audit.recommended_action or "")
    amount_paise = audit.amount_paise or (intervention.amount_at_risk_paise if intervention else 0) or 0
    voice_eligible = should_use_voice(amount_paise=amount_paise, action=action)
    if intervention and intervention.channel == "voice":
        voice_eligible = True

    recovered = current_stage == "recovered"
    stopped = current_stage == "stopped"
    delayed = current_stage == "delayed"
    watching = current_stage == "watching"
    executed = intervention is not None and not stopped and not delayed and not watching
    has_promise = promise is not None
    reminder_pending = any(s.status == "pending" for s in scheduled)
    reminder_sent = any(s.status == "sent" for s in scheduled)

    timeline = [
        {
            "key": "detect",
            "title": "Payment failure detected",
            "detail": f"{audit.event_type} · Rs {(audit.amount_paise or 0) / 100:.0f}",
            "status": _stage_status(True, current_stage == "detected"),
            "at": audit.created_at.isoformat() if audit.created_at else None,
        },
        {
            "key": "diagnose",
            "title": "Root cause diagnosed",
            "detail": f"{audit.error_reason or 'unknown'} → {audit.recommended_action or result.intended_action or '—'}",
            "status": _stage_status(True, False),
            "at": audit.created_at.isoformat() if audit.created_at else None,
        },
        {
            "key": "score",
            "title": f"Recovery score {recovery_intel.get('score', '—')}/100",
            "detail": recovery_intel.get("explanation") or recovery_intel.get("recommended_strategy", ""),
            "status": _stage_status(True, current_stage in {"stopped", "awaiting_payment"} and not recovered),
            "at": audit.created_at.isoformat() if audit.created_at else None,
        },
        {
            "key": "decide",
            "title": "Compliance decision",
            "detail": (
                f"Stopped: {result.stop_reason}"
                if stopped
                else (
                    "Delayed — no customer spam during outage"
                    if delayed
                    else (
                        "Watching — late auth, no nudge"
                        if watching
                        else "Recovery allowed within nudge limits"
                    )
                )
            ),
            "status": _stage_status(
                True,
                current_stage in {"stopped", "delayed", "watching"},
                blocked=stopped,
            ),
            "at": audit.created_at.isoformat() if audit.created_at else None,
        },
    ]

    if not stopped and not watching:
        exec_detail = (
            f"Channel {intervention.channel} · {intervention.action}"
            if intervention
            else ("Deferred — downtime window" if delayed else "Not executed")
        )
        if intervention and voice_eligible:
            exec_detail += " · Hinglish voice IVR (press 1 = pay now, 2 = pay later)"
        elif intervention and intervention.channel in {"sms", "email"}:
            exec_detail += " · one-way notify (no reply expected)"
        timeline.append(
            {
                "key": "execute",
                "title": "Recovery executed",
                "detail": exec_detail,
                "status": _stage_status(executed, current_stage == "awaiting_payment" and not has_promise),
                "at": intervention.created_at.isoformat() if intervention and intervention.created_at else None,
            }
        )

    # Promise capture only on voice path — SMS/email are outbound-only
    if voice_eligible and (executed or has_promise):
        timeline.append(
            {
                "key": "customer_reply",
                "title": "Voice IVR — customer intent",
                "detail": (
                    f'"{promise.raw_text}" → pay by {promise.promised_date.astimezone().strftime("%a %d %b %I:%M %p")}'
                    if promise
                    else 'Awaiting IVR reply — customer pressed 2 or said when they will pay'
                ),
                "status": _stage_status(
                    has_promise,
                    current_stage == "awaiting_payment" and executed and not has_promise,
                ),
                "at": promise.created_at.isoformat() if promise and promise.created_at else None,
            }
        )

    if voice_eligible and has_promise:
        sched = scheduled[0] if scheduled else None
        timeline.append(
            {
                "key": "scheduled",
                "title": "Reminder scheduled",
                "detail": (
                    f"Email reminder {sched.status} for {sched.run_at.astimezone().strftime('%a %d %b %I:%M %p')}"
                    if sched
                    else "No reminder queued"
                ),
                "status": _stage_status(
                    reminder_sent,
                    reminder_pending and current_stage == "waiting_promise_date",
                ),
                "at": sched.sent_at.isoformat() if sched and sched.sent_at else (sched.run_at.isoformat() if sched else None),
            }
        )

    timeline.append(
        {
            "key": "attribute",
            "title": "Revenue recovered",
            "detail": (
                f"Rs {(intervention.amount_recovered_paise or audit.amount_paise or 0) / 100:.0f} attributed"
                if recovered
                else "Waiting for successful payment"
            ),
            "status": _stage_status(recovered, current_stage == "awaiting_payment" and not has_promise),
            "at": intervention.recovered_at.isoformat() if intervention and intervention.recovered_at else None,
        }
    )

    razorpay_default = "Generic payment link + email for every failure"
    revrecover_action = result.intended_action or audit.recommended_action or "—"
    comparison = {
        "razorpay_alone": razorpay_default,
        "revrecover": (
            f"No nudge — {result.stop_reason}"
            if stopped
            else (
                "Wait for late auth — no spam"
                if watching
                else (
                    f"Defer until outage clears"
                    if delayed
                    else f"Playbook `{revrecover_action}` via {intervention.channel if intervention else '—'}"
                )
            )
        ),
    }

    can_record_promise = bool(
        voice_eligible
        and intervention
        and intervention.status in {"sent", "reused_link", "sent_no_link"}
        and not has_promise
        and current_stage not in {"recovered", "stopped", "delayed", "watching"}
    )

    return {
        "audit_id": audit.id,
        "intervention_id": intervention.id if intervention else None,
        "order_id": audit.order_id,
        "customer_email": audit.customer_email,
        "customer_contact": audit.customer_contact,
        "amount_rupees": (audit.amount_paise or 0) / 100,
        "error_reason": audit.error_reason,
        "channel": intervention.channel if intervention else None,
        "voice_eligible": voice_eligible,
        "notify_only": bool(intervention and not voice_eligible and executed),
        "current_stage": current_stage,
        "current_stage_label": current_stage.replace("_", " ").title(),
        "timeline": timeline,
        "pipeline": pipeline,
        "result": None,  # filled by router
        "comparison": comparison,
        "promise": (
            {
                "id": promise.id,
                "raw_text": promise.raw_text,
                "promised_date": promise.promised_date.isoformat(),
                "parsed_by": promise.parsed_by,
                "source_channel": promise.source_channel,
                "status": promise.status,
            }
            if promise
            else None
        ),
        "scheduled_actions": [
            {
                "id": s.id,
                "action_type": s.action_type,
                "run_at": s.run_at.isoformat(),
                "status": s.status,
                "result_note": s.result_note,
            }
            for s in scheduled
        ],
        "can_record_promise": can_record_promise,
        "recovery_score": recovery_intel,
    }


def get_case_stage(
    db: Session,
    audit: AuditEvent,
    intervention: Intervention | None = None,
) -> str:
    if intervention is None:
        intervention = (
            db.query(Intervention)
            .filter(Intervention.audit_event_id == audit.id)
            .order_by(Intervention.created_at.desc())
            .first()
        )
    promise = None
    scheduled: list[ScheduledAction] = []
    if intervention:
        promise = (
            db.query(PromiseToPay)
            .filter(PromiseToPay.intervention_id == intervention.id, PromiseToPay.status == "active")
            .first()
        )
        scheduled = (
            db.query(ScheduledAction)
            .filter(ScheduledAction.intervention_id == intervention.id)
            .all()
        )
    return compute_current_stage(
        audit=audit, intervention=intervention, promise=promise, scheduled=scheduled
    )
