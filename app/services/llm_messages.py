"""LLM-personalized recovery messages — optional layer on template messages."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.diagnosis.engine import DiagnosisResult
from app.services.customer_context import CustomerContext
from app.services.llm_client import llm_complete

logger = logging.getLogger(__name__)


def personalize_recovery_message(
    base_message: str,
    *,
    diagnosis: DiagnosisResult,
    customer: CustomerContext,
    amount_rupees: float,
    recovery_score: int,
    payment_link_url: str | None,
) -> tuple[str, str]:
    settings = get_settings()
    if not settings.llm_messages_enabled:
        return base_message, "template"

    prompt = f"""Rewrite this payment recovery SMS/email for an Indian merchant customer.
Keep under 280 chars. Keep payment link URL exactly as given. Be polite, specific, no jargon.

Customer: {customer.name} ({customer.persona}, {customer.engagement} engagement)
Failure: {diagnosis.reason or 'payment issue'}
Action: {diagnosis.action}
Amount: Rs {amount_rupees:.0f}
Recovery score: {recovery_score}/100
Base message:
{base_message}

Reply with ONLY the final message text."""

    text = llm_complete(
        system="Concise Indian fintech recovery copywriter.",
        user=prompt,
        max_tokens=200,
        temperature=0.4,
    )
    if not text:
        return base_message, "template"

    if payment_link_url and payment_link_url not in text:
        text = f"{text}\n\nRetry here: {payment_link_url}"
    from app.services.llm_client import llm_provider_name

    source = llm_provider_name() or "llm"
    return text[:600], source
