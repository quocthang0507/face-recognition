"""Tests for recomputing stored face embeddings after a pipeline change."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.config import settings
from src.database import Base
from src.reembed import reembed_outdated
from src.services import StudentService, deserialize_embedding


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


class AvatarStorage:
    def __init__(self, missing: bool = False) -> None:
        self.missing = missing

    def read_avatar(self, name: str) -> bytes:
        if self.missing:
            raise FileNotFoundError(name)
        return b"jpeg"


def outdated_student(db: Session):
    student = StudentService.register(db, "S01", "An", [1.0, 0.0], "a.enc")
    student.embedding_model = "Facenet:opencv"
    db.commit()
    return student


def test_outdated_embedding_is_recomputed_from_the_stored_avatar(db: Session) -> None:
    student = outdated_student(db)

    updated, failed = reembed_outdated(db, AvatarStorage(), lambda content: [0.0, 1.0])

    db.refresh(student)
    assert (updated, failed) == (1, 0)
    assert deserialize_embedding(student.embedding) == [0.0, 1.0]
    assert student.embedding_model == settings.embedding_model_id


def test_current_embeddings_are_left_untouched(db: Session) -> None:
    StudentService.register(db, "S01", "An", [1.0, 0.0], "a.enc")

    assert reembed_outdated(db, AvatarStorage(), lambda content: [0.0, 1.0]) == (0, 0)


def test_missing_avatar_keeps_the_old_embedding(db: Session) -> None:
    student = outdated_student(db)

    updated, failed = reembed_outdated(
        db, AvatarStorage(missing=True), lambda content: [0.0, 1.0]
    )

    db.refresh(student)
    assert (updated, failed) == (0, 1)
    assert deserialize_embedding(student.embedding) == [1.0, 0.0]
