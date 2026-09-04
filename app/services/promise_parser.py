"""Parse customer promise-to-pay text — LLM when configured, else smart regex."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.llm_client import llm_complete, llm_configured, llm_provider_name

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
    "somvar": 0,
    "mangalvar": 1,
    "budhvar": 2,
    "guruvar": 3,
    "shukravar": 4,
    "shaniwar": 5,
    "ravivar": 6,
}


def _default_evening(dt: datetime) -> datetime:
    return dt.replace(hour=18, minute=0, second=0, microsecond=0)


def _next_weekday(now: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return _default_evening(now + timedelta(days=days_ahead))


def parse_promise_date_regex(text: str, *, now: datetime | None = None) -> tuple[datetime, str]:
    """Regex/heuristic parser — always available fallback."""
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    lower = text.lower()

    if re.search(r"\b(tuesday|wed|monday|mon|friday|fri|saturday|sat|sunday|sun)\b.*\b(tak|ko|par)\b", lower):
        for token, wd in _WEEKDAYS.items():
            if token in lower:
                return _next_weekday(now, wd), "regex_hinglish_weekday"

    if re.search(r"\bpay\s*kar\s*(dunga|denge|karunga|karenge)\b", lower):
        if re.search(r"\bkal\b", lower):
            return _default_evening(now + timedelta(days=1)), "regex_hinglish_kal"
        m = re.search(r"\b(\d+)\s*days?\b", lower)
        if m:
            return _default_evening(now + timedelta(days=int(m.group(1)))), "regex_hinglish_days"
        return _default_evening(now + timedelta(days=2)), "regex_hinglish_promise"

    for token, wd in _WEEKDAYS.items():
        if re.search(rf"\b{re.escape(token)}\b", lower):
            return _next_weekday(now, wd), "regex_weekday"

    m = re.search(r"\b(\d+)\s*days?\b", lower)
    if m:
        return _default_evening(now + timedelta(days=int(m.group(1)))), "regex_days"

    if re.search(r"\b(next week|agle hafte|agle week)\b", lower):
        return _default_evening(now + timedelta(days=7)), "regex_next_week"

    m_next = re.search(
        r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b",
        lower,
    )
    if m_next:
        token = m_next.group(1)
        for key, wd in _WEEKDAYS.items():
            if key == token or key.startswith(token[:3]):
                return _next_weekday(now, wd), "regex_next_weekday"

    if re.search(r"\b(will pay|pay on|pay by|page on)\b", lower):
        for token, wd in _WEEKDAYS.items():
            if re.search(rf"\b{re.escape(token)}\b", lower):
                return _next_weekday(now, wd), "regex_english_weekday"

    if re.search(r"\b(tomorrow|kal)\b", lower):
        return _default_evening(now + timedelta(days=1)), "regex_tomorrow"

    m_hin = re.search(r"\b(\d+)\s*(din|day)s?\s*(mein|me)\b", lower)
    if m_hin:
        return _default_evening(now + timedelta(days=int(m_hin.group(1)))), "regex_hinglish_days"

    if re.search(r"\b(tak pay|pay karunga|pay kar dunga|kar dunga|karunga)\b", lower):
        return _default_evening(now + timedelta(days=2)), "regex_hinglish_promise"

    if re.search(r"\b(day after|parso|parson)\b", lower):
        return _default_evening(now + timedelta(days=2)), "regex_day_after"

    if re.search(r"\b(today|aaj)\b", lower):
        return now.replace(hour=23, minute=0, second=0, microsecond=0), "regex_today"

    return _default_evening(now + timedelta(days=2)), "regex_default"


def _parse_llm(text: str, *, now: datetime) -> tuple[datetime | None, str, float]:
    if not llm_configured():
        return None, "no_llm_key", 0.0

    prompt = f"""Extract when the customer promises to pay from this message.
Today is {now.astimezone(IST).strftime("%A %Y-%m-%d %H:%M IST")}.
Message: "{text}"

Reply JSON only:
{{"promised_date_iso": "YYYY-MM-DDTHH:MM:SS+05:30", "confidence": 0.0-1.0, "intent": "promise_to_pay|unclear|refuse"}}
Use 18:00 IST if no time given. For weekdays use the NEXT occurrence."""

    content = llm_complete(
        system="You extract payment promise dates. JSON only.",
        user=prompt,
        max_tokens=120,
        temperature=0.1,
    )
    if not content:
        return None, "llm_error", 0.0

    try:
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        data = json.loads(content)
        if data.get("intent") == "refuse":
            return None, "llm_refuse", float(data.get("confidence", 0.5))
        iso = data.get("promised_date_iso")
        if not iso:
            return None, "llm_no_date", 0.0
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        tag = llm_provider_name() or "llm"
        return dt.astimezone(timezone.utc), tag, float(data.get("confidence", 0.85))
    except Exception as exc:
        logger.warning("LLM promise parse exception: %s", exc)
        return None, "llm_exception", 0.0


def parse_customer_promise(text: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Universal promise parser for any channel (SMS, email, voice transcript, WhatsApp)."""
    now = now or datetime.now(timezone.utc)
    text = (text or "").strip()
    if not text:
        regex_dt, method = parse_promise_date_regex("2 days", now=now)
        return {
            "promised_date": regex_dt,
            "parsed_by": method,
            "confidence": 0.3,
            "raw_text": text,
        }

    llm_dt, llm_method, confidence = _parse_llm(text, now=now)
    if llm_dt is not None:
        return {
            "promised_date": llm_dt,
            "parsed_by": llm_method,
            "confidence": confidence,
            "raw_text": text,
        }

    regex_dt, method = parse_promise_date_regex(text, now=now)
    return {
        "promised_date": regex_dt,
        "parsed_by": method,
        "confidence": 0.75 if method != "regex_default" else 0.5,
        "raw_text": text,
    }
