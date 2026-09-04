"""Shared scenario definitions and webhook firing for Lab + CLI."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings, internal_webhook_url
from app.services.link_pool import pay_path_explanation
from app.services.razorpay_client import get_razorpay_client

FAILURE_SCENARIOS: list[dict[str, Any]] = [
    {"id": "incorrect_otp", "reason": "incorrect_otp", "source": "customer", "step": "payment_authentication", "amount": 49900, "label": "Wrong OTP"},
    {"id": "otp_expired", "reason": "otp_expired", "source": "customer", "step": "payment_authentication", "amount": 29900, "label": "OTP expired"},
    {"id": "insufficient_funds", "reason": "insufficient_funds", "source": "customer", "step": "payment_authorization", "amount": 150000, "label": "Low balance"},
    {"id": "payment_cancelled", "reason": "payment_cancelled", "source": "customer", "step": "payment_authentication", "amount": 79900, "label": "Customer cancelled"},
    {"id": "bank_technical_error", "reason": "bank_technical_error", "source": "bank", "step": "payment_authorization", "amount": 99900, "label": "Bank downtime"},
    {"id": "invalid_vpa", "reason": "invalid_vpa", "source": "customer", "step": "payment_authentication", "amount": 25000, "method": "upi", "label": "Invalid UPI VPA"},
    {"id": "payment_risk_check_failed", "reason": "payment_risk_check_failed", "source": "bank", "step": "payment_authorization", "amount": 120000, "label": "Risk check failed"},
    {"id": "otp_attempts_exceeded", "reason": "otp_attempts_exceeded", "source": "customer", "step": "payment_authentication", "amount": 34900, "label": "OTP attempts exceeded"},
]

SUBSCRIPTION_SCENARIOS: list[dict[str, Any]] = [
    {"id": "subscription_pending", "event": "subscription.pending", "amount": 19900, "label": "Subscription payment pending"},
    {"id": "subscription_halted", "event": "subscription.halted", "amount": 19900, "label": "Subscription halted"},
    {
        "id": "mandate_debit_declined",
        "reason": "debit_declined",
        "source": "bank",
        "step": "payment_authorization",
        "amount": 19900,
        "label": "Mandate debit declined (sequencer)",
    },
]

B2B_SCENARIOS: list[dict[str, Any]] = [
    {"id": "payment_link_expired", "event": "payment_link.expired", "amount": 2500000, "label": "B2B payment link expired"},
]

ABANDONMENT_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "checkout_abandoned",
        "reason": "checkout_abandoned",
        "source": "customer",
        "step": "payment_authentication",
        "amount": 89900,
        "label": "Checkout abandoned (drop-off)",
    },
]

LATE_AUTH_SCENARIOS: list[dict[str, Any]] = [
    {"id": "late_auth_pending", "event": "payment.pending", "amount": 129900, "label": "Late auth pending (no nudge)"},
]


@dataclass
class ScenarioCatalog:
    failures: list[dict[str, Any]] = field(default_factory=lambda: list(FAILURE_SCENARIOS))
    subscriptions: list[dict[str, Any]] = field(default_factory=lambda: list(SUBSCRIPTION_SCENARIOS))
    b2b: list[dict[str, Any]] = field(default_factory=lambda: list(B2B_SCENARIOS))
    abandonment: list[dict[str, Any]] = field(default_factory=lambda: list(ABANDONMENT_SCENARIOS))
    late_auth: list[dict[str, Any]] = field(default_factory=lambda: list(LATE_AUTH_SCENARIOS))

    def all_scenarios(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for s in self.failures:
            items.append({**s, "group": "payment_failure"})
        for s in self.abandonment:
            items.append({**s, "group": "abandonment"})
        for s in self.late_auth:
            items.append({**s, "group": "late_auth"})
        for s in self.subscriptions:
            group = "payment_failure" if "reason" in s else "subscription"
            items.append({**s, "group": group})
        for s in self.b2b:
            items.append({**s, "group": "b2b"})
        return items

    def get(self, scenario_id: str) -> dict[str, Any] | None:
        for item in self.all_scenarios():
            if item["id"] == scenario_id:
                return item
        return None


scenario_catalog = ScenarioCatalog()


def sign_payload(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def build_payment_failed_payload(
    *,
    order_id: str,
    payment_id: str,
    amount: int,
    reason: str,
    source: str,
    step: str,
    method: str = "card",
    email: str = "demo@revrecover.test",
    contact: str = "+919876543210",
) -> dict:
    return {
        "event": "payment.failed",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "method": method,
                    "email": email,
                    "contact": contact,
                    "error_reason": reason,
                    "error_source": source,
                    "error_step": step,
                    "status": "failed",
                }
            }
        },
    }


def build_success_payload(event_type: str, order_id: str, payment_id: str, amount: int) -> dict:
    return {
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "method": "card",
                    "status": "captured",
                }
            },
            "order": {"entity": {"id": order_id, "amount": amount, "currency": "INR", "status": "paid"}},
        },
    }


def build_subscription_payload(
    event_type: str,
    amount: int,
    email: str = "demo@revrecover.test",
    contact: str = "+919876543210",
) -> dict:
    sub_id = f"sub_{uuid.uuid4().hex[:14]}"
    return {
        "event": event_type,
        "payload": {
            "subscription": {
                "entity": {
                    "id": sub_id,
                    "status": event_type.split(".")[1],
                    "plan_id": "plan_demo",
                }
            },
            "payment": {
                "entity": {
                    "id": f"pay_{uuid.uuid4().hex[:14]}",
                    "amount": amount,
                    "email": email,
                    "contact": contact,
                }
            },
        },
    }


def build_payment_pending_payload(
    *,
    amount: int,
    email: str = "demo@revrecover.test",
    contact: str = "+919876543210",
) -> dict:
    return {
        "event": "payment.pending",
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_{uuid.uuid4().hex[:14]}",
                    "order_id": f"order_{uuid.uuid4().hex[:14]}",
                    "amount": amount,
                    "currency": "INR",
                    "method": "card",
                    "email": email,
                    "contact": contact,
                    "status": "pending",
                }
            }
        },
    }


def build_payment_link_expired_payload(
    amount: int,
    email: str = "demo@revrecover.test",
    contact: str = "+919876543210",
    order_id: str | None = None,
) -> dict:
    order_id = order_id or f"order_{uuid.uuid4().hex[:14]}"
    return {
        "event": "payment_link.expired",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": f"plink_{uuid.uuid4().hex[:14]}",
                    "amount": amount,
                    "currency": "INR",
                    "status": "expired",
                    "reference_id": order_id,
                }
            },
            "payment": {
                "entity": {
                    "id": f"pay_{uuid.uuid4().hex[:14]}",
                    "order_id": order_id,
                    "amount": amount,
                    "email": email,
                    "contact": contact,
                }
            },
        },
    }


def post_webhook(client: httpx.Client, url: str, payload: dict, secret: str) -> dict:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Razorpay-Signature"] = sign_payload(body, secret)
    response = client.post(url, content=body, headers=headers, timeout=30.0)
    response.raise_for_status()
    return response.json()


@dataclass
class FireResult:
    scenario_id: str
    label: str
    group: str
    event: str
    order_id: str | None
    amount_paise: int
    recommended_action: str | None
    payment_link_url: str | None
    channel: str | None
    message_preview: str | None
    ok: bool
    audit_id: str | None = None
    error: str | None = None
    status: str | None = None
    delayed: bool = False
    stopped: bool = False
    mandate_plan: dict[str, Any] | None = None
    intervention_id: str | None = None
    demo_pay_url: str | None = None
    razorpay_payment_link: str | None = None
    error_reason: str | None = None
    diagnosis_path: str | None = None
    intended_action: str | None = None
    stop_reason: str | None = None
    link_error: str | None = None
    pay_path_note: str | None = None


def _extract_recovery(result: dict) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    bool,
    bool,
    dict | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    recovery = result.get("recovery") or {}
    return (
        recovery.get("payment_link_url"),
        recovery.get("channel"),
        recovery.get("message_preview"),
        recovery.get("status") or result.get("recommended_action"),
        bool(recovery.get("delayed")),
        bool(recovery.get("stopped")),
        recovery.get("mandate_plan"),
        recovery.get("intervention_id"),
        recovery.get("demo_pay_url"),
        recovery.get("razorpay_payment_link"),
        recovery.get("intended_action") or result.get("recommended_action"),
        recovery.get("stop_reason"),
        recovery.get("link_error"),
    )


def _fire_result_from_webhook(
    *,
    scenario_id: str,
    label: str,
    group: str,
    event: str,
    order_id: str | None,
    amount_paise: int,
    result: dict,
    error_reason: str | None = None,
) -> FireResult:
    (
        link,
        channel,
        preview,
        status,
        delayed,
        stopped,
        mandate_plan,
        intervention_id,
        demo_pay_url,
        razorpay_link,
        intended_action,
        stop_reason,
        link_error,
    ) = _extract_recovery(result)
    pay_url = razorpay_link or (link if link and str(link).startswith("http") else None)
    demo_url = demo_pay_url or (link if link and str(link).startswith("/pay/") else None)
    if not demo_url and intervention_id:
        demo_url = f"/pay/{intervention_id}"
    path_note = pay_path_explanation(
        amount_paise=amount_paise,
        status=status,
        has_razorpay_url=bool(pay_url),
        link_error=link_error,
    )
    return FireResult(
        scenario_id=scenario_id,
        label=label,
        group=group,
        event=event,
        order_id=order_id,
        amount_paise=amount_paise,
        recommended_action=result.get("recommended_action") or status,
        payment_link_url=pay_url or demo_url or link,
        channel=channel,
        message_preview=preview,
        ok=True,
        audit_id=result.get("audit_id"),
        status=status,
        delayed=delayed,
        stopped=stopped,
        mandate_plan=mandate_plan,
        intervention_id=intervention_id,
        demo_pay_url=demo_url,
        razorpay_payment_link=razorpay_link,
        error_reason=error_reason,
        diagnosis_path=result.get("diagnosis_path"),
        intended_action=intended_action,
        stop_reason=stop_reason,
        link_error=link_error,
        pay_path_note=path_note or None,
    )


def fire_scenario(
    scenario_id: str,
    *,
    webhook_url: str | None = None,
    customer_email: str | None = None,
    customer_contact: str | None = None,
) -> FireResult:
    settings = get_settings()
    url = webhook_url or internal_webhook_url()
    secret = settings.razorpay_webhook_secret
    email = customer_email or settings.demo_customer_email
    contact = customer_contact or settings.demo_customer_contact
    scenario = scenario_catalog.get(scenario_id)
    if not scenario:
        raise ValueError(f"Unknown scenario: {scenario_id}")

    group = scenario["group"]
    label = scenario.get("label", scenario_id)

    with httpx.Client() as client:
        if group in {"payment_failure", "abandonment"}:
            rz = get_razorpay_client()
            order = rz.order.create(
                {"amount": scenario["amount"], "currency": "INR", "payment_capture": 1}
            )
            order_id = order["id"]
            payment_id = f"pay_{uuid.uuid4().hex[:14]}"
            payload = build_payment_failed_payload(
                order_id=order_id,
                payment_id=payment_id,
                amount=scenario["amount"],
                reason=scenario["reason"],
                source=scenario["source"],
                step=scenario["step"],
                method=scenario.get("method", "card"),
                email=email,
                contact=contact,
            )
            result = post_webhook(client, url, payload, secret)
            return _fire_result_from_webhook(
                scenario_id=scenario_id,
                label=label,
                group=group,
                event="payment.failed",
                order_id=order_id,
                amount_paise=scenario["amount"],
                result=result,
                error_reason=scenario.get("reason"),
            )

        if group == "late_auth":
            payload = build_payment_pending_payload(
                amount=scenario["amount"], email=email, contact=contact
            )
            result = post_webhook(client, url, payload, secret)
            return _fire_result_from_webhook(
                scenario_id=scenario_id,
                label=label,
                group=group,
                event="payment.pending",
                order_id=None,
                amount_paise=scenario["amount"],
                result=result,
                error_reason=scenario.get("reason"),
            )

        if group == "subscription":
            payload = build_subscription_payload(
                scenario["event"], scenario["amount"], email=email, contact=contact
            )
            result = post_webhook(client, url, payload, secret)
            return _fire_result_from_webhook(
                scenario_id=scenario_id,
                label=label,
                group=group,
                event=scenario["event"],
                order_id=None,
                amount_paise=scenario["amount"],
                result=result,
                error_reason=scenario.get("reason"),
            )

        payload = build_payment_link_expired_payload(
            scenario["amount"], email=email, contact=contact
        )
        order_id = payload["payload"]["payment"]["entity"]["order_id"]
        result = post_webhook(client, url, payload, secret)
        return _fire_result_from_webhook(
            scenario_id=scenario_id,
            label=label,
            group=group,
            event=scenario["event"],
            order_id=order_id,
            amount_paise=scenario["amount"],
            result=result,
            error_reason=scenario.get("reason"),
        )


def fire_all_scenarios(
    *,
    webhook_url: str | None = None,
    simulate_recovery: bool = False,
    recovery_count: int = 3,
    delay: float = 3.0,
    customer_email: str | None = None,
    customer_contact: str | None = None,
) -> list[FireResult]:
    settings = get_settings()
    url = webhook_url or internal_webhook_url()
    secret = settings.razorpay_webhook_secret
    email = customer_email or settings.demo_customer_email
    contact = customer_contact or settings.demo_customer_contact
    results: list[FireResult] = []
    failure_orders: list[tuple[str, int]] = []

    with httpx.Client() as client:
        for scenario in scenario_catalog.all_scenarios():
            try:
                fired = fire_scenario(
                    scenario["id"],
                    webhook_url=url,
                    customer_email=email,
                    customer_contact=contact,
                )
                results.append(fired)
                if fired.order_id and scenario["group"] in {"payment_failure", "abandonment"}:
                    failure_orders.append((fired.order_id, fired.amount_paise))
            except Exception as exc:
                results.append(
                    FireResult(
                        scenario_id=scenario["id"],
                        label=scenario.get("label", scenario["id"]),
                        group=scenario["group"],
                        event=scenario.get("event") or "payment.failed",
                        order_id=None,
                        amount_paise=scenario["amount"],
                        recommended_action=None,
                        payment_link_url=None,
                        channel=None,
                        message_preview=None,
                        ok=False,
                        error=str(exc),
                    )
                )
            time.sleep(delay)

        if simulate_recovery:
            for order_id, amount in failure_orders[:recovery_count]:
                payment_id = f"pay_{uuid.uuid4().hex[:14]}"
                payload = build_success_payload("order.paid", order_id, payment_id, amount)
                post_webhook(client, url, payload, secret)
                time.sleep(delay)

    return results
