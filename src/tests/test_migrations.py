"""Tests for upgrading classroom.db at application startup."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from src import migrate
from src import models  # noqa: F401
from src.database import Base
from src.migrate import MigrationError, head_revision, upgrade_database

COLUMNS_ADDED_AFTER_FIRST_RELEASE = {
    "students": ["embedding_model"],
    "sessions": ["title"],
    "session_students": ["checked_in_at", "attendance_source", "note"],
}
INSERT_STUDENT = text(
    "INSERT INTO students (student_code, fullname, embedding, created_at) "
    "VALUES ('HS001', 'Nguyễn Văn An', '[1.0]', '2026-01-01 00:00:00')"
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "classroom.db"


@pytest.fixture
def engine(db_path: Path) -> Iterator[Engine]:
    instance = create_engine(f"sqlite:///{db_path}")
    yield instance
    instance.dispose()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def columns(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def backups(db_path: Path) -> list[Path]:
    return sorted(db_path.parent.glob("classroom.db.bak-*"))


def create_database_without_version(engine: Engine) -> None:
    """A database written by a release that had no Alembic."""

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        connection.execute(INSERT_STUDENT)


def create_first_release_database(engine: Engine) -> None:
    """A version-less database still missing the columns added later."""

    create_database_without_version(engine)
    with engine.begin() as connection:
        for table, names in COLUMNS_ADDED_AFTER_FIRST_RELEASE.items():
            for name in names:
                connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {name}"))


def student_names(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(connection.scalars(text("SELECT fullname FROM students")))


def test_new_database_gets_schema_and_version(engine: Engine) -> None:
    upgrade_database(engine)

    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    assert current_revision(engine) == head_revision()


def test_new_database_is_not_backed_up(engine: Engine, db_path: Path) -> None:
    upgrade_database(engine)

    assert backups(db_path) == []


def test_first_release_database_gains_missing_columns(engine: Engine) -> None:
    create_first_release_database(engine)

    upgrade_database(engine)

    for table, names in COLUMNS_ADDED_AFTER_FIRST_RELEASE.items():
        assert set(names) <= columns(engine, table)
    assert current_revision(engine) == head_revision()


def test_first_release_database_keeps_its_data(engine: Engine) -> None:
    create_first_release_database(engine)

    upgrade_database(engine)

    assert student_names(engine) == ["Nguyễn Văn An"]


def test_unversioned_current_database_is_adopted(engine: Engine) -> None:
    create_database_without_version(engine)

    upgrade_database(engine)

    assert current_revision(engine) == head_revision()
    assert student_names(engine) == ["Nguyễn Văn An"]


def test_upgrade_leaves_readable_backup_of_old_data(
    engine: Engine, db_path: Path
) -> None:
    create_first_release_database(engine)

    upgrade_database(engine)

    [backup] = backups(db_path)
    with sqlite3.connect(backup) as copy:
        rows = copy.execute("SELECT fullname FROM students").fetchall()
        column_names = {row[1] for row in copy.execute("PRAGMA table_info(sessions)")}
    assert rows == [("Nguyễn Văn An",)]
    assert "title" not in column_names


def test_up_to_date_database_is_left_alone(engine: Engine, db_path: Path) -> None:
    upgrade_database(engine)
    with engine.begin() as connection:
        connection.execute(INSERT_STUDENT)

    upgrade_database(engine)

    assert student_names(engine) == ["Nguyễn Văn An"]
    assert backups(db_path) == []


def test_models_match_migrations(engine: Engine) -> None:
    upgrade_database(engine)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_database_missing_a_table_is_refused(engine: Engine) -> None:
    create_database_without_version(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE behavior_logs"))

    with pytest.raises(MigrationError, match="behavior_logs"):
        upgrade_database(engine)


def test_failed_upgrade_names_the_backup(
    engine: Engine, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_first_release_database(engine)

    def fail(*_args, **_kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(migrate.command, "upgrade", fail)

    with pytest.raises(MigrationError, match=r"classroom\.db\.bak-"):
        upgrade_database(engine)
    assert len(backups(db_path)) == 1


def test_retry_after_failure_keeps_the_original_backup(engine: Engine) -> None:
    create_first_release_database(engine)
    backup = migrate.backup_database(engine, "test")
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM students"))

    assert migrate.backup_database(engine, "test") == backup
    with sqlite3.connect(backup) as copy:
        assert copy.execute("SELECT COUNT(*) FROM students").fetchone() == (1,)


def test_interrupted_backup_is_not_mistaken_for_a_good_one(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_first_release_database(engine)
    real_copy = migrate._copy_sqlite

    def interrupted(_source: Path, target: Path) -> None:
        target.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(migrate, "_copy_sqlite", interrupted)
    with pytest.raises(OSError):
        migrate.backup_database(engine, "test")
    monkeypatch.setattr(migrate, "_copy_sqlite", real_copy)

    backup = migrate.backup_database(engine, "test")

    with sqlite3.connect(backup) as copy:
        assert copy.execute("SELECT COUNT(*) FROM students").fetchone() == (1,)


def test_adopted_first_release_database_matches_models(engine: Engine) -> None:
    create_first_release_database(engine)

    upgrade_database(engine)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []
