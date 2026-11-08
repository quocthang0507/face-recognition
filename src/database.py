"""SQLAlchemy database connection and session helpers."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(settings.database_url, connect_args=connect_args)

_is_sqlite_file = settings.database_url.startswith("sqlite") and (
    ":memory:" not in settings.database_url
)
if _is_sqlite_file:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        """WAL lets the camera pipeline write while the dashboard reads."""

        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_tables() -> None:
    """Create application tables if they are missing and upgrade old schemas."""

    from .migrate import upgrade_database

    settings.ensure_directories()
    upgrade_database(engine)


def get_db() -> Generator[Session, None, None]:
    """Yield one database session for a FastAPI request."""

    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()
