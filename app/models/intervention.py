import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Intervention(Base):
    __tablename__ = "interventions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_event_id: Mapped[str] = mapped_column(String(36), ForeignKey("audit_events.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_link_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_link_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    link_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="sent")
    amount_at_risk_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_recovered_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovered_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
