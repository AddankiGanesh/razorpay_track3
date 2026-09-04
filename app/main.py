import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, get_settings
from app.database import get_db, init_db
from app.diagnosis.engine import diagnosis_engine
from app.checkout.router import router as checkout_router
from app.demo_pay import router as demo_pay_router
from app.lab.router import router as lab_router
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.services.metrics import get_batch_metrics, get_metrics_summary
from app.services.llm_client import llm_configured, llm_provider_name
from app.services.ml_recovery import ml_model_status, train_recovery_model
from app.services.learn_loop import refresh_learned_rates
from app.services.recovery_economics import get_intelligence_metrics, get_leak_funnel
from app.services.leakage_report import get_leak_tree, get_leakage_report
from app.services.counterfactual import simulate_strategies
from app.services.recovery_budget import allocate_recovery_budget
from app.services.reconciliation import reconcile_state
from app.webhooks.razorpay import router as webhooks_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RevRecover",
    description="AI Revenue Recovery Agent — Razorpay Buildathon Track 03",
    version="0.8.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router)
app.include_router(lab_router)
app.include_router(checkout_router)
app.include_router(demo_pay_router)

UI_PATH = PROJECT_ROOT / "app" / "ui" / "app.html"


def _load_ui() -> str:
    return UI_PATH.read_text(encoding="utf-8")


@app.on_event("startup")
def on_startup() -> None:
    import threading
    import time

    from app.database import SessionLocal
    from app.services.scheduler import process_due_actions

    init_db()
    settings = get_settings()

    logger.info(
        "RevRecover v0.8 booting. reasons=%s resend=%s llm=%s provider=%s ml_scoring=%s",
        len(diagnosis_engine.reason_catalog),
        bool(settings.resend_api_key),
        llm_configured(),
        llm_provider_name(),
        settings.ml_scoring_enabled,
    )

    def _warm_ml_and_learn() -> None:
        db = SessionLocal()
        try:
            learn = refresh_learned_rates(db)
            ml = train_recovery_model(db)
            logger.info(
                "Background ML ready: %s patterns | trained=%s samples=%s source=%s",
                learn.get("patterns_learned", 0),
                ml.get("trained"),
                ml.get("samples_total"),
                ml.get("training_source"),
            )
        except Exception as exc:
            logger.warning("Background ML warmup failed: %s", exc)
        finally:
            db.close()

    threading.Thread(target=_warm_ml_and_learn, daemon=True, name="ml-warmup").start()

    def _scheduler_loop() -> None:
        while True:
            time.sleep(45)
            db = SessionLocal()
            try:
                result = process_due_actions(db)
                if result.get("sent"):
                    logger.info("Scheduler sent %s reminder(s)", result["sent"])
            except Exception as exc:
                logger.warning("Scheduler error: %s", exc)
            finally:
                db.close()

    threading.Thread(target=_scheduler_loop, daemon=True, name="scheduler").start()


@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
@app.get("/demo", response_class=HTMLResponse)
def unified_ui() -> HTMLResponse:
    """Single page: metrics + scenarios + activity + APIs."""
    return HTMLResponse(
        content=_load_ui(),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/index.json")
def root_json() -> dict[str, str]:
    return {
        "service": "RevRecover",
        "status": "running",
        "ui": "/",
        "webhook": "/webhooks/razorpay",
        "health": "/health",
        "metrics": "/metrics/summary",
        "lab": "/lab",
        "dashboard": "/dashboard",
        "api_docs": "/docs",
        "api_list": "/api",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "service": "RevRecover",
        "status": "ok",
        "razorpay_key_configured": bool(settings.razorpay_key_id),
        "webhook_secret_configured": bool(settings.razorpay_webhook_secret),
        "resend_configured": bool(settings.resend_api_key),
        "twilio_configured": bool(settings.twilio_account_sid and settings.twilio_auth_token),
        "elevenlabs_configured": bool(settings.elevenlabs_api_key and settings.elevenlabs_agent_id),
        "openai_configured": bool(settings.openai_api_key),
        "gemini_configured": bool(settings.gemini_api_key),
        "grok_configured": bool(settings.grok_api_key or settings.xai_api_key),
        "groq_configured": bool(settings.groq_api_key),
        "llm_configured": llm_configured(),
        "llm_provider": llm_provider_name(),
        "ml_scoring_enabled": settings.ml_scoring_enabled,
        "ml_model": ml_model_status(),
        "auto_capture_enabled": settings.auto_capture_enabled,
        "reason_catalog_size": len(diagnosis_engine.reason_catalog),
    }


@app.get("/api")
def api_catalog() -> dict[str, Any]:
    return {
        "service": "RevRecover",
        "version": "0.5.0",
        "pages": {
            "ui": {"method": "GET", "path": "/", "description": "Unified demo UI (start here)"},
            "checkout": {"method": "GET", "path": "/checkout", "description": "Live Checkout.js fail→recover demo"},
            "demo_pay": {"method": "GET", "path": "/pay/{intervention_id}", "description": "Demo recovery page when Razorpay rate-limits links"},
            "dashboard": {"method": "GET", "path": "/dashboard", "description": "Classic metrics tables"},
            "lab": {"method": "GET", "path": "/lab", "description": "Legacy lab page"},
            "swagger": {"method": "GET", "path": "/docs", "description": "Interactive OpenAPI docs"},
        },
        "core": {
            "health": {"method": "GET", "path": "/health", "description": "Health check"},
            "metrics": {"method": "GET", "path": "/metrics/summary", "description": "At-risk, recovered, rate"},
            "batch_metrics": {"method": "GET", "path": "/metrics/batch", "description": "Recovery by category/action"},
            "audit_events": {"method": "GET", "path": "/audit/events?limit=50", "description": "Webhook audit trail"},
            "interventions": {"method": "GET", "path": "/interventions?limit=50", "description": "Recovery actions + links"},
        },
        "webhooks": {
            "razorpay": {
                "method": "POST",
                "path": "/webhooks/razorpay",
                "description": "Razorpay webhook receiver",
            },
        },
        "lab_api": {
            "scenarios": {"method": "GET", "path": "/lab/scenarios", "description": "List 14 test scenarios"},
            "fire_one": {"method": "POST", "path": "/lab/fire/{scenario_id}", "description": "Fire single scenario"},
            "fire_all": {"method": "POST", "path": "/lab/fire-all", "description": "Fire all scenarios"},
            "promise": {"method": "POST", "path": "/lab/promise", "description": "Record promise-to-pay (suppress nudges)"},
            "promises": {"method": "GET", "path": "/lab/promises", "description": "List promises"},
            "clear_promises": {"method": "DELETE", "path": "/lab/promises", "description": "Clear active promises (unblock nudges)"},
            "activity": {"method": "GET", "path": "/lab/activity", "description": "Activity feed + metrics"},
            "sync_razorpay": {"method": "POST", "path": "/lab/sync-razorpay", "description": "Poll Razorpay for paid payment links (localhost)"},
            "batch_metrics": {"method": "GET", "path": "/lab/batch-metrics", "description": "Recovery by category/action (batch bar)"},
            "retry_links": {
                "method": "POST",
                "path": "/lab/retry-failed-links?limit=5",
                "description": "Retry rate-limited payment links",
            },
            "reset": {
                "method": "POST",
                "path": "/lab/reset?confirm=true",
                "description": "Wipe audit + interventions for clean demo",
            },
        },
        "features": {
            "stopping_rules": "max 3 nudges / soft_nudge once / suppress after recovery",
            "voice_ivr": "Hinglish IVR script on halted revival (Twilio when configured)",
            "mandate_sequencer": "debit_declined → SMS/email/re-register (3 steps, then stop)",
            "promise_to_pay": "Hinglish/English promise parsing → suppress until date",
            "auto_capture": "payment.authorized → Razorpay capture API",
            "late_auth": "payment.pending → wait_and_poll, no customer spam",
            "downtime_delay": "bank/gateway tech errors → delay customer nudge",
            "email": "Resend when RESEND_API_KEY set; else log stub",
            "sms": "Twilio when TWILIO_* set; else log stub",
            "checkout_demo": "/checkout Checkout.js + create-order",
            "demo_pay": "/pay/{id} when Razorpay rate-limits links",
        },
    }


@app.get("/metrics/intelligence")
def metrics_intelligence(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_intelligence_metrics(db)


@app.get("/metrics/ml-status")
def metrics_ml_status() -> dict[str, Any]:
    return ml_model_status()


@app.get("/metrics/leakage")
def metrics_leakage(
    include_ai: bool = Query(default=False, description="Call Gemini for narrative (slower)"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_leakage_report(db, include_ai=include_ai)


@app.get("/metrics/leak-tree")
def metrics_leak_tree(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_leak_tree(db)


@app.get("/metrics/learn-loop")
def metrics_learn_loop(db: Session = Depends(get_db)) -> dict[str, Any]:
    return refresh_learned_rates(db)


@app.get("/metrics/counterfactual")
def metrics_counterfactual(db: Session = Depends(get_db)) -> dict[str, Any]:
    return simulate_strategies(db)


@app.get("/metrics/recovery-budget")
def metrics_recovery_budget(
    budget_rupees: float | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return allocate_recovery_budget(db, budget_rupees=budget_rupees)


@app.get("/metrics/reconcile")
def metrics_reconcile(db: Session = Depends(get_db)) -> dict[str, Any]:
    return reconcile_state(db)


@app.get("/metrics/leak-funnel")
def metrics_leak_funnel(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_leak_funnel(db)


@app.get("/metrics/summary")
def metrics_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_metrics_summary(db)


@app.get("/metrics/batch")
def metrics_batch(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Alias for batch recovery breakdown (same as /lab/batch-metrics)."""
    return get_batch_metrics(db)


@app.get("/audit/events")
def list_audit_events(limit: int = 50, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "events": [
            {
                "id": row.id,
                "event_type": row.event_type,
                "category": row.category,
                "payment_id": row.payment_id,
                "order_id": row.order_id,
                "error_reason": row.error_reason,
                "error_source": row.error_source,
                "diagnosis_path": row.diagnosis_path,
                "recommended_action": row.recommended_action,
                "amount_paise": row.amount_paise,
                "status": row.status,
                "customer_email": row.customer_email,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@app.get("/interventions")
def list_interventions(limit: int = 50, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = db.query(Intervention).order_by(Intervention.created_at.desc()).limit(limit).all()
    return {
        "count": len(rows),
        "interventions": [
            {
                "id": row.id,
                "audit_event_id": row.audit_event_id,
                "action": row.action,
                "channel": row.channel,
                "payment_link_url": row.payment_link_url,
                "amount_at_risk_paise": row.amount_at_risk_paise,
                "amount_recovered_paise": row.amount_recovered_paise,
                "status": row.status,
                "message": row.message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    }


@app.get("/dashboard")
def dashboard_redirect() -> RedirectResponse:
    return RedirectResponse(url="/?tab=log")


@app.get("/dashboard-legacy", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)) -> str:
    metrics = get_metrics_summary(db)
    events = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(15).all()
    interventions = db.query(Intervention).order_by(Intervention.created_at.desc()).limit(15).all()

    event_rows = "".join(
        f"<tr><td>{e.event_type}</td><td>{e.error_reason or '-'}</td>"
        f"<td>{e.recommended_action or '-'}</td><td>{(e.amount_paise or 0)/100:.0f}</td>"
        f"<td>{e.status}</td></tr>"
        for e in events
    )
    intervention_rows = "".join(
        f"<tr><td>{i.action}</td><td>{i.channel}</td>"
        f"<td>{(i.amount_at_risk_paise or 0)/100:.0f}</td>"
        f"<td>{(i.amount_recovered_paise or 0)/100:.0f}</td>"
        f"<td>{i.status}</td>"
        f"<td>{f'<a href=\"{i.payment_link_url}\" style=\"color:#38bdf8\" target=\"_blank\">Pay</a>' if i.payment_link_url else '-'}</td></tr>"
        for i in interventions
    )

    return f"""<!DOCTYPE html>
<html><head><title>RevRecover Dashboard</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 2rem; }}
.card {{ background: #1e293b; padding: 1.5rem; border-radius: 12px; }}
.card h3 {{ margin: 0; color: #94a3b8; font-size: 0.85rem; }}
.card p {{ margin: 0.5rem 0 0; font-size: 1.8rem; font-weight: bold; color: #38bdf8; }}
table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; }}
th, td {{ padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #334155; }}
th {{ background: #334155; color: #94a3b8; }}
h2 {{ margin-top: 2rem; }}
nav a {{ color: #38bdf8; margin-right: 1rem; }}
</style></head><body>
<nav><a href="/">Unified UI</a><a href="/lab">Lab</a><a href="/api">API list</a></nav>
<h1>RevRecover — Recovery Dashboard</h1>
<div class="cards">
  <div class="card"><h3>At Risk</h3><p>Rs {metrics['total_at_risk_rupees']}</p></div>
  <div class="card"><h3>Recovered</h3><p>Rs {metrics['total_recovered_rupees']}</p></div>
  <div class="card"><h3>Recovery Rate</h3><p>{metrics['recovery_rate_percent']}%</p></div>
  <div class="card"><h3>Interventions</h3><p>{metrics['interventions_sent']}</p></div>
</div>
<h2>Recent Events</h2>
<table><tr><th>Event</th><th>Reason</th><th>Action</th><th>Amount</th><th>Status</th></tr>{event_rows}</table>
<h2>Recent Interventions</h2>
<table><tr><th>Action</th><th>Channel</th><th>At Risk</th><th>Recovered</th><th>Status</th><th>Payment Link</th></tr>{intervention_rows}</table>
</body></html>"""
