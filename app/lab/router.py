from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import internal_webhook_url
from app.database import get_db
from app.execution.executor import retry_failed_links
from app.lab.pipeline import build_recovery_pipeline
from app.lab.replay import fire_result_from_audit
from app.lab.scenarios import FireResult, fire_all_scenarios, fire_scenario, scenario_catalog
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.models.promise import PromiseToPay, record_promise
from app.services.batch_seed import seed_batch_events, seed_training_batch
from app.services.counterfactual import simulate_strategies
from app.services.downtime import clear_outage, mark_outage
from app.services.voice import build_hinglish_ivr_script
from app.services.journey import build_customer_journey, compute_current_stage, get_case_stage
from app.services.leakage_report import get_leak_tree, get_leakage_report
from app.services.learn_loop import refresh_learned_rates
from app.services.mandate_sequencer import plan_for_intervention
from app.services.metrics import get_batch_metrics, get_metrics_summary, reset_demo_data
from app.services.payment_link_sync import sync_all_open_payment_links
from app.services.recovery_budget import allocate_recovery_budget
from app.services.recovery_economics import get_intelligence_metrics, clear_intelligence_cache, get_leak_funnel
from app.services.reconciliation import reconcile_state
from app.services.scheduler import process_due_actions
from app.models.escalation import EscalationCase, list_escalations

router = APIRouter(prefix="/lab", tags=["lab"])


class FireRequest(BaseModel):
    customer_email: str | None = None
    customer_contact: str | None = None


class FireAllRequest(FireRequest):
    simulate_recovery: bool = False
    recovery_count: int = Field(default=3, ge=1, le=8)


def _fire_result_dict(r: FireResult) -> dict[str, Any]:
    scenario = scenario_catalog.get(r.scenario_id) or {}
    pipeline = build_recovery_pipeline(r, scenario)
    return {
        "audit_id": r.audit_id,
        "scenario_id": r.scenario_id,
        "label": r.label,
        "group": r.group,
        "event": r.event,
        "order_id": r.order_id,
        "amount_rupees": r.amount_paise / 100,
        "recommended_action": r.recommended_action,
        "payment_link_url": r.razorpay_payment_link or r.payment_link_url,
        "razorpay_payment_link": r.razorpay_payment_link,
        "demo_pay_url": r.demo_pay_url,
        "intervention_id": r.intervention_id,
        "channel": r.channel,
        "message_preview": r.message_preview,
        "error_reason": r.error_reason,
        "diagnosis_path": r.diagnosis_path,
        "ok": r.ok,
        "error": r.error,
        "status": r.status,
        "delayed": r.delayed,
        "stopped": r.stopped,
        "mandate_plan": r.mandate_plan,
        "intended_action": r.intended_action,
        "stop_reason": r.stop_reason,
        "link_error": r.link_error,
        "pay_path_note": r.pay_path_note,
        "pipeline": pipeline,
    }


@router.get("/scenarios")
def list_scenarios() -> dict[str, Any]:
    return {
        "count": len(scenario_catalog.all_scenarios()),
        "scenarios": [
            {
                "id": s["id"],
                "label": s.get("label", s["id"]),
                "group": s["group"],
                "amount_rupees": s["amount"] / 100,
                "event": s.get("event") or "payment.failed",
                "reason": s.get("reason"),
            }
            for s in scenario_catalog.all_scenarios()
        ],
    }


@router.post("/fire/{scenario_id}")
def fire_one(scenario_id: str, request: Request, body: FireRequest | None = None) -> dict[str, Any]:
    body = body or FireRequest()
    try:
        result = fire_scenario(
            scenario_id,
            webhook_url=internal_webhook_url(str(request.base_url)),
            customer_email=body.customer_email,
            customer_contact=body.customer_contact,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": result.ok, "result": _fire_result_dict(result)}


@router.post("/fire-all")
def fire_all(request: Request, body: FireAllRequest | None = None) -> dict[str, Any]:
    body = body or FireAllRequest()
    results = fire_all_scenarios(
        webhook_url=internal_webhook_url(str(request.base_url)),
        simulate_recovery=body.simulate_recovery,
        recovery_count=body.recovery_count,
        customer_email=body.customer_email,
        customer_contact=body.customer_contact,
    )
    ok_count = sum(1 for r in results if r.ok)
    links_created = sum(1 for r in results if r.payment_link_url)
    return {
        "ok": ok_count == len(results),
        "fired": len(results),
        "succeeded": ok_count,
        "links_created": links_created,
        "simulate_recovery": body.simulate_recovery,
        "results": [_fire_result_dict(r) for r in results],
    }


class PromiseRequest(BaseModel):
    text: str = "Tuesday ko pay karunga"
    customer_email: str | None = None
    customer_contact: str | None = None
    audit_id: str | None = None
    intervention_id: str | None = None
    source_channel: str = "reply"  # sms | email | voice | whatsapp | reply


@router.post("/promise")
def create_promise(body: PromiseRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Record customer promise-to-pay for a specific case; schedules reminder email."""
    from app.config import get_settings

    settings = get_settings()
    email = body.customer_email or settings.demo_customer_email
    contact = body.customer_contact or settings.demo_customer_contact

    audit: AuditEvent | None = None
    intervention: Intervention | None = None
    if body.audit_id:
        audit = db.get(AuditEvent, body.audit_id)
    if body.intervention_id:
        intervention = db.get(Intervention, body.intervention_id)
    elif audit:
        intervention = (
            db.query(Intervention)
            .filter(Intervention.audit_event_id == audit.id)
            .order_by(Intervention.created_at.desc())
            .first()
        )

    if audit:
        email = audit.customer_email or email
        contact = audit.customer_contact or contact

    action = intervention.action if intervention else (audit.recommended_action if audit else "")
    amount_paise = (audit.amount_paise if audit else 0) or (intervention.amount_at_risk_paise if intervention else 0) or 0
    from app.services.voice import should_use_voice

    if not should_use_voice(amount_paise=amount_paise, action=action) and not (
        intervention and intervention.channel == "voice"
    ):
        raise HTTPException(
            status_code=400,
            detail="Promise-to-pay is only for voice IVR cases (halted subscription, high-value B2B). "
            "SMS/email are one-way — no customer reply captured.",
        )

    link_url = intervention.payment_link_url if intervention else None
    amount = (audit.amount_paise or intervention.amount_at_risk_paise or 0) / 100 if (audit or intervention) else 0

    promise, meta = record_promise(
        db,
        text=body.text,
        customer_email=email,
        customer_contact=contact,
        audit_event_id=audit.id if audit else body.audit_id,
        intervention_id=intervention.id if intervention else body.intervention_id,
        source_channel=body.source_channel or "voice",
        payment_link_url=link_url,
        amount_rupees=amount or None,
    )
    journey = build_customer_journey(db, audit, intervention) if audit else None
    return {
        "ok": True,
        "promise_id": promise.id,
        "promised_date": promise.promised_date.isoformat(),
        "raw_text": promise.raw_text,
        "parsed_by": promise.parsed_by,
        "confidence": meta.get("confidence"),
        "scheduled_at": meta.get("scheduled_at"),
        "status": promise.status,
        "note": "Nudges suppressed until promised_date; reminder email scheduled",
        "journey": journey,
    }


@router.delete("/promises")
def clear_promises(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Clear active promises so nudges are no longer suppressed (demo helper)."""
    count = db.query(PromiseToPay).filter(PromiseToPay.status == "active").update({"status": "cleared"})
    db.commit()
    return {"ok": True, "cleared": count, "note": "Active promises cleared — fire scenarios again"}


@router.get("/promises")
def list_promises(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.query(PromiseToPay).order_by(PromiseToPay.created_at.desc()).limit(20).all()
    return {
        "count": len(rows),
        "promises": [
            {
                "id": r.id,
                "customer_email": r.customer_email,
                "promised_date": r.promised_date.isoformat() if r.promised_date else None,
                "raw_text": r.raw_text,
                "status": r.status,
            }
            for r in rows
        ],
    }


@router.post("/sync-razorpay")
def sync_razorpay(limit: int = Query(default=50, le=100), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Poll Razorpay API for paid payment links (works on localhost without webhooks)."""
    result = sync_all_open_payment_links(db, limit=limit)
    return {
        "ok": True,
        **result,
        "metrics": get_metrics_summary(db),
    }


@router.post("/retry-failed-links")
def retry_links(limit: int = Query(default=5, le=20), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Retry payment-link creation for interventions without a Razorpay URL."""
    results = retry_failed_links(db, limit=limit)
    ok = sum(1 for r in results if r["ok"])
    return {"retried": len(results), "links_restored": ok, "results": results}


@router.post("/reset")
def reset_lab(confirm: bool = Query(default=False), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Wipe audit + intervention tables for a clean demo. Requires confirm=true."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass confirm=true to reset demo data")
    deleted = reset_demo_data(db)
    clear_outage("bank")
    clear_outage("gateway")
    clear_intelligence_cache()
    from app.services.customer_context import clear_customer_cache

    clear_customer_cache()
    return {"ok": True, **deleted, "metrics": get_metrics_summary(db), "outages_cleared": True}


@router.post("/outage/{source}")
def set_outage(source: str, hours: float = Query(default=4.0, ge=0.1, le=48)) -> dict[str, Any]:
    """Demo helper: mark bank/gateway downtime so nudges delay."""
    if source not in {"bank", "gateway"}:
        raise HTTPException(status_code=400, detail="source must be bank or gateway")
    mark_outage(source, hours=hours)
    return {"ok": True, "source": source, "hours": hours}


@router.delete("/outage/{source}")
def unset_outage(source: str) -> dict[str, Any]:
    clear_outage(source)
    return {"ok": True, "source": source, "cleared": True}


@router.get("/batch-metrics")
def batch_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Recovery breakdown by category/action for judge batch demo."""
    return get_batch_metrics(db)


@router.get("/intelligence")
def intelligence_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """ERR + recovery plan buckets."""
    return get_intelligence_metrics(db)


@router.get("/leak-funnel")
def leak_funnel(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Revenue leak funnel for dashboard visualization."""
    return get_leak_funnel(db)


@router.get("/leakage-report")
def leakage_report(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Revenue leakage by reason, payment method, and hour-of-day (IST)."""
    return get_leakage_report(db)


@router.get("/leak-tree")
def leak_tree(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Hierarchical leak graph (tree) for dashboard."""
    return get_leak_tree(db)


@router.get("/learn-loop")
def learn_loop(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Historical outcome learning — adjusts recovery scores."""
    return refresh_learned_rates(db)


@router.get("/counterfactual")
def counterfactual(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Baseline vs smart strategy simulator."""
    return simulate_strategies(db)


@router.get("/recovery-budget")
def recovery_budget(
    budget_rupees: float | None = Query(default=None, ge=1000, le=500_000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Allocate recovery spend under budget cap (default ₹50k)."""
    return allocate_recovery_budget(db, budget_rupees=budget_rupees)


@router.get("/escalations")
def escalations(limit: int = Query(default=20, le=50), db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = list_escalations(db, limit=limit)
    queue: list[dict[str, Any]] = []
    for r in rows:
        audit = db.get(AuditEvent, r.audit_event_id) if r.audit_event_id else None
        queue.append(
            {
                "id": r.id,
                "audit_event_id": r.audit_event_id,
                "intervention_id": r.intervention_id,
                "customer_email": r.customer_email,
                "amount_rupees": (r.amount_paise or 0) / 100,
                "recovery_score": r.recovery_score,
                "reason": r.reason or (audit.error_reason if audit else None),
                "event_type": audit.event_type if audit else None,
                "status": r.status,
                "note": r.note,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    db.commit()
    return {"count": len(queue), "queue": queue}


@router.post("/escalations/{case_id}/resolve")
def resolve_escalation(case_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(EscalationCase, case_id)
    if not row:
        raise HTTPException(status_code=404, detail="Escalation not found")
    row.status = "resolved"
    db.commit()
    return {"ok": True, "id": case_id, "status": "resolved"}


@router.get("/reconcile")
def lab_reconcile(db: Session = Depends(get_db)) -> dict[str, Any]:
    return reconcile_state(db)


@router.post("/seed-training-batch")
def seed_training(
    count: int = Query(default=2000, ge=100, le=2000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Seed 2000 events with reason-weighted recoveries — primary ML training pipeline."""
    result = seed_training_batch(db, count=count)
    clear_intelligence_cache()
    result["intelligence"] = get_intelligence_metrics(db, use_cache=False)
    result["leakage"] = get_leakage_report(db)
    return {"ok": True, **result}


@router.post("/seed-batch")
def seed_batch(
    count: int = Query(default=200, ge=10, le=2000),
    training: bool = Query(default=False, description="Use ML training mode (reason-weighted recoveries)"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Seed synthetic revenue-loss events for ERR / funnel demo (or ML training if training=true)."""
    if training or count >= 1000:
        result = seed_training_batch(db, count=count)
    else:
        result = seed_batch_events(db, count=count)
    clear_intelligence_cache()
    result["intelligence"] = get_intelligence_metrics(db, use_cache=False)
    result["leakage"] = get_leakage_report(db)
    return {"ok": True, **result}


def _activity_display_label(e: AuditEvent) -> str:
    reason = e.error_reason or e.event_type or "case"
    labels = {
        "checkout_abandoned": "Checkout abandoned (drop-off)",
        "incorrect_otp": "Wrong OTP",
        "otp_expired": "OTP expired",
        "insufficient_funds": "Low balance",
        "payment_cancelled": "Customer cancelled",
        "bank_technical_error": "Bank downtime",
        "gateway_technical_error": "Gateway error",
        "subscription_halted": "Subscription halted",
        "debit_declined": "Mandate debit declined",
        "b2b_expired": "B2B link expired",
    }
    return labels.get(reason, reason.replace("_", " "))


def _playbook_hint(e: AuditEvent, iv: Intervention | None, stage: str) -> str | None:
    action = (e.recommended_action or (iv.action if iv else "") or "").split(":")[0]
    if stage == "recovered":
        return "Payment completed — this row updated, no separate paid log"
    if stage == "watching" or "wait_and_poll" in action:
        return "WATCHING — no customer nudge; polls for late auth (payment not auto-executed)"
    if stage == "delayed":
        return "DELAYED — outage window; nudge after bank/gateway recovers"
    if stage == "stopped":
        return "STOPPED — compliance cap; no more messages"
    if stage == "awaiting_payment":
        return "Pay link sent — customer pays manually; click Refresh after payment"
    return None


@router.get("/activity")
def activity(
    limit: int = Query(default=30, le=100),
    sync: bool = Query(default=False, description="Poll Razorpay for paid payment links before listing"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    process_due_actions(db)
    razorpay_sync = sync_all_open_payment_links(db) if sync else None

    # Only show recovery cases (failures) — success webhooks update the original row, not new list entries
    RISK_EVENT_TYPES = frozenset(
        {
            "payment.failed",
            "payment.pending",
            "subscription.pending",
            "subscription.halted",
            "payment_link.expired",
        }
    )
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type.in_(list(RISK_EVENT_TYPES)))
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    interventions = db.query(Intervention).order_by(Intervention.created_at.desc()).limit(limit * 2).all()
    intervention_by_audit = {i.audit_event_id: i for i in interventions}

    recovered_by_order: dict[str, Intervention] = {}
    for i in interventions:
        if i.status != "recovered":
            continue
        audit = db.get(AuditEvent, i.audit_event_id)
        if audit and audit.order_id:
            recovered_by_order[audit.order_id] = i

    feed: list[dict[str, Any]] = []
    for e in events:
        iv = intervention_by_audit.get(e.id)
        attributed = recovered_by_order.get(e.order_id) if e.order_id else None
        preview: str | None = None

        if iv and iv.status == "recovered":
            link_url = iv.payment_link_url
            action = "recovery_attributed"
            channel = iv.channel
            link_note = "Payment completed · revenue attributed"
        elif e.event_type in {"order.paid", "payment.captured", "payment_link.paid"}:
            link_url = attributed.payment_link_url if attributed else None
            action = "recovery_attributed" if attributed else e.recommended_action
            channel = attributed.channel if attributed else None
            link_note = "Recovered" if attributed else "No matching intervention"
        elif e.status == "watching_late_auth" or (iv and iv.status == "watching"):
            link_url = None
            action = e.recommended_action or (iv.action if iv else None)
            channel = "system"
            link_note = "Watching (late auth — no nudge)"
        elif e.status == "delayed_for_downtime":
            link_url = None
            action = e.recommended_action
            channel = "system"
            preview = (iv.message or "")[:120] if iv else None
            link_note = "Delayed (bank/gateway downtime)"
            if preview:
                link_note += " — see outage panel"
        elif e.status == "skipped_stopping_rule":
            link_url = None
            action = e.recommended_action
            channel = None
            link_note = "Stopped (compliance rule)"
        elif e.status == "skipped":
            link_url = None
            action = e.recommended_action
            channel = "system"
            link_note = "Skipped (no customer nudge)"
        elif iv:
            link_url = iv.payment_link_url
            action = e.recommended_action or iv.action
            channel = iv.channel
            link_note = None
            if iv.action == "mandate_retry_sequence":
                plan = plan_for_intervention(db, iv, e)
                if plan:
                    step = plan["current"]["step"]
                    link_note = f"Mandate step {step}/{plan['total_steps']} ({plan['current']['channel']})"
            if link_url and not link_note:
                link_note = "Pay link" if iv.status != "reused_link" else "Reused link"
            elif iv.status == "sent_no_link" and not link_note:
                link_url = f"/pay/{iv.id}"
                link_note = "Demo pay (no Razorpay link)"
            elif iv.status == "delayed" and not link_note:
                link_note = "Delayed (bank/gateway downtime)"
            elif not link_note:
                link_note = iv.status
        else:
            link_url = None
            action = e.recommended_action
            channel = None
            link_note = None

        stage = get_case_stage(db, e, iv)
        feed.append(
            {
                "audit_id": e.id,
                "intervention_id": iv.id if iv else None,
                "at": e.created_at.isoformat() if e.created_at else None,
                "type": "event",
                "event_type": e.event_type,
                "reason": e.error_reason,
                "display_label": _activity_display_label(e),
                "action": action,
                "amount_rupees": (e.amount_paise or 0) / 100,
                "status": e.status,
                "current_stage": stage,
                "playbook_hint": _playbook_hint(e, iv, stage),
                "recovery_score": e.recovery_score,
                "order_id": e.order_id,
                "channel": channel,
                "payment_link_url": link_url,
                "link_note": link_note,
                "message_preview": preview or ((iv.message or "")[:160] if iv else None),
                "source": "webhook",
            }
        )

    metrics = get_metrics_summary(db)
    return {
        "count": len(feed),
        "activity": feed,
        "metrics": metrics,
        "razorpay_sync": razorpay_sync,
        "help": {
            "events": "Every detected failure (payment.failed, subscription, etc.) — may not all get a pay link.",
            "pay_path": "Razorpay Pay link OR Demo pay (/pay/{id}) — both count as recoverable paths.",
            "stopped": "Compliance rule blocked Execute — no link by design (see Decide step in pipeline).",
            "delayed": "Bank/gateway downtime — customer nudge deferred; check Active outage panel on home.",
            "recovered": "Increases on order.paid webhook or Demo pay → Simulate successful recovery.",
            "reconciliation": "Events ≈ Pay path + Stopped + Delayed (+ late-auth watch rows).",
            "real_pay_links": (
                "After paying on a Razorpay Pay link, click Sync from Razorpay — we poll the API "
                "(no ngrok needed for successful payments). Failed attempts on the link page need webhooks."
            ),
            "replay": "Click any Activity row to replay its Detect→Attribute pipeline at the top.",
        },
    }


@router.get("/journey/{audit_id}")
def get_journey(audit_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Full customer recovery journey for any scenario — timeline + current stage."""
    process_due_actions(db)
    audit = db.get(AuditEvent, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit event not found")

    # Success webhook rows are internal — show journey on the original failure case
    if audit.event_type in {"order.paid", "payment.captured", "payment_link.paid"}:
        if audit.order_id:
            parent_audit = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.order_id == audit.order_id,
                    AuditEvent.event_type.in_(
                        [
                            "payment.failed",
                            "payment.pending",
                            "subscription.pending",
                            "subscription.halted",
                            "payment_link.expired",
                        ]
                    ),
                )
                .order_by(AuditEvent.created_at.desc())
                .first()
            )
            if parent_audit:
                audit = parent_audit
                audit_id = parent_audit.id
        elif audit.payment_id:
            parent_iv = (
                db.query(Intervention)
                .filter(Intervention.recovered_payment_id == audit.payment_id)
                .order_by(Intervention.recovered_at.desc())
                .first()
            )
            if parent_iv:
                audit = db.get(AuditEvent, parent_iv.audit_event_id) or audit
                audit_id = audit.id

    intervention = (
        db.query(Intervention)
        .filter(Intervention.audit_event_id == audit_id)
        .order_by(Intervention.created_at.desc())
        .first()
    )
    journey = build_customer_journey(db, audit, intervention)
    result = fire_result_from_audit(db, audit, intervention)
    journey["result"] = _fire_result_dict(result)
    journey["pipeline"] = build_recovery_pipeline(result)
    if (
        journey.get("voice_eligible")
        or result.intended_action == "halted_revival_job"
        or audit.event_type == "subscription.halted"
    ):
        link = result.razorpay_payment_link or result.demo_pay_url
        journey["hinglish_script"] = build_hinglish_ivr_script(
            amount_rupees=(audit.amount_paise or 0) / 100,
            payment_link_url=link,
            customer_name=(audit.customer_email or "Customer").split("@")[0],
        )
        if result.intended_action == "halted_revival_job" or audit.event_type == "subscription.halted":
            journey["voice_eligible"] = True
    return journey


@router.get("/event/{audit_id}")
def replay_event(audit_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Rebuild pipeline UI for any stored audit event (lab fire or real Razorpay webhook)."""
    process_due_actions(db)
    audit = db.get(AuditEvent, audit_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit event not found")

    intervention = (
        db.query(Intervention)
        .filter(Intervention.audit_event_id == audit_id)
        .order_by(Intervention.created_at.desc())
        .first()
    )
    result = fire_result_from_audit(db, audit, intervention)
    pipeline = build_recovery_pipeline(result)
    journey = build_customer_journey(db, audit, intervention)
    return {
        "audit_id": audit_id,
        "intervention_id": intervention.id if intervention else None,
        "result": _fire_result_dict(result),
        "pipeline": pipeline,
        "journey": journey,
        "raw_payload": audit.raw_payload,
    }


LAB_HTML = """<!DOCTYPE html>
<html><head>
<title>RevRecover Lab</title>
<meta charset="utf-8"/>
<style>
:root { --bg:#0f172a; --card:#1e293b; --border:#334155; --muted:#94a3b8; --accent:#38bdf8; --ok:#4ade80; --warn:#fbbf24; }
* { box-sizing:border-box; }
body { font-family:system-ui,sans-serif; margin:0; background:var(--bg); color:#e2e8f0; }
header { padding:1.25rem 2rem; border-bottom:1px solid var(--border); display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:1rem; }
header h1 { margin:0; font-size:1.4rem; }
nav a { color:var(--accent); margin-left:1rem; text-decoration:none; }
main { padding:1.5rem 2rem; display:grid; grid-template-columns:340px 1fr; gap:1.5rem; }
@media(max-width:960px){ main { grid-template-columns:1fr; } }
.panel { background:var(--card); border-radius:12px; padding:1rem; border:1px solid var(--border); }
.panel h2 { margin:0 0 1rem; font-size:1rem; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:.75rem; margin-bottom:1.5rem; }
.metric { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1rem; }
.metric small { color:var(--muted); display:block; }
.metric strong { font-size:1.4rem; color:var(--accent); }
.scenario { border:1px solid var(--border); border-radius:8px; padding:.75rem; margin-bottom:.5rem; display:flex; justify-content:space-between; align-items:center; gap:.5rem; }
.scenario small { color:var(--muted); display:block; }
button { background:var(--accent); color:#0f172a; border:none; border-radius:8px; padding:.45rem .8rem; font-weight:600; cursor:pointer; }
button.secondary { background:#475569; color:#fff; }
button:disabled { opacity:.5; cursor:not-allowed; }
.actions { display:flex; gap:.5rem; flex-wrap:wrap; margin-bottom:1rem; }
input { width:100%; padding:.5rem; border-radius:6px; border:1px solid var(--border); background:#0f172a; color:#e2e8f0; margin-bottom:.5rem; }
label { font-size:.85rem; color:var(--muted); display:block; margin-bottom:.25rem; }
table { width:100%; border-collapse:collapse; font-size:.85rem; }
th,td { padding:.6rem .5rem; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
th { color:var(--muted); }
.tag { display:inline-block; padding:.15rem .45rem; border-radius:4px; font-size:.75rem; background:#334155; }
.tag.ok { background:#14532d; color:var(--ok); }
.tag.fail { background:#7f1d1d; color:#fca5a5; }
a.link { color:var(--accent); }
#log { max-height:420px; overflow:auto; }
.toast { position:fixed; bottom:1rem; right:1rem; background:#334155; padding:.75rem 1rem; border-radius:8px; display:none; }
</style></head><body>
<header>
  <h1>RevRecover Lab</h1>
  <nav>
    <a href="/">Unified UI</a>
    <a href="/dashboard">Dashboard</a>
    <a href="/checkout">Checkout</a>
    <a href="/audit/events">Audit API</a>
    <a href="/interventions">Interventions API</a>
  </nav>
</header>
<div style="padding:0 2rem 1rem">
  <div class="metrics" id="metrics"></div>
</div>
<main>
  <div>
    <div class="panel">
      <h2>Fire scenarios</h2>
      <label>Customer email (for payment link notify)</label>
      <input id="email" placeholder="you@gmail.com"/>
      <div class="actions">
        <button onclick="fireAll(false)">Fire all 11 scenarios</button>
        <button class="secondary" onclick="fireAll(true)">Fire all + simulate 3 recoveries</button>
      </div>
      <div id="scenarios"></div>
    </div>
  </div>
  <div class="panel">
    <h2>Activity log</h2>
    <p style="color:var(--muted);font-size:.85rem;margin-top:0">
      <strong>At Risk</strong> rises on every fired scenario.
      <strong>Recovered</strong> rises only after <code>order.paid</code>.
      For the <b>live pipeline</b> view, open <a class="link" href="/">Unified UI</a> → <b>Activity</b> tab → click any row.
    </p>
    <div id="log"><table>
      <tr><th>Time</th><th>Event</th><th>Reason</th><th>Action</th><th>Channel</th><th>Amount</th><th>Link / Status</th></tr>
      <tbody id="activity-body"></tbody>
    </table></div>
  </div>
</main>
<div class="toast" id="toast"></div>
<script>
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3500);
}
async function loadMetrics() {
  const r = await fetch('/lab/activity?limit=1');
  const d = await r.json();
  const m = d.metrics;
  document.getElementById('metrics').innerHTML = `
    <div class="metric"><small>At Risk</small><strong>Rs ${m.total_at_risk_rupees}</strong></div>
    <div class="metric"><small>Recovered</small><strong>Rs ${m.total_recovered_rupees}</strong></div>
    <div class="metric"><small>Recovery Rate</small><strong>${m.recovery_rate_percent}%</strong></div>
    <div class="metric"><small>Interventions</small><strong>${m.interventions_sent}</strong></div>`;
}
async function loadScenarios() {
  const r = await fetch('/lab/scenarios');
  const d = await r.json();
  document.getElementById('scenarios').innerHTML = d.scenarios.map(s => `
    <div class="scenario">
      <div><strong>${s.label}</strong><small>${s.group} · Rs ${s.amount_rupees} · ${s.event}</small></div>
      <button onclick="fireOne('${s.id}')">Fire</button>
    </div>`).join('');
}
async function loadActivity() {
  const r = await fetch('/lab/activity?limit=25');
  const d = await r.json();
  document.getElementById('activity-body').innerHTML = d.activity.map(a => {
    let linkCell = '-';
    if (a.payment_link_url) {
      linkCell = `<a class="link" href="${a.payment_link_url}" target="_blank">Pay</a>`;
    } else if (a.link_note) {
      linkCell = `<span class="tag ${a.link_note.includes('failed') || a.link_note.includes('rate') ? 'fail' : 'ok'}">${a.link_note}</span>`;
    }
    return `<tr>
      <td>${(a.at||'').slice(11,19)}</td>
      <td>${a.event_type}</td>
      <td>${a.reason || '-'}</td>
      <td><span class="tag">${a.action || '-'}</span></td>
      <td>${a.channel || '-'}</td>
      <td>Rs ${a.amount_rupees}</td>
      <td>${linkCell}</td>
    </tr>`;
  }).join('');
  if (d.metrics) {
    const m = d.metrics;
    document.getElementById('metrics').innerHTML = `
      <div class="metric"><small>At Risk</small><strong>Rs ${m.total_at_risk_rupees}</strong></div>
      <div class="metric"><small>Recovered</small><strong>Rs ${m.total_recovered_rupees}</strong></div>
      <div class="metric"><small>Recovery Rate</small><strong>${m.recovery_rate_percent}%</strong></div>
      <div class="metric"><small>Interventions</small><strong>${m.interventions_sent}</strong></div>`;
  }
}
function emailBody() {
  const email = document.getElementById('email').value.trim();
  return email ? { customer_email: email, customer_contact: '+919876543210' } : {};
}
async function fireOne(id) {
  toast('Firing ' + id + '...');
  const r = await fetch('/lab/fire/' + id, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(emailBody()) });
  const d = await r.json();
  if (!r.ok) { toast('Error: ' + (d.detail || 'failed')); return; }
  toast('Fired: ' + d.result.recommended_action + (d.result.payment_link_url ? ' — link created' : ' — use Demo pay'));
  loadActivity();
}
async function fireAll(sim) {
  toast(sim ? 'Firing all + recoveries...' : 'Firing all 11 scenarios...');
  const body = { ...emailBody(), simulate_recovery: sim, recovery_count: 3 };
  const r = await fetch('/lab/fire-all', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const d = await r.json();
  const links = (d.results || []).filter(r => r.payment_link_url).length;
  toast('Done: ' + d.succeeded + '/' + d.fired + ' · links: ' + links + (sim ? ' · +3 simulated recoveries' : ''));
  loadActivity();
}
loadScenarios(); loadActivity();
setInterval(loadActivity, 8000);
</script>
</body></html>"""


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def lab_page() -> str:
    """Legacy lab URL — redirect handled by meta refresh; unified UI is at /."""
    return (
        '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=/?tab=lab"/>'
        '<script>location.replace("/?tab=lab")</script></head>'
        '<body><a href="/?tab=lab">Open RevRecover</a></body></html>'
    )
