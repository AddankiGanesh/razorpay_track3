"""Machine learning recovery probability — sklearn logistic regression on historical outcomes."""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, get_settings
from app.diagnosis.engine import DiagnosisResult
from app.services.customer_context import CustomerContext
from app.services.recovery_score import HIGH_RECOVERY_REASONS, LOW_RECOVERY_REASONS

logger = logging.getLogger(__name__)

MODEL_PATH = PROJECT_ROOT / "data" / "recovery_model.joblib"
_MIN_TRAIN_SAMPLES = 20
_MODEL_CACHE: dict[str, Any] = {"pipeline": None, "meta": {}}

# Weak labels for bootstrap when DB has few recoveries (reason → P(recovered))
# Shared with batch_seed training pipeline — aligned to Razorpay error-reason taxonomy
REASON_RECOVERY_PRIORS: dict[str, float] = {
    "incorrect_otp": 0.78,
    "otp_expired": 0.72,
    "insufficient_funds": 0.55,
    "payment_cancelled": 0.22,
    "bank_technical_error": 0.48,
    "gateway_technical_error": 0.45,
    "payment_timed_out": 0.62,
    "debit_declined": 0.50,
    "checkout_abandoned": 0.30,
    "subscription_halted": 0.58,
    "b2b_expired": 0.65,
    "otp_attempts_exceeded": 0.18,
    "payment_risk_check_failed": 0.15,
    "invalid_vpa": 0.12,
}

_PRIORITY_MAP = {"critical": 3, "high": 2, "medium": 1, "low": 0}
_CHANNEL_MAP = {"email": 0, "sms": 1, "voice": 2, "whatsapp": 3, "system": 4}
_METHOD_MAP = {"upi": 0, "card": 1, "netbanking": 2, "wallet": 3, "emi": 4}


def feature_vector(
    *,
    amount_paise: int,
    error_reason: str | None,
    diagnosis: DiagnosisResult,
    customer: CustomerContext,
    channel: str,
    payment_method: str | None = None,
    event_hour: int | None = None,
) -> np.ndarray:
    reason = (error_reason or diagnosis.reason or "unknown").lower()
    hour = event_hour if event_hour is not None else datetime.now(timezone.utc).hour
    method = (payment_method or "unknown").lower()

    return np.array(
        [
            math.log1p(max(amount_paise, 0) / 100),
            hour / 24.0,
            1.0 if reason in HIGH_RECOVERY_REASONS else 0.0,
            1.0 if reason in LOW_RECOVERY_REASONS else 0.0,
            1.0 if diagnosis.check_downtime else 0.0,
            _PRIORITY_MAP.get(diagnosis.priority, 1) / 3.0,
            _CHANNEL_MAP.get(channel, 0) / 4.0,
            _METHOD_MAP.get(method, 5) / 5.0,
            min(customer.successful_payments, 20) / 20.0,
            min(customer.prior_failures_30d, 10) / 10.0,
            min(customer.reminders_ignored, 5) / 5.0,
            min(customer.nudges_sent_72h, 5) / 5.0,
            min(customer.prior_recoveries, 10) / 10.0,
            1.0 if customer.engagement == "high" else (0.5 if customer.engagement == "medium" else 0.0),
            1.0 if diagnosis.recoverable else 0.0,
        ],
        dtype=np.float64,
    )


def _synthetic_dataset(n: int = 300, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    X, y = [], []
    reasons = list(REASON_RECOVERY_PRIORS.keys())
    for _ in range(n):
        reason = rng.choice(reasons)
        base_p = REASON_RECOVERY_PRIORS[reason]
        amount = rng.choice([49900, 79900, 150000, 500000, 2500000])
        hour = rng.choice([8, 9, 20, 21, 22, 14, 15])
        method = rng.choice(["upi", "card", "netbanking"])
        from app.diagnosis.engine import diagnosis_engine

        diag = diagnosis_engine.diagnose(reason, "customer", "payment_authentication")
        cust = CustomerContext(
            email="synthetic@test",
            contact=None,
            name="Synthetic",
            successful_payments=rng.randint(0, 15),
            subscription_months=rng.randint(0, 24),
            prior_failures_30d=rng.randint(0, 5),
            prior_failures_72h=rng.randint(0, 3),
            prior_recoveries=rng.randint(0, 4),
            nudges_sent_72h=rng.randint(0, 3),
            reminders_ignored=rng.randint(0, 3),
            checkout_visits=rng.randint(1, 10),
            engagement=rng.choice(["high", "medium", "low"]),
            persona="synthetic",
            razorpay_payments_found=0,
        )
        ch = diag.channels[0] if diag.channels else "email"
        vec = feature_vector(
            amount_paise=amount,
            error_reason=reason,
            diagnosis=diag,
            customer=cust,
            channel=ch,
            payment_method=method,
            event_hour=hour,
        )
        # Noisy label around base rate
        p = base_p + rng.uniform(-0.12, 0.12)
        p = max(0.05, min(0.95, p))
        label = 1 if rng.random() < p else 0
        X.append(vec)
        y.append(label)
    return np.vstack(X), np.array(y, dtype=np.int32)


def _load_training_data(db: Session) -> tuple[np.ndarray, np.ndarray, int]:
    from app.models.audit import AuditEvent
    from app.models.intervention import Intervention
    from app.diagnosis.engine import diagnosis_engine
    from app.services.customer_context import build_customer_context

    rows = (
        db.query(Intervention, AuditEvent)
        .join(AuditEvent, AuditEvent.id == Intervention.audit_event_id)
        .order_by(Intervention.created_at.desc())
        .limit(2000)
        .all()
    )

    X_list: list[np.ndarray] = []
    y_list: list[int] = []
    for iv, audit in rows:
        diag = diagnosis_engine.diagnose(audit.error_reason, audit.error_source, audit.error_step)
        customer = build_customer_context(
            db, email=audit.customer_email, contact=audit.customer_contact, exclude_audit_id=audit.id
        )
        channel = iv.channel or (diag.channels[0] if diag.channels else "email")
        hour = audit.created_at.hour if audit.created_at else None
        X_list.append(
            feature_vector(
                amount_paise=audit.amount_paise or iv.amount_at_risk_paise or 0,
                error_reason=audit.error_reason,
                diagnosis=diag,
                customer=customer,
                channel=channel,
                payment_method=audit.payment_method,
                event_hour=hour,
            )
        )
        y_list.append(1 if iv.status == "recovered" else 0)

    real_n = len(y_list)
    if real_n >= 100:
        # Chosen training strategy: enough seed-batch rows → train on 100% real DB outcomes
        X = np.vstack(X_list)
        y = np.array(y_list, dtype=np.int32)
    elif real_n < _MIN_TRAIN_SAMPLES:
        sx, sy = _synthetic_dataset(400 - real_n)
        if X_list:
            X = np.vstack([np.vstack(X_list), sx])
            y = np.concatenate([np.array(y_list, dtype=np.int32), sy])
        else:
            X, y = sx, sy
    else:
        X = np.vstack(X_list)
        y = np.array(y_list, dtype=np.int32)

    return X, y, real_n


def train_recovery_model(db: Session) -> dict[str, Any]:
    """Train (or retrain) logistic regression and persist to disk."""
    settings = get_settings()
    if not settings.ml_scoring_enabled:
        return {"trained": False, "reason": "ml_scoring_disabled"}

    X, y, real_samples = _load_training_data(db)
    if len(y) < 10:
        return {"trained": False, "reason": "insufficient_samples"}

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(max_iter=500, class_weight="balanced", random_state=42),
            ),
        ]
    )
    pipeline.fit(X, y)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples_total": int(len(y)),
        "samples_real": real_samples,
        "positive_rate": round(float(y.mean()) * 100, 1),
        "feature_dim": int(X.shape[1]),
        "model_type": "logistic_regression",
        "training_source": (
            "database_only" if real_samples >= 100
            else "database_hybrid" if real_samples >= _MIN_TRAIN_SAMPLES
            else "synthetic_bootstrap"
        ),
    }
    joblib.dump({"pipeline": pipeline, "meta": meta}, MODEL_PATH)
    _MODEL_CACHE["pipeline"] = pipeline
    _MODEL_CACHE["meta"] = meta
    logger.info("ML recovery model trained on %s samples (%s real)", meta["samples_total"], real_samples)
    return {"trained": True, **meta}


def _get_pipeline() -> tuple[Any | None, dict[str, Any]]:
    if _MODEL_CACHE["pipeline"] is not None:
        return _MODEL_CACHE["pipeline"], _MODEL_CACHE["meta"]
    if MODEL_PATH.exists():
        try:
            blob = joblib.load(MODEL_PATH)
            _MODEL_CACHE["pipeline"] = blob["pipeline"]
            _MODEL_CACHE["meta"] = blob.get("meta", {})
            return _MODEL_CACHE["pipeline"], _MODEL_CACHE["meta"]
        except Exception as exc:
            logger.warning("Failed to load ML model: %s", exc)
    return None, {}


def predict_recovery_probability(
    *,
    amount_paise: int,
    error_reason: str | None,
    diagnosis: DiagnosisResult,
    customer: CustomerContext,
    channel: str,
    payment_method: str | None = None,
    event_hour: int | None = None,
) -> float | None:
    settings = get_settings()
    if not settings.ml_scoring_enabled:
        return None

    pipeline, meta = _get_pipeline()
    if pipeline is None:
        return None

    vec = feature_vector(
        amount_paise=amount_paise,
        error_reason=error_reason,
        diagnosis=diagnosis,
        customer=customer,
        channel=channel,
        payment_method=payment_method,
        event_hour=event_hour,
    ).reshape(1, -1)
    prob = float(pipeline.predict_proba(vec)[0][1])
    return round(prob * 100, 1)


def ml_model_status() -> dict[str, Any]:
    _, meta = _get_pipeline()
    settings = get_settings()
    return {
        "enabled": settings.ml_scoring_enabled,
        "model_loaded": bool(meta),
        "blend_weight_ml": settings.ml_blend_weight,
        **meta,
    }
