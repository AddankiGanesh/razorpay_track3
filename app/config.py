from functools import lru_cache
from pathlib import Path

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    razorpay_key_id: str = "rzp_test_dummy"
    razorpay_key_secret: str = "dummy_secret"
    razorpay_webhook_secret: str = ""

    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'revrecover.db'}"
    reason_catalog_path: str = str(PROJECT_ROOT / "payments_error_reasons.xlsx")

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True

    # Razorpay test mode caps total payment links at 30 (does not reset hourly)
    payment_link_min_interval_sec: float = 8.0

    # Resend email (optional — falls back to log stub)
    resend_api_key: str = ""
    resend_from_email: str = "RevRecover <onboarding@resend.dev>"

    # Default demo customer (used when Lab email empty / B2B scenarios)
    demo_customer_email: str = "ganeshsuraj29@gmail.com"
    demo_customer_contact: str = "+919876543210"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # LLM — Gemini, xAI Grok, or OpenAI (set LLM_PROVIDER=grok to force Grok)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    llm_provider: str = "auto"  # auto | gemini | grok | groq | openai

    # Groq (keys start with gsk_) — https://console.groq.com
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_api_base: str = "https://api.groq.com/openai/v1"

    grok_api_key: str = ""
    xai_api_key: str = ""  # alias for grok_api_key (xAI console)
    grok_model: str = "grok-3-mini"
    grok_api_base: str = "https://api.x.ai/v1"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_api_base: str = "https://api.openai.com/v1"

    # ElevenLabs voice agent (uses Twilio-linked number for outbound)
    elevenlabs_api_key: str = ""
    elevenlabs_agent_id: str = ""
    elevenlabs_agent_phone_number_id: str = ""

    # Default monthly recovery spend cap for budget allocator demo
    recovery_budget_rupees: float = 50_000.0

    # ML recovery scoring (sklearn — works offline, no API key)
    ml_scoring_enabled: bool = False
    ml_blend_weight: float = 0.45  # weight on ML prob vs heuristic score

    # Optional LLM layers (Gemini, Grok, or OpenAI)
    llm_diagnosis_enabled: bool = True
    llm_messages_enabled: bool = True
    llm_explanations_enabled: bool = True

    # Auto-capture on payment.authorized
    auto_capture_enabled: bool = True

    # Lab demo: each payment failure has a unique order_id — don't block after 3 fires
    stopping_global_email_cap: int = 12
    stopping_use_per_order_limits: bool = True

    # Stopping rules: per-customer cap only for events without order_id (subs/B2B)
    global_nudge_cap: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_listen_port() -> int:
    """Port the process is actually bound to (may differ from APP_PORT when 8000 is busy)."""
    settings = get_settings()
    env_port = os.environ.get("REVRECOVER_LISTEN_PORT")
    if env_port:
        return int(env_port)
    return settings.app_port


def internal_webhook_url(request_base: str | None = None) -> str:
    """URL for in-process webhook simulation (lab fire / demo pay)."""
    if request_base:
        return request_base.rstrip("/") + "/webhooks/razorpay"
    return f"http://127.0.0.1:{get_listen_port()}/webhooks/razorpay"
