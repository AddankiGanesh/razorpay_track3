"""Build live pipeline steps for judge-facing UI when a scenario fires."""

from __future__ import annotations

from typing import Any

from app.lab.scenarios import FireResult
from app.services.link_pool import link_error_label

_TERMINAL = frozenset({"blocked", "skipped", "done", "waiting", "ready"})


def build_recovery_pipeline(result: FireResult, scenario: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    scenario = scenario or {}
    amount = result.amount_paise / 100
    reason = result.error_reason or scenario.get("reason") or "—"
    intended = result.intended_action or scenario.get("reason") or "—"
    if result.stopped and result.intended_action:
        intended = result.intended_action
    elif not result.stopped:
        intended = result.recommended_action or intended

    stop_label = result.stop_reason or result.recommended_action or "compliance rule"

    steps: list[dict[str, Any]] = [
        {
            "stage": 1,
            "key": "detect",
            "title": "Detect",
            "status": "done",
            "detail": f"Webhook `{result.event}` · Rs {amount:.0f} at risk",
            "halted": False,
        },
        {
            "stage": 2,
            "key": "diagnose",
            "title": "Diagnose",
            "status": "done",
            "detail": f"Reason `{reason}` → playbook `{intended}`"
            + (f" ({result.diagnosis_path})" if result.diagnosis_path else ""),
            "halted": False,
        },
    ]

    if result.stopped:
        decide = {
            "stage": 3,
            "key": "decide",
            "title": "Decide + stop",
            "status": "blocked",
            "detail": f"STOPPED here · {stop_label}",
            "hint": _stopping_hint(stop_label),
            "halted": True,
        }
    elif result.delayed:
        decide = {
            "stage": 3,
            "key": "decide",
            "title": "Decide + stop",
            "status": "delayed",
            "detail": "Bank/gateway downtime — customer nudge deferred",
            "hint": "No spam during outage window",
            "halted": False,
        }
    elif intended in {"wait_and_poll", "wait_and_poll_late_auth"} or result.status == "watching":
        decide = {
            "stage": 3,
            "key": "decide",
            "title": "Decide + stop",
            "status": "skipped",
            "detail": "Late auth — watch only, no customer nudge",
            "hint": "Pipeline ends here by design",
            "halted": True,
        }
    else:
        decide = {
            "stage": 3,
            "key": "decide",
            "title": "Decide + stop",
            "status": "done",
            "detail": "Within compliance limits — recovery allowed",
            "hint": None,
            "halted": False,
        }
    steps.append(decide)

    halted_at_decide = decide.get("halted") or decide["status"] == "blocked"

    if halted_at_decide and result.stopped:
        execute = {
            "stage": 4,
            "key": "execute",
            "title": "Execute",
            "status": "not_run",
            "detail": "Not executed — stopped at Decide step",
            "payment_link_url": None,
            "demo_pay_url": None,
            "halted": True,
        }
    elif halted_at_decide:
        execute = {
            "stage": 4,
            "key": "execute",
            "title": "Execute",
            "status": "not_run",
            "detail": "Not executed — no customer nudge for this path",
            "payment_link_url": None,
            "demo_pay_url": None,
            "halted": True,
        }
    elif result.razorpay_payment_link:
        reused = result.status == "reused_link"
        detail = result.pay_path_note or (
            f"Channel `{result.channel or 'email'}` · Reused existing Razorpay link"
            if reused
            else f"Channel `{result.channel or 'email'}` · Razorpay payment link ready"
        )
        execute = {
            "stage": 4,
            "key": "execute",
            "title": "Execute",
            "status": "done",
            "detail": detail,
            "payment_link_url": result.razorpay_payment_link,
            "demo_pay_url": result.demo_pay_url,
            "halted": False,
        }
    elif result.demo_pay_url or result.intervention_id:
        demo = result.demo_pay_url or f"/pay/{result.intervention_id}"
        execute = {
            "stage": 4,
            "key": "execute",
            "title": "Execute",
            "status": "done",
            "detail": result.pay_path_note or (
                f"Execute complete · 30-link cap — no unpaid Razorpay link for Rs {amount:.0f} "
                f"· Demo pay ready"
            ),
            "payment_link_url": None,
            "demo_pay_url": demo,
            "halted": False,
        }
    elif result.delayed:
        execute = {
            "stage": 4,
            "key": "execute",
            "title": "Execute",
            "status": "pending",
            "detail": "Will retry after downtime window",
            "payment_link_url": None,
            "demo_pay_url": None,
            "halted": False,
        }
    else:
        execute = {
            "stage": 4,
            "key": "execute",
            "title": "Execute",
            "status": "pending",
            "detail": "Waiting for payment link — try Retry failed links",
            "payment_link_url": result.payment_link_url,
            "demo_pay_url": result.demo_pay_url,
            "halted": False,
        }
    steps.append(execute)

    halted_at_execute = execute.get("halted") or execute["status"] == "not_run"

    if result.status == "recovered":
        attr = {
            "stage": 5,
            "key": "attribute",
            "title": "Attribute",
            "status": "done",
            "detail": f"Rs {amount:.0f} recovered · linked to intervention",
            "halted": False,
        }
    elif halted_at_decide or execute["status"] == "not_run":
        attr = {
            "stage": 5,
            "key": "attribute",
            "title": "Attribute",
            "status": "not_run",
            "detail": "Not reached — pipeline stopped earlier",
            "halted": True,
        }
    elif result.razorpay_payment_link:
        attr = {
            "stage": 5,
            "key": "attribute",
            "title": "Attribute",
            "status": "ready",
            "detail": "Pay the Razorpay link → recovery attributed on order.paid",
            "halted": False,
        }
    else:
        attr = {
            "stage": 5,
            "key": "attribute",
            "title": "Attribute",
            "status": "ready",
            "detail": "Open Demo pay → click Simulate successful recovery to finish",
            "halted": False,
        }
    steps.append(attr)

    return steps


def _stopping_hint(reason: str) -> str:
    r = (reason or "").lower()
    if "promise_to_pay" in r:
        return "Click Clear promises or Reset demo data, then fire again"
    if "max_nudges" in r:
        return "Global nudge cap hit — Reset demo data, or fire payment failures (each has unique order)"
    if "soft_nudge" in r:
        return "Soft nudge already sent once for this customer — try Wrong OTP or Reset demo"
    if "order_already_recovered" in r:
        return "This order was already recovered"
    return "Stopping rule active — Reset demo or Clear promises"
