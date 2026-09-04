from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()
db_path = settings.database_url.replace("sqlite:///", "")
Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_columns() -> None:
    """Lightweight SQLite migrations for columns added after first deploy."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(interventions)"))}
        if "link_error" not in cols:
            conn.execute(text("ALTER TABLE interventions ADD COLUMN link_error VARCHAR(512)"))

        pcols = {row[1] for row in conn.execute(text("PRAGMA table_info(promises_to_pay)"))}
        for col, typedef in [
            ("audit_event_id", "VARCHAR(36)"),
            ("intervention_id", "VARCHAR(36)"),
            ("parsed_by", "VARCHAR(32)"),
            ("source_channel", "VARCHAR(32)"),
        ]:
            if col not in pcols:
                conn.execute(text(f"ALTER TABLE promises_to_pay ADD COLUMN {col} {typedef}"))

        acols = {row[1] for row in conn.execute(text("PRAGMA table_info(audit_events)"))}
        for col, typedef in [
            ("recovery_score", "INTEGER"),
            ("recovery_score_json", "TEXT"),
        ]:
            if col not in acols:
                conn.execute(text(f"ALTER TABLE audit_events ADD COLUMN {col} {typedef}"))


def init_db() -> None:
    from app.models import audit, escalation, intervention, promise, scheduled_action  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_columns()
