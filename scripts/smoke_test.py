"""Smoke test RevRecover after UI restore."""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001"
BODY = json.dumps({"customer_email": "ganeshsuraj29@gmail.com"}).encode()


def get(path: str) -> tuple[int, dict | str]:
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=30) as r:
        ct = r.headers.get("content-type", "")
        data = r.read()
        if "json" in ct:
            return r.status, json.loads(data)
        return r.status, data.decode("utf-8", errors="replace")


def post(path: str, body: bytes | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body or b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read())


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    fails = 0
    print(f"\n=== RevRecover smoke test @ {BASE} ===\n")

    # --- Pages ---
    print("Pages")
    for path, needle in [
        ("/", "loadCharts"),
        ("/", "loadIntelligencePanels"),
        ("/", "fireOne("),
        ("/", "seedBatch"),
        ("/", "hero-kpi"),
        ("/checkout", "checkout.js"),
        ("/dashboard", "RevRecover"),
        ("/lab", "scenario"),
        ("/docs", "swagger"),
    ]:
        try:
            status, html = get(path)
            ok = status == 200 and (needle.lower() in html.lower())
            if not check(f"GET {path} contains '{needle}'", ok, f"status={status}"):
                fails += 1
        except Exception as e:
            if not check(f"GET {path}", False, str(e)):
                fails += 1

    # --- Health ---
    print("\nCore APIs")
    try:
        status, h = get("/health")
        ok = status == 200 and h.get("status") == "ok" and h.get("reason_catalog_size", 0) >= 100
        if not check("GET /health", ok, f"reasons={h.get('reason_catalog_size')} llm={h.get('llm_provider')}"): fails += 1
    except Exception as e:
        if not check("GET /health", False, str(e)): fails += 1

    for path in [
        "/metrics/summary",
        "/metrics/batch",
        "/metrics/intelligence",
        "/metrics/leak-funnel",
        "/metrics/leakage?include_ai=false",
        "/metrics/counterfactual",
        "/metrics/recovery-budget",
        "/lab/scenarios",
        "/lab/activity?limit=5",
        "/lab/batch-metrics",
    ]:
        try:
            status, data = get(path)
            if not check(f"GET {path}", status == 200, f"keys={list(data.keys())[:5] if isinstance(data, dict) else 'html'}"):
                fails += 1
        except Exception as e:
            if not check(f"GET {path}", False, str(e)): fails += 1

    # --- Reset + scenarios ---
    print("\nLab flows")
    try:
        post("/lab/reset?confirm=true")
        check("POST /lab/reset?confirm=true", True)
    except Exception as e:
        if not check("POST /lab/reset", False, str(e)): fails += 1
        return 1

    scenarios = [
        ("incorrect_otp", "CHASE", ["retry", "payment_link", "regenerate"]),
        ("payment_cancelled", "soft", ["soft", "nudge", "stop"]),
        ("bank_technical_error", "delay", ["delay", "downtime", "watch"]),
    ]
    for sid, label, hints in scenarios:
        try:
            status, data = post(f"/lab/fire/{sid}", BODY)
            res = data.get("result", data)
            action = str(res.get("recommended_action", "")).lower()
            status_s = str(res.get("status", "")).lower()
            delayed = res.get("delayed", False)
            stopped = res.get("stopped", False)
            ok = res.get("ok", True) is not False
            matched = any(h in action or h in status_s for h in hints) or delayed or stopped
            detail = f"action={res.get('recommended_action')} delayed={delayed} stopped={stopped}"
            if not check(f"Fire {sid} ({label})", ok and matched, detail):
                fails += 1
        except Exception as e:
            if not check(f"Fire {sid}", False, str(e)): fails += 1

    # --- Seed batch ---
    try:
        status, data = post("/lab/seed-batch", json.dumps({"count": 50}).encode())
        ok = status == 200 and data.get("ok", True)
        if not check("POST /lab/seed-batch (50)", ok, f"created={data.get('created', data.get('count', '?'))}"): fails += 1
    except Exception as e:
        if not check("POST /lab/seed-batch", False, str(e)): fails += 1

    # --- Metrics after seed ---
    try:
        _, batch = get("/metrics/batch")
        _, summary = get("/metrics/summary")
        at_risk = summary.get("at_risk_rupees", summary.get("total_at_risk_rupees", 0))
        cases = batch.get("total_cases", batch.get("cases", 0))
        if not check("Metrics after seed", at_risk > 0 or cases > 0, f"at_risk=₹{at_risk} cases={cases}"):
            fails += 1
    except Exception as e:
        if not check("Metrics after seed", False, str(e)): fails += 1

    # --- Fire all ---
    try:
        status, data = post("/lab/fire-all", BODY)
        results = data.get("results", [])
        if not check("POST /lab/fire-all", status == 200 and len(results) >= 10, f"{len(results)} scenarios"): fails += 1
    except Exception as e:
        if not check("POST /lab/fire-all", False, str(e)): fails += 1

    # --- Simulate recovery on first link ---
    try:
        _, activity = get("/lab/activity?limit=20")
        items = activity.get("activity", [])
        pay_item = next((a for a in items if a.get("payment_link_url") or a.get("intervention_id")), None)
        if pay_item and pay_item.get("intervention_id"):
            iid = pay_item["intervention_id"]
            status, sim = post(f"/demo/pay/{iid}/simulate")
            if not check("Simulate recovery", status == 200 and sim.get("ok", True), f"intervention={iid[:12]}..."): fails += 1
        else:
            check("Simulate recovery", True, "skipped — no payment link (Razorpay rate limit ok)")
    except Exception as e:
        if not check("Simulate recovery", False, str(e)): fails += 1

    # --- Promise-to-pay ---
    try:
        _, activity = get("/lab/activity?limit=5")
        audit_id = None
        for a in activity.get("activity", []):
            if a.get("audit_id"):
                audit_id = a["audit_id"]
                break
        if audit_id:
            status, pr = post("/lab/promise", json.dumps({
                "audit_id": audit_id,
                "promise_text": "Friday tak pay karunga",
            }).encode())
            if not check("POST /lab/promise", status == 200 and pr.get("ok", True)): fails += 1
        else:
            check("POST /lab/promise", True, "skipped — no audit_id")
    except Exception as e:
        if not check("POST /lab/promise", False, str(e)): fails += 1

    # --- Checkout order ---
    print("\nCheckout")
    try:
        status, order = post("/checkout/create-order", json.dumps({
            "amount": 49900,
            "email": "ganeshsuraj29@gmail.com",
        }).encode())
        ok = status == 200 and bool(order.get("order_id") or order.get("id"))
        if not check("POST /checkout/create-order", ok, f"order_id={order.get('order_id', order.get('id', '?'))}"): fails += 1
    except Exception as e:
        if not check("POST /checkout/create-order", False, str(e)): fails += 1

    print(f"\n=== Result: {fails} failure(s) ===\n")
    return fails


if __name__ == "__main__":
    sys.exit(main())
