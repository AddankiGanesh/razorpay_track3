from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl

from app.config import PROJECT_ROOT, get_settings

# Default recovery actions for known high-frequency failure reasons
DEFAULT_ACTIONS: dict[str, dict[str, Any]] = {
    "incorrect_otp": {
        "fault": "customer",
        "recoverable": True,
        "action": "retry_with_new_otp",
        "channel": ["sms", "email"],
        "priority": "high",
    },
    "otp_expired": {
        "fault": "customer",
        "recoverable": True,
        "action": "retry_immediate",
        "channel": ["sms"],
        "priority": "high",
    },
    "otp_attempts_exceeded": {
        "fault": "customer",
        "recoverable": True,
        "action": "suggest_alternate_method",
        "channel": ["sms"],
        "priority": "medium",
    },
    "insufficient_funds": {
        "fault": "customer",
        "recoverable": True,
        "action": "retry_delayed",
        "channel": ["sms"],
        "priority": "medium",
    },
    "payment_cancelled": {
        "fault": "customer",
        "recoverable": True,
        "action": "soft_nudge_once",
        "channel": ["email"],
        "priority": "low",
    },
    "checkout_abandoned": {
        "fault": "customer",
        "recoverable": True,
        "action": "soft_nudge_once",
        "channel": ["email"],
        "priority": "low",
    },
    "payment_timed_out": {
        "fault": "customer",
        "recoverable": True,
        "action": "retry_with_urgency",
        "channel": ["sms"],
        "priority": "high",
    },
    "bank_technical_error": {
        "fault": "bank",
        "recoverable": True,
        "action": "delay_retry",
        "channel": ["email"],
        "priority": "medium",
        "check_downtime": True,
    },
    "gateway_technical_error": {
        "fault": "gateway",
        "recoverable": True,
        "action": "delay_retry",
        "channel": ["email"],
        "priority": "medium",
        "check_downtime": True,
    },
    "payment_risk_check_failed": {
        "fault": "bank",
        "recoverable": True,
        "action": "suggest_alternate_method",
        "channel": ["sms"],
        "priority": "medium",
    },
    "capture_failed": {
        "fault": "gateway",
        "recoverable": True,
        "action": "auto_retry_capture",
        "channel": ["system"],
        "priority": "critical",
    },
    "payment_pending": {
        "fault": "bank",
        "recoverable": True,
        "action": "wait_and_poll",
        "channel": ["system"],
        "priority": "low",
    },
    "debit_declined": {
        "fault": "bank",
        "recoverable": True,
        "action": "mandate_retry_sequence",
        "channel": ["sms"],
        "priority": "high",
    },
    "reqauth_mandate_not_acknowledged": {
        "fault": "customer",
        "recoverable": True,
        "action": "mandate_retry_sequence",
        "channel": ["sms", "email"],
        "priority": "high",
    },
}

FALLBACK_BY_SOURCE_STEP: dict[tuple[str, str], dict[str, Any]] = {
    ("customer", "payment_authentication"): {
        "action": "retry_with_guidance",
        "channel": ["sms"],
        "fault": "customer",
    },
    ("customer", "payment_authorization"): {
        "action": "retry_with_guidance",
        "channel": ["sms"],
        "fault": "customer",
    },
    ("bank", "payment_authorization"): {
        "action": "delay_retry",
        "channel": ["email"],
        "fault": "bank",
        "check_downtime": True,
    },
    ("gateway", "payment_authorization"): {
        "action": "delay_retry",
        "channel": ["email"],
        "fault": "gateway",
        "check_downtime": True,
    },
}

SAFE_DEFAULT: dict[str, Any] = {
    "action": "soft_nudge_once",
    "channel": ["email"],
    "fault": "unknown",
    "recoverable": True,
    "priority": "low",
}


@dataclass
class DiagnosisResult:
    path: str
    reason: str | None
    source: str | None
    step: str | None
    action: str
    fault: str
    recoverable: bool
    channels: list[str]
    explanation: str | None = None
    next_steps: str | None = None
    priority: str = "medium"
    check_downtime: bool = False


class DiagnosisEngine:
    def __init__(self) -> None:
        self.reason_catalog: dict[str, dict[str, str]] = {}
        self.reason_actions: dict[str, dict[str, Any]] = dict(DEFAULT_ACTIONS)
        self._load_catalog()

    def _load_catalog(self) -> None:
        settings = get_settings()
        catalog_path = Path(settings.reason_catalog_path)
        if not catalog_path.exists():
            catalog_path = PROJECT_ROOT / "payments_error_reasons.xlsx"
        if not catalog_path.exists():
            return

        workbook = openpyxl.load_workbook(catalog_path, read_only=True)
        sheet = workbook.active
        for idx, row in enumerate(sheet.iter_rows(values_only=True)):
            if idx == 0 or not row[0]:
                continue
            reason = str(row[0]).strip()
            self.reason_catalog[reason] = {
                "explanation": str(row[1] or "").strip(),
                "next_steps": str(row[2] or "").strip(),
            }
            if reason not in self.reason_actions:
                self.reason_actions[reason] = {
                    "fault": "unknown",
                    "recoverable": True,
                    "action": "soft_nudge_once",
                    "channel": ["email"],
                    "priority": "low",
                }
        workbook.close()

    def diagnose(
        self,
        error_reason: str | None,
        error_source: str | None,
        error_step: str | None,
    ) -> DiagnosisResult:
        reason = (error_reason or "").strip() or None
        source = (error_source or "").strip() or None
        step = (error_step or "").strip() or None

        catalog_entry = self.reason_catalog.get(reason or "", {})
        explanation = catalog_entry.get("explanation") or None
        next_steps = catalog_entry.get("next_steps") or None

        if reason and reason in self.reason_actions:
            action_cfg = self.reason_actions[reason]
            return DiagnosisResult(
                path="known_rule",
                reason=reason,
                source=source,
                step=step,
                action=action_cfg["action"],
                fault=action_cfg.get("fault", "unknown"),
                recoverable=bool(action_cfg.get("recoverable", True)),
                channels=list(action_cfg.get("channel", ["email"])),
                explanation=explanation,
                next_steps=next_steps,
                priority=action_cfg.get("priority", "medium"),
                check_downtime=bool(action_cfg.get("check_downtime", False)),
            )

        if source and step:
            fallback = FALLBACK_BY_SOURCE_STEP.get((source, step))
            if fallback:
                return DiagnosisResult(
                    path="source_step_fallback",
                    reason=reason,
                    source=source,
                    step=step,
                    action=fallback["action"],
                    fault=fallback.get("fault", source),
                    recoverable=True,
                    channels=list(fallback.get("channel", ["email"])),
                    explanation=explanation,
                    next_steps=next_steps,
                    priority="medium",
                    check_downtime=bool(fallback.get("check_downtime", False)),
                )

        return DiagnosisResult(
            path="safe_default",
            reason=reason,
            source=source,
            step=step,
            action=SAFE_DEFAULT["action"],
            fault=SAFE_DEFAULT["fault"],
            recoverable=SAFE_DEFAULT["recoverable"],
            channels=list(SAFE_DEFAULT["channel"]),
            explanation=explanation,
            next_steps=next_steps,
            priority=SAFE_DEFAULT["priority"],
        )


diagnosis_engine = DiagnosisEngine()
