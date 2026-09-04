"""Human escalation queue for high-value recovery cases."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base

HUMAN_ESCALATION_MIN_PAISE = 2_500_000  # ₹25,000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EscalationCase(Base):
    __tablename__ = "escalation_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("audit_events.id"), index=True)
    intervention_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("interventions.id"), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | assigned | resolved
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def maybe_queue_escalation(
    db: Session,
    *,
    audit_event_id: str,
    intervention_id: str | None,
    customer_email: str | None,
    amount_paise: int,
    recovery_score: int,
    error_reason: str | None,
) -> EscalationCase | None:
    if amount_paise < HUMAN_ESCALATION_MIN_PAISE or recovery_score < 55:
        return None
    existing = (
        db.query(EscalationCase)
        .filter(EscalationCase.audit_event_id == audit_event_id, EscalationCase.status == "pending")
        .first()
    )
    if existing:
        return existing
    case = EscalationCase(
        audit_event_id=audit_event_id,
        intervention_id=intervention_id,
        customer_email=customer_email,
        amount_paise=amount_paise,
        recovery_score=recovery_score,
        reason=error_reason,
        status="pending",
        note="High-value case — assign to account manager after automated nudges",
    )
    db.add(case)
    db.flush()
    return case


def resolve_escalations_for_audit(db: Session, audit_event_id: str, *, note: str | None = None) -> int:
    """Mark pending escalations resolved when a case is paid or closed."""
    from app.models.audit import AuditEvent

    rows = (
        db.query(EscalationCase)
        .filter(EscalationCase.audit_event_id == audit_event_id, EscalationCase.status == "pending")
        .all()
    )
    for row in rows:
        row.status = "resolved"
        if note:
            row.note = note
    return len(rows)


def resolve_stale_escalations(db: Session) -> int:
    """Auto-close queue rows that are orphans or already recovered."""
    from app.models.audit import AuditEvent
    from app.models.intervention import Intervention

    resolved = 0
    pending = db.query(EscalationCase).filter(EscalationCase.status == "pending").all()
    for row in pending:
        audit = db.get(AuditEvent, row.audit_event_id) if row.audit_event_id else None
        iv = db.get(Intervention, row.intervention_id) if row.intervention_id else None

        if audit is None:
            row.status = "resolved"
            row.note = (row.note or "") + " · auto-closed (case removed)"
            resolved += 1
            continue

        if audit.status == "recovered":
            row.status = "resolved"
            row.note = (row.note or "") + " · auto-resolved (payment recovered)"
            resolved += 1
            continue

        if iv and (iv.status == "recovered" or iv.amount_recovered_paise):
            row.status = "resolved"
            row.note = (row.note or "") + " · auto-resolved (intervention paid)"
            resolved += 1

    if resolved:
        db.commit()
    return resolved


def list_escalations(db: Session, *, limit: int = 20) -> list[EscalationCase]:
    resolve_stale_escalations(db)
    rows = (
        db.query(EscalationCase)
        .filter(EscalationCase.status == "pending")
        .order_by(EscalationCase.amount_paise.desc())
        .limit(limit * 3)
        .all()
    )
    seen: set[str] = set()
    unique: list[EscalationCase] = []
    for row in rows:
        if row.audit_event_id in seen:
            continue
        seen.add(row.audit_event_id)
        unique.append(row)
        if len(unique) >= limit:
            break
    return unique
