"""Shared fixtures for tests that use the API against an in-memory database."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Set before importing the app so tests never create a key in src/data.
os.environ.setdefault("FACE_APP_TOKEN_SECRET", "unit-test-token-secret")

from src.database import Base, get_db  # noqa: E402


@pytest.fixture
def session_factory() -> Iterator[sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def client(session_factory: sessionmaker) -> Iterator[TestClient]:
    from src import main

    def override() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = override
    main.login_throttle._failures.clear()
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
