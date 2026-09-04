"""Optional LLM narrative layer — explains leakage & strategy (never executes payments)."""

from __future__ import annotations

import logging
from typing import Any

from app.services.llm_client import llm_complete

logger = logging.getLogger(__name__)


def narrate_leakage_report(report: dict[str, Any]) -> str:
    summary = {
        "total_loss_rupees": report.get("total_loss_rupees"),
        "top_reasons": report.get("by_reason", [])[:5],
        "top_methods": report.get("by_payment_method", [])[:3],
        "peak_hours": report.get("by_hour_ist", [])[:3],
    }
    prompt = (
        "You are a Razorpay revenue recovery analyst. In 2-3 sentences, summarize this "
        "merchant leakage report for a hackathon judge. Be specific with numbers. "
        f"Data: {summary}"
    )
    text = llm_complete(
        system="Concise merchant-facing revenue insights.",
        user=prompt,
        max_tokens=200,
        temperature=0.3,
    )
    return text or report.get("heuristic_insight", "")


def explain_recovery_decision(context: dict[str, Any]) -> str | None:
    from app.config import get_settings

    if not get_settings().llm_explanations_enabled:
        return None
    return llm_complete(
        system="One sentence recovery analyst explanation.",
        user=f"Explain in one sentence why this recovery decision makes sense: {context}",
        max_tokens=80,
        temperature=0.3,
    )
