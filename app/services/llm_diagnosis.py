"""LLM fallback diagnosis for unknown / low-confidence failure reasons."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import get_settings
from app.diagnosis.engine import DiagnosisResult
from app.services.llm_client import llm_complete

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = frozenset(
    {
        "retry_with_new_otp",
        "retry_immediate",
        "retry_delayed",
        "delay_retry",
        "soft_nudge_once",
        "suggest_alternate_method",
        "halted_revival_job",
        "regenerate_payment_link",
        "mandate_retry_sequence",
        "retry_with_urgency",
    }
)


def should_use_llm_diagnosis(result: DiagnosisResult) -> bool:
    return result.path == "safe_default"


def llm_enrich_diagnosis(
    result: DiagnosisResult,
    *,
    amount_paise: int | None = None,
) -> DiagnosisResult:
    settings = get_settings()
    if not settings.llm_diagnosis_enabled:
        return result
    if not should_use_llm_diagnosis(result):
        return result

    prompt = f"""You are a Razorpay payment recovery expert. Given a failed payment, recommend recovery action.

Failure reason: {result.reason or 'unknown'}
Error source: {result.source or 'unknown'}
Error step: {result.step or 'unknown'}
Amount paise: {amount_paise or 0}
Current fallback action: {result.action}

Reply JSON only:
{{"action": "<one of retry_with_new_otp|retry_immediate|retry_delayed|delay_retry|soft_nudge_once|suggest_alternate_method|halted_revival_job|regenerate_payment_link|mandate_retry_sequence|retry_with_urgency>",
 "priority": "critical|high|medium|low",
 "channels": ["sms","email","voice"],
 "recoverable": true,
 "rationale": "one sentence"}}"""

    content = llm_complete(
        system="Payment recovery playbook selector. JSON only.",
        user=prompt,
        max_tokens=180,
        temperature=0.2,
    )
    if not content:
        return result

    try:
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        data: dict[str, Any] = json.loads(content)
        action = data.get("action", result.action)
        if action not in _ALLOWED_ACTIONS:
            action = result.action
        channels = [c for c in data.get("channels", result.channels) if c in {"sms", "email", "voice", "whatsapp"}]
        if not channels:
            channels = list(result.channels)
        return DiagnosisResult(
            path="llm_diagnosis",
            reason=result.reason,
            source=result.source,
            step=result.step,
            action=action,
            fault=result.fault,
            recoverable=bool(data.get("recoverable", result.recoverable)),
            channels=channels,
            explanation=data.get("rationale") or result.explanation,
            next_steps=result.next_steps,
            priority=data.get("priority", result.priority),
            check_downtime=result.check_downtime,
        )
    except Exception as exc:
        logger.debug("LLM diagnosis parse skipped: %s", exc)
        return result
