"""Tests for classroom session business rules."""

import random
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.config import settings
from src.database import Base
from src.models import as_utc
from src.services import (
    BehaviorLogService,
    ClassroomService,
    DomainError,
    StudentService,
    is_late,
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


def test_picker_does_not_call_absent_students_once_attendance_started(
    db: Session,
) -> None:
    present = register(db, "S01", "An")
    register(db, "S02", "Binh")
    classroom_session = ClassroomService.start_session(db)
    ClassroomService.mark_present(db, classroom_session.id, present.id)

    assert ClassroomService.pick_random(db, classroom_session.id).student_id == (
        present.id
    )
    with pytest.raises(DomainError, match="có mặt đã được gọi"):
        ClassroomService.pick_random(db, classroom_session.id)


def test_picker_falls_back_to_roster_when_nobody_checked_in(db: Session) -> None:
    student = register(db, "S01", "An")
    classroom_session = ClassroomService.start_session(db)

    assert ClassroomService.pick_random(db, classroom_session.id).student_id == (
        student.id
    )


def test_mark_present_records_check_in_time_and_late_status(db: Session) -> None:
    student = register(db, "S01", "An")
    classroom_session = ClassroomService.start_session(db)
    started = as_utc(classroom_session.created_at)

    changed = ClassroomService.mark_present(
        db,
        classroom_session.id,
        student.id,
        now=started + timedelta(minutes=settings.late_after_minutes + 1),
    )

    state = ClassroomService.attendance(db, classroom_session.id)[0]
    assert changed is True
    assert state.attendance_source == "AUTO"
    assert is_late(state, classroom_session)
    assert ClassroomService.mark_present(db, classroom_session.id, student.id) is False


def test_camera_never_overrides_manual_absence(db: Session) -> None:
    student = register(db, "S01", "An")
    classroom_session = ClassroomService.start_session(db)

    ClassroomService.set_attendance(
        db, classroom_session.id, student.id, present=False, note="Có phép"
    )
    changed = ClassroomService.mark_present(db, classroom_session.id, student.id)

    state = ClassroomService.attendance(db, classroom_session.id)[0]
    assert changed is False
    assert state.is_present is False
    assert state.note == "Có phép"


def test_manual_attendance_and_summary(db: Session) -> None:
    first = register(db, "S01", "An")
    register(db, "S02", "Binh")
    classroom_session = ClassroomService.start_session(db, "Toán 7A")

    ClassroomService.set_attendance(db, classroom_session.id, first.id, present=True)
    summary = ClassroomService.summary(db, classroom_session)

    assert classroom_session.title == "Toán 7A"
    assert summary.to_dict() == {
        "total": 2,
        "present": 1,
        "late": 0,
        "absent": 1,
        "called": 0,
        "manual": 1,
        "behaviors": 0,
    }


def test_finished_session_stays_readable_for_reports(db: Session) -> None:
    register(db, "S01", "An")
    classroom_session = ClassroomService.start_session(db)
    ClassroomService.finish_session(db, classroom_session.id)

    assert ClassroomService.get_session(db, classroom_session.id).status == "FINISHED"
    assert len(ClassroomService.attendance(db, classroom_session.id)) == 1
    assert ClassroomService.list_sessions(db)[0].id == classroom_session.id


def test_delete_student_keeps_anonymous_behavior_logs(db: Session) -> None:
    class RecordingStorage:
        def __init__(self) -> None:
            self.avatars: list[str] = []

        def delete_avatar(self, name: str) -> None:
            self.avatars.append(name)

    student = register(db, "S01", "An")
    classroom_session = ClassroomService.start_session(db)
    BehaviorLogService.create(
        db, classroom_session.id, "SLEEPING", "a.jpg", student_id=student.id
    )
    storage = RecordingStorage()

    StudentService.delete(db, student.id, storage)

    assert StudentService.list_all(db) == []
    assert storage.avatars == ["S01.enc"]
    assert BehaviorLogService.list_recent(db)[0].student_id is None
    assert ClassroomService.attendance(db, classroom_session.id) == []


def test_shared_snapshot_is_kept_until_last_log_is_deleted(db: Session) -> None:
    class RecordingStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_snapshot(self, name: str) -> None:
            self.deleted.append(name)

    classroom_session = ClassroomService.start_session(db)
    first = BehaviorLogService.create(db, classroom_session.id, "SLEEPING", "s.jpg")
    BehaviorLogService.create(db, classroom_session.id, "CHEATING", "s.jpg")
    storage = RecordingStorage()

    BehaviorLogService._delete_logs(db, storage, [first])
    assert storage.deleted == []
    BehaviorLogService.clear_all(db, storage)
    assert storage.deleted == ["s.jpg"]


def test_reset_called_keeps_call_history_for_reports(db: Session) -> None:
    student = register(db, "S01", "An")
    classroom_session = ClassroomService.start_session(db)
    ClassroomService.set_attendance(db, classroom_session.id, student.id, present=True)
    ClassroomService.pick_random(db, classroom_session.id)

    ClassroomService.reset_called(db, classroom_session.id)

    state = ClassroomService.attendance(db, classroom_session.id)[0]
    assert state.is_called is False
    assert state.called_at is not None
    assert ClassroomService.summary(db, classroom_session).called == 1


def test_start_session_supports_custom_late_after_minutes(db: Session) -> None:
    session = ClassroomService.start_session(db, title="Kiểm tra", late_after_minutes=0)
    assert session.late_after_minutes == 0
    ClassroomService.finish_session(db, session.id)

    with pytest.raises(DomainError, match="đi muộn"):
        ClassroomService.start_session(db, late_after_minutes=-1)
    with pytest.raises(DomainError, match="đi muộn"):
        ClassroomService.start_session(db, late_after_minutes=181)


def test_behavior_log_delete_one_keeps_shared_snapshot_until_last_log(
    db: Session,
) -> None:
    class RecordingStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete_snapshot(self, name: str) -> None:
            self.deleted.append(name)

    classroom_session = ClassroomService.start_session(db)
    first = BehaviorLogService.create(db, classroom_session.id, "SLEEPING", "s.jpg")
    second = BehaviorLogService.create(db, classroom_session.id, "CHEATING", "s.jpg")
    storage = RecordingStorage()

    BehaviorLogService.delete_one(db, first.id, storage)
    assert storage.deleted == []

    BehaviorLogService.delete_one(db, second.id, storage)
    assert storage.deleted == ["s.jpg"]
