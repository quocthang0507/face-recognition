"""SQLAlchemy database connection and session helpers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# Columns added after the first release. ``create_all`` never alters existing
# tables, so older classroom.db files are upgraded in place on startup.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "sessions": {"title": "VARCHAR(120)"},
    "session_students": {
        "checked_in_at": "DATETIME",
        "attendance_source": "VARCHAR(10)",
        "note": "VARCHAR(200)",
    },
}


def apply_lightweight_migrations(bind: Engine) -> list[str]:
    """Add missing nullable columns to tables created by an older version."""

    inspector = inspect(bind)
    added: list[str] = []
    with bind.begin() as connection:
        for table, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl_type in columns.items():
                if name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")
                    )
                    added.append(f"{table}.{name}")
    return added


def create_tables() -> None:
    """Create application tables if they are missing and upgrade old schemas."""

    from . import models  # noqa: F401

    settings.ensure_directories()
    Base.metadata.create_all(bind=engine)
    apply_lightweight_migrations(engine)


def get_db() -> Generator[Session, None, None]:
    """Yield one database session for a FastAPI request."""

    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
