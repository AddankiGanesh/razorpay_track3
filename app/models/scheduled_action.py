"""Scheduled recovery actions — reminder emails on promise date, etc."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledAction(Base):
    __tablename__ = "scheduled_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    intervention_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("interventions.id"), index=True, nullable=True
    )
    audit_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("audit_events.id"), index=True, nullable=True
    )
    promise_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("promises_to_pay.id"), index=True, nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(64), default="reminder_email")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | sent | cancelled
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
