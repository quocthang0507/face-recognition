"""Alembic environment shared by the CLI and application startup."""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from src import models  # noqa: F401 - registers tables on Base.metadata
from src.database import Base, engine


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite cannot alter most column properties
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# Application startup passes its own connection; the CLI opens one.
provided_connection = context.config.attributes.get("connection")
if provided_connection is not None:
    run_migrations(provided_connection)
else:
    with engine.begin() as cli_connection:
        run_migrations(cli_connection)
