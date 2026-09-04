"""Local demo recovery page when Razorpay payment-link API cannot create a new link."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings, internal_webhook_url
from app.database import get_db
from app.execution.executor import refresh_intervention_link
from app.models.audit import AuditEvent
from app.models.intervention import Intervention
from app.services.link_pool import link_error_label
from app.services.payment_link_sync import sync_payment_link_by_id

router = APIRouter(tags=["demo-pay"])


@router.get("/razorpay/return")
def razorpay_return(
    razorpay_payment_link_id: str | None = Query(default=None),
    payment_link_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Razorpay redirects here after payment-link checkout — sync status without webhooks."""
    plink = razorpay_payment_link_id or payment_link_id
    if plink:
        sync_payment_link_by_id(db, plink)
    return RedirectResponse(url="/?tab=log&synced=1")


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _fallback_notice(link_error: str | None) -> str:
    label = link_error_label(link_error, reused=False)
    return (
        f'<p style="color:#fbbf24">{label}. '
        "No matching unpaid Razorpay link for this amount — use "
        "<b>Simulate successful recovery</b> to complete the demo pipeline.</p>"
    )


@router.get("/pay/{intervention_id}", response_class=HTMLResponse)
def demo_pay_page(intervention_id: str, db: Session = Depends(get_db)) -> str:
    iv = db.get(Intervention, intervention_id)
    if not iv:
        raise HTTPException(status_code=404, detail="Intervention not found")

    if not iv.payment_link_url and iv.status in {"sent_no_link", "sent", "reused_link"}:
        refresh_intervention_link(db, iv)
        db.refresh(iv)

    amount = (iv.amount_at_risk_paise or 0) / 100
    link = iv.payment_link_url
    status = iv.status
    msg = (iv.message or "").replace("<", "&lt;")
    if link:
        real_pay = (
            f'<p><a href="{link}" style="background:#38bdf8;color:#0b1220;padding:12px 18px;'
            f'border-radius:8px;text-decoration:none;font-weight:700">Pay on Razorpay</a></p>'
            f'<p class="muted">Test card 5267 3181 8797 5449 · OTP 1234</p>'
        )
    else:
        real_pay = _fallback_notice(iv.link_error)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>RevRecover — Complete payment</title>
<style>
body{{font-family:system-ui;background:#0b1220;color:#e2e8f0;display:flex;justify-content:center;padding:2rem}}
.box{{max-width:480px;background:#1e293b;border:1px solid #334155;border-radius:14px;padding:1.5rem}}
button{{width:100%;padding:.75rem;border:none;border-radius:10px;background:#4ade80;color:#052e16;font-weight:700;cursor:pointer;margin-top:.75rem}}
.muted{{color:#94a3b8;font-size:.9rem;white-space:pre-wrap}}
a{{color:#38bdf8}}
</style></head><body>
<div class="box">
  <h1>Recovery payment</h1>
  <p class="muted">Action: <b>{iv.action}</b> · Channel: {iv.channel} · Status: {status}</p>
  <p style="font-size:1.6rem;margin:.5rem 0">Rs {amount:.0f}</p>
  <p class="muted">{msg}</p>
  {real_pay}
  <button onclick="demoPay()">Simulate successful recovery (demo)</button>
  <p class="muted" id="out"></p>
  <p><a href="/">Back to RevRecover</a></p>
</div>
<script>
async function demoPay() {{
  const r = await fetch('/pay/{intervention_id}/simulate', {{ method:'POST' }});
  const d = await r.json();
  document.getElementById('out').textContent = r.ok && d.ok
    ? ('Recovered Rs ' + d.amount_rupees + ' — opening dashboard...')
    : ('Failed: ' + (d.detail || d.error || JSON.stringify(d)));
  if (r.ok && d.ok) setTimeout(() => location.href='/', 1200);
}}
</script>
</body></html>"""


@router.post("/pay/{intervention_id}/simulate")
def simulate_recovery(intervention_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Fire a signed order.paid webhook so attribution + recovered metrics update."""
    iv = db.get(Intervention, intervention_id)
    if not iv:
        raise HTTPException(status_code=404, detail="Intervention not found")
    if iv.status == "recovered":
        return {"ok": True, "amount_rupees": (iv.amount_recovered_paise or 0) / 100, "already": True}

    audit = db.get(AuditEvent, iv.audit_event_id)
    if not audit:
        raise HTTPException(status_code=404, detail="Audit event missing")

    amount = iv.amount_at_risk_paise or audit.amount_paise or 0
    order_id = audit.order_id or f"order_demo_{uuid.uuid4().hex[:10]}"
    payment_id = f"pay_demo_{uuid.uuid4().hex[:10]}"

    if not audit.order_id:
        audit.order_id = order_id
        db.commit()

    settings = get_settings()
    payload = {
        "event": "order.paid",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "status": "captured",
                    "email": audit.customer_email,
                    "contact": audit.customer_contact,
                }
            },
            "order": {"entity": {"id": order_id, "amount": amount, "currency": "INR", "status": "paid"}},
        },
    }
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if settings.razorpay_webhook_secret:
        headers["X-Razorpay-Signature"] = _sign(body, settings.razorpay_webhook_secret)

    url = internal_webhook_url()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, content=body, headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=resp.text[:500])

    db.refresh(iv)
    return {
        "ok": True,
        "amount_rupees": amount / 100,
        "intervention_status": iv.status,
        "webhook": resp.json(),
    }
