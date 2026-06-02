"""Business services for students, lessons and behavior audit logs."""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from .models import BehaviorLog, ClassroomSession, SessionStudent, Student, utc_now
from .storage import PrivateStorage


class DomainError(ValueError):
    """Raised when a requested business operation is not valid."""


def serialize_embedding(embedding: Sequence[float] | None) -> str:
    """Serialize a numeric embedding for storage."""

    if not embedding:
        return "[]"
    return json.dumps([float(value) for value in embedding], separators=(",", ":"))


def deserialize_embedding(raw_embedding: str) -> list[float]:
    """Load a numeric embedding from storage."""

    if not raw_embedding or raw_embedding == "[]":
        return []
    try:
        values = json.loads(raw_embedding)
        if not isinstance(values, list) or not values:
            return []
        return [float(value) for value in values]
    except Exception:
        return []


class StudentService:
    """Manage registered students."""

    @staticmethod
    def register(
        db: Session,
        student_code: str,
        fullname: str,
        embedding: Sequence[float] | None = None,
        avatar_path: str | None = None,
    ) -> Student:
        """Register one student after validating unique identity fields."""

        normalized_code = student_code.strip()
        normalized_name = fullname.strip()
        if not normalized_code or len(normalized_code) > 20:
            raise DomainError("Mã học sinh phải có từ 1-20 ký tự")
        if not normalized_name or len(normalized_name) > 100:
            raise DomainError("Họ và tên phải có từ 1-100 ký tự")
        existing = db.scalar(
            select(Student).where(Student.student_code == normalized_code)
        )
        if existing:
            raise DomainError("Mã học sinh đã tồn tại")
        student = Student(
            student_code=normalized_code,
            fullname=normalized_name,
            embedding=serialize_embedding(embedding),
            avatar_path=avatar_path,
        )
        db.add(student)
        db.commit()
        db.refresh(student)

        # Enroll in the currently active session if one exists
        active_session = db.scalar(
            select(ClassroomSession).where(ClassroomSession.status == "ACTIVE")
        )
        if active_session:
            db.add(
                SessionStudent(
                    session_id=active_session.id,
                    student_id=student.id,
                    is_present=False,
                    is_called=False,
                )
            )
            db.commit()

        return student

    @staticmethod
    def list_all(db: Session) -> list[Student]:
        """Return registered students ordered by full name."""

        return list(db.scalars(select(Student).order_by(Student.fullname)))


class ClassroomService:
    """Manage lesson lifecycle, attendance and random student calls."""

    @staticmethod
    def start_session(db: Session) -> ClassroomSession:
        """Start a lesson and initialize attendance state for all students."""

        active = ClassroomService.get_active_session(db)
        if active is not None:
            raise DomainError("Có phiên học đang hoạt động")
        session = ClassroomSession(status="ACTIVE")
        db.add(session)
        db.flush()

        students = db.scalars(select(Student)).all()
        for student in students:
            db.add(
                SessionStudent(
                    session_id=session.id,
                    student_id=student.id,
                    is_present=False,
                    is_called=False,
                )
            )
        db.commit()
        return session

    @staticmethod
    def get_active_session(db: Session) -> ClassroomSession | None:
        """Return the current active lesson if any."""

        return db.scalar(
            select(ClassroomSession).where(ClassroomSession.status == "ACTIVE")
        )

    @staticmethod
    def finish_session(db: Session, session_id: int) -> ClassroomSession:
        """Finish an active lesson."""

        classroom_session = ClassroomService._active_by_id(db, session_id)
        classroom_session.status = "FINISHED"
        classroom_session.finished_at = utc_now()
        db.commit()
        return classroom_session

    @staticmethod
    def mark_present(db: Session, session_id: int, student_id: int) -> None:
        """Mark one student present in the active lesson."""

        ClassroomService._active_by_id(db, session_id)
        state = db.scalar(
            select(SessionStudent).where(
                SessionStudent.session_id == session_id,
                SessionStudent.student_id == student_id,
            )
        )
        if state is None:
            state = SessionStudent(session_id=session_id, student_id=student_id)
            db.add(state)
        if not state.is_present:
            state.is_present = True
            db.commit()

    @staticmethod
    def pick_random(
        db: Session,
        session_id: int,
        chooser: random.Random | None = None,
    ) -> SessionStudent:
        """Pick one present student who has not yet been called, falling back to any uncalled student."""

        ClassroomService._active_by_id(db, session_id)
        # Try to find present uncalled students first
        candidates = list(
            db.scalars(
                select(SessionStudent)
                .options(joinedload(SessionStudent.student))
                .where(
                    SessionStudent.session_id == session_id,
                    SessionStudent.is_present.is_(True),
                    SessionStudent.is_called.is_(False),
                )
            )
        )
        # Fallback to all uncalled students in the session if no present uncalled students
        if not candidates:
            candidates = list(
                db.scalars(
                    select(SessionStudent)
                    .options(joinedload(SessionStudent.student))
                    .where(
                        SessionStudent.session_id == session_id,
                        SessionStudent.is_called.is_(False),
                    )
                )
            )
        if not candidates:
            raise DomainError("Không còn học sinh nào chưa được gọi")
        selected = (chooser or random).choice(candidates)
        selected.is_called = True
        selected.called_at = utc_now()
        db.commit()
        return selected

    @staticmethod
    def reset_called(db: Session, session_id: int) -> None:
        """Reset the called state for all students in an active lesson."""

        ClassroomService._active_by_id(db, session_id)
        states = db.scalars(
            select(SessionStudent).where(SessionStudent.session_id == session_id)
        )
        for state in states:
            state.is_called = False
            state.called_at = None
        db.commit()

    @staticmethod
    def attendance(db: Session, session_id: int) -> list[SessionStudent]:
        """Return attendance state and student data for one lesson."""

        return list(
            db.scalars(
                select(SessionStudent)
                .options(joinedload(SessionStudent.student))
                .where(SessionStudent.session_id == session_id)
                .order_by(SessionStudent.id)
            )
        )

    @staticmethod
    def _active_by_id(db: Session, session_id: int) -> ClassroomSession:
        classroom_session = db.get(ClassroomSession, session_id)
        if classroom_session is None or classroom_session.status != "ACTIVE":
            raise DomainError("Không tìm thấy phiên học đang hoạt động")
        return classroom_session


class BehaviorLogService:
    """Write and prune the behavior audit trail."""

    @staticmethod
    def create(
        db: Session,
        session_id: int,
        behavior_type: str,
        snapshot_path: str,
        student_id: int | None = None,
    ) -> BehaviorLog:
        """Persist one detected behavior event."""

        log = BehaviorLog(
            session_id=session_id,
            student_id=student_id,
            behavior_type=behavior_type,
            snapshot_path=snapshot_path,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    @staticmethod
    def list_recent(db: Session, limit: int = 50) -> list[BehaviorLog]:
        """Return the newest behavior events."""

        return list(
            db.scalars(
                select(BehaviorLog)
                .options(joinedload(BehaviorLog.student))
                .order_by(BehaviorLog.timestamp.desc())
                .limit(limit)
            )
        )

    @staticmethod
    def cleanup_old(
        db: Session,
        storage: PrivateStorage,
        retention_days: int,
        now: datetime | None = None,
    ) -> int:
        """Delete behavior logs and snapshots older than the retention window."""

        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
        logs = list(
            db.scalars(select(BehaviorLog).where(BehaviorLog.timestamp < cutoff))
        )
        return BehaviorLogService._delete_logs(db, storage, logs)

    @staticmethod
    def clear_all(db: Session, storage: PrivateStorage) -> int:
        """Delete every behavior log and its evidence snapshot."""

        logs = list(db.scalars(select(BehaviorLog)))
        return BehaviorLogService._delete_logs(db, storage, logs)

    @staticmethod
    def _delete_logs(
        db: Session, storage: PrivateStorage, logs: Sequence[BehaviorLog]
    ) -> int:
        """Delete selected behavior logs and any snapshots still on disk."""

        for log in logs:
            try:
                storage.delete_snapshot(log.snapshot_path)
            except FileNotFoundError:
                pass
        if logs:
            db.execute(
                delete(BehaviorLog).where(BehaviorLog.id.in_([log.id for log in logs]))
            )
            db.commit()
        return len(logs)
