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


def serialize_embedding(embedding: Sequence[float]) -> str:
    """Serialize a numeric embedding for storage."""

    if not embedding:
        raise DomainError("Face embedding cannot be empty")
    return json.dumps([float(value) for value in embedding], separators=(",", ":"))


def deserialize_embedding(raw_embedding: str) -> list[float]:
    """Load a numeric embedding from storage."""

    values = json.loads(raw_embedding)
    if not isinstance(values, list) or not values:
        raise DomainError("Stored face embedding is invalid")
    return [float(value) for value in values]


class StudentService:
    """Manage registered students."""

    @staticmethod
    def register(
        db: Session,
        student_code: str,
        fullname: str,
        embedding: Sequence[float],
        avatar_path: str,
    ) -> Student:
        """Register one student after validating unique identity fields."""

        normalized_code = student_code.strip()
        normalized_name = fullname.strip()
        if not normalized_code or len(normalized_code) > 20:
            raise DomainError("Student code must contain 1-20 characters")
        if not normalized_name or len(normalized_name) > 100:
            raise DomainError("Full name must contain 1-100 characters")
        existing = db.scalar(
            select(Student).where(Student.student_code == normalized_code)
        )
        if existing:
            raise DomainError("Student code already exists")
        student = Student(
            student_code=normalized_code,
            fullname=normalized_name,
            embedding=serialize_embedding(embedding),
            avatar_path=avatar_path,
        )
        db.add(student)
        db.commit()
        db.refresh(student)
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
        if active:
            raise DomainError("A classroom session is already active")
        classroom_session = ClassroomSession(status="ACTIVE")
        db.add(classroom_session)
        db.flush()
        for student in db.scalars(select(Student)):
            db.add(
                SessionStudent(session_id=classroom_session.id, student_id=student.id)
            )
        db.commit()
        return classroom_session

    @staticmethod
    def get_active_session(db: Session) -> ClassroomSession | None:
        """Return the currently active lesson, if any."""

        return db.scalar(
            select(ClassroomSession)
            .where(ClassroomSession.status == "ACTIVE")
            .order_by(ClassroomSession.created_at.desc())
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
        """Mark a recognized student as present in an active lesson."""

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
        """Pick one present student who has not yet been called."""

        ClassroomService._active_by_id(db, session_id)
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
        if not candidates:
            raise DomainError("No uncalled present students remain")
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
            raise DomainError("Active classroom session was not found")
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
