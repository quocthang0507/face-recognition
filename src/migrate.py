"""Bring the database to the current schema when the application starts."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from .config import BASE_DIR

logger = logging.getLogger(__name__)

BASELINE_REVISION = "0001"
_BASELINE_TABLES = ("students", "sessions", "session_students", "behavior_logs")
# Columns that releases before Alembic added on startup. A database that stopped
# at an older release may still lack them when it is adopted at the baseline.
_PRE_ALEMBIC_COLUMNS: dict[str, dict[str, str]] = {
    "students": {"embedding_model": "VARCHAR(40)"},
    "sessions": {"title": "VARCHAR(120)"},
    "session_students": {
        "checked_in_at": "DATETIME",
        "attendance_source": "VARCHAR(10)",
        "note": "VARCHAR(200)",
    },
}


class MigrationError(RuntimeError):
    """The database could not be brought to the current schema."""


def _config(connection: Connection | None = None) -> Config:
    config = Config()
    location = str(BASE_DIR / "migrations").replace("%", "%%")
    config.set_main_option("script_location", location)
    config.attributes["connection"] = connection
    return config


def head_revision() -> str:
    """Return the newest schema revision shipped with this release."""

    return ScriptDirectory.from_config(_config()).get_current_head()


def sqlite_file(bind: Engine) -> Path | None:
    database = bind.url.database
    if (
        bind.url.get_backend_name() != "sqlite"
        or not database
        or database == ":memory:"
    ):
        return None
    return Path(database)


def _copy_sqlite(source_path: Path, target_path: Path) -> None:
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def backup_database(bind: Engine, label: str) -> Path | None:
    """Copy a SQLite file, keeping any earlier copy made for the same label.

    SQLite's backup API is used because recent writes may still be in the WAL.
    An existing copy is kept: after a failed upgrade it is the only intact one.
    """

    source_path = sqlite_file(bind)
    if source_path is None:
        return None
    target_path = source_path.with_name(f"{source_path.name}.bak-{label}")
    if target_path.exists():
        return target_path
    partial_path = target_path.with_name(f"{target_path.name}.partial")
    partial_path.unlink(missing_ok=True)
    _copy_sqlite(source_path, partial_path)
    partial_path.replace(target_path)  # only a complete copy gets the final name
    logger.info("Đã sao lưu CSDL trước khi nâng cấp: %s", target_path)
    return target_path


def purge_expired_backups(
    database: Path, retention_days: int, now: float | None = None
) -> int:
    """Delete upgrade backups past the retention window; they hold face data."""

    cutoff = (time.time() if now is None else now) - retention_days * 86400
    expired = [
        path
        for path in database.parent.glob(f"{database.name}.bak-*")
        if path.stat().st_mtime < cutoff
    ]
    for path in expired:
        path.unlink()
    return len(expired)


def _add_pre_alembic_columns(connection: Connection) -> None:
    inspector = inspect(connection)
    for table, added_columns in _PRE_ALEMBIC_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl_type in added_columns.items():
            if name not in existing:
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")
                )


def upgrade_database(bind: Engine) -> None:
    """Create or upgrade the schema, backing up existing data first."""

    head = head_revision()
    with bind.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        tables = set(inspect(connection).get_table_names())
    if current == head:
        return

    adopting = current is None and bool(tables.intersection(_BASELINE_TABLES))
    if adopting:
        missing = sorted(set(_BASELINE_TABLES) - tables)
        if missing:
            raise MigrationError(
                f"CSDL hiện có thiếu bảng {', '.join(missing)}, không thể nâng cấp."
            )

    backup = backup_database(bind, head) if adopting or current else None
    try:
        with bind.begin() as connection:
            config = _config(connection)
            if adopting:
                _add_pre_alembic_columns(connection)
                command.stamp(config, BASELINE_REVISION)
            command.upgrade(config, "head")
    except Exception as exc:
        location = f" Bản sao trước khi nâng cấp: {backup}." if backup else ""
        raise MigrationError(f"Nâng cấp CSDL thất bại.{location}") from exc
