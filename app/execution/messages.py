from app.diagnosis.engine import DiagnosisResult


def build_recovery_message(
    *,
    diagnosis: DiagnosisResult,
    amount_rupees: float,
    payment_link_url: str | None,
    customer_name: str = "Customer",
) -> str:
    reason = diagnosis.reason or "payment issue"
    link_line = f"\n\nRetry here: {payment_link_url}" if payment_link_url else ""

    templates: dict[str, str] = {
        "retry_with_new_otp": (
            f"Hi {customer_name}, your Rs {amount_rupees:.0f} payment failed due to incorrect OTP. "
            f"Please retry with a fresh OTP.{link_line}"
        ),
        "retry_immediate": (
            f"Hi {customer_name}, your OTP expired for Rs {amount_rupees:.0f}. "
            f"Retry now before it expires again.{link_line}"
        ),
        "suggest_alternate_method": (
            f"Hi {customer_name}, payment failed ({reason}). "
            f"Try UPI or another card for Rs {amount_rupees:.0f}.{link_line}"
        ),
        "retry_delayed": (
            f"Hi {customer_name}, Rs {amount_rupees:.0f} failed due to low balance. "
            f"Retry once funds are available.{link_line}"
        ),
        "delay_retry": (
            f"Hi {customer_name}, our payment partner had a temporary issue. "
            f"We will retry your Rs {amount_rupees:.0f} payment shortly.{link_line}"
        ),
        "soft_nudge_once": (
            f"Hi {customer_name}, you left Rs {amount_rupees:.0f} unpaid. "
            f"Complete payment when ready.{link_line}"
        ),
        "proactive_customer_nudge": (
            f"Hi {customer_name}, your subscription payment of Rs {amount_rupees:.0f} is pending. "
            f"Update your method before it halts.{link_line}"
        ),
        "halted_revival_job": (
            f"Hi {customer_name}, your subscription is HALTED — Razorpay will not auto-retry charges. "
            f"Pay Rs {amount_rupees:.0f} now to revive service and stop silent revenue loss.{link_line}"
        ),
        "regenerate_payment_link": (
            f"Hi {customer_name}, your B2B payment link expired. "
            f"Here is a fresh link for Rs {amount_rupees:.0f}.{link_line}"
        ),
        "mandate_retry_sequence": (
            f"Hi {customer_name}, your subscription auto-debit of Rs {amount_rupees:.0f} failed. "
            f"We will send a bounded SMS → email → re-register sequence (then stop).{link_line}"
        ),
    }

    default = (
        f"Hi {customer_name}, your Rs {amount_rupees:.0f} payment needs attention ({reason})."
        f"{link_line}"
    )
    return templates.get(diagnosis.action, default)
