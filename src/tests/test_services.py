"""Tests for classroom session business rules."""

import random

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database import Base
from src.services import (
    BehaviorLogService,
    ClassroomService,
    DomainError,
    StudentService,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def register(db: Session, code: str, name: str):
    return StudentService.register(db, code, name, [1.0, 0.0], f"{code}.enc")


def test_session_picker_never_calls_present_student_twice(db: Session) -> None:
    first = register(db, "S01", "An")
    second = register(db, "S02", "Binh")
    classroom_session = ClassroomService.start_session(db)
    ClassroomService.mark_present(db, classroom_session.id, first.id)
    ClassroomService.mark_present(db, classroom_session.id, second.id)

    selected = {
        ClassroomService.pick_random(
            db, classroom_session.id, random.Random(seed)
        ).student_id
        for seed in (1, 2)
    }

    assert selected == {first.id, second.id}
    with pytest.raises(DomainError):
        ClassroomService.pick_random(db, classroom_session.id)


def test_reset_called_opens_a_new_picker_round(db: Session) -> None:
    student = register(db, "S01", "An")
    classroom_session = ClassroomService.start_session(db)
    ClassroomService.mark_present(db, classroom_session.id, student.id)
    ClassroomService.pick_random(db, classroom_session.id)

    ClassroomService.reset_called(db, classroom_session.id)

    assert (
        ClassroomService.pick_random(db, classroom_session.id).student_id == student.id
    )


def test_only_one_classroom_session_can_be_active(db: Session) -> None:
    ClassroomService.start_session(db)

    with pytest.raises(DomainError):
        ClassroomService.start_session(db)


def test_clear_behavior_logs_deletes_database_rows_and_snapshots(db: Session) -> None:
    class RecordingStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_snapshot(self, name: str) -> None:
            self.deleted.append(name)

    classroom_session = ClassroomService.start_session(db)
    BehaviorLogService.create(db, classroom_session.id, "SLEEPING", "first.jpg")
    BehaviorLogService.create(db, classroom_session.id, "CHEATING", "second.jpg")
    storage = RecordingStorage()

    deleted = BehaviorLogService.clear_all(db, storage)

    assert deleted == 2
    assert storage.deleted == ["first.jpg", "second.jpg"]
    assert BehaviorLogService.list_recent(db) == []
