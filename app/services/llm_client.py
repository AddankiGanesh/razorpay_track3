"""Unified LLM client — Gemini, Groq, xAI Grok, or OpenAI."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _grok_api_key() -> str:
    settings = get_settings()
    return (settings.grok_api_key or settings.xai_api_key or "").strip()


def _provider() -> str | None:
    settings = get_settings()
    pref = (settings.llm_provider or "auto").lower()
    has_gemini = bool(settings.gemini_api_key)
    has_groq = bool(settings.groq_api_key)
    has_grok = bool(_grok_api_key())
    has_openai = bool(settings.openai_api_key)

    if pref == "gemini" and has_gemini:
        return "gemini"
    if pref == "groq" and has_groq:
        return "groq"
    if pref == "grok" and has_grok:
        return "grok"
    if pref == "openai" and has_openai:
        return "openai"
    if pref == "auto":
        if has_gemini:
            return "gemini"
        if has_groq:
            return "groq"
        if has_grok:
            return "grok"
        if has_openai:
            return "openai"
        return None
    if has_gemini:
        return "gemini"
    if has_groq:
        return "groq"
    if has_grok:
        return "grok"
    if has_openai:
        return "openai"
    return None


def llm_configured() -> bool:
    return _provider() is not None


def llm_provider_name() -> str | None:
    return _provider()


def llm_complete(
    *,
    system: str,
    user: str,
    max_tokens: int = 256,
    temperature: float = 0.3,
) -> str | None:
    """Return model text or None (caller falls back to heuristics)."""
    provider = _provider()
    if not provider:
        return None
    if provider == "gemini":
        return _gemini_complete(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
    if provider == "grok":
        return _grok_complete(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
    if provider == "groq":
        return _groq_complete(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
    return _openai_complete(system=system, user=user, max_tokens=max_tokens, temperature=temperature)


def _gemini_complete(
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    settings = get_settings()
    model = settings.gemini_model
    url = f"{GEMINI_BASE}/{model}:generateContent"
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": settings.gemini_api_key},
                json=payload,
            )
        if resp.status_code >= 400:
            logger.warning("Gemini API error %s: %s", resp.status_code, resp.text[:300])
            return None
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        return text or None
    except Exception as exc:
        logger.debug("Gemini request failed: %s", exc)
        return None


def _chat_completions_complete(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    provider_label: str,
) -> str | None:
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        if resp.status_code >= 400:
            logger.warning("%s API error %s: %s", provider_label, resp.status_code, resp.text[:300])
            return None
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.debug("%s request failed: %s", provider_label, exc)
        return None


def _groq_complete(
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    settings = get_settings()
    return _chat_completions_complete(
        base_url=settings.groq_api_base,
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=temperature,
        provider_label="Groq",
    )


def _grok_complete(
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    settings = get_settings()
    return _chat_completions_complete(
        base_url=settings.grok_api_base,
        api_key=_grok_api_key(),
        model=settings.grok_model,
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=temperature,
        provider_label="Grok",
    )


def _openai_complete(
    *,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    settings = get_settings()
    return _chat_completions_complete(
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=temperature,
        provider_label="OpenAI",
    )
