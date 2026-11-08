"""Business services for students, lessons and behavior audit logs."""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, joinedload

from .config import settings
from .models import (
    BehaviorLog,
    ClassroomSession,
    SessionStudent,
    Student,
    as_utc,
    utc_now,
)
from .storage import PrivateStorage

ATTENDANCE_AUTO = "AUTO"
ATTENDANCE_MANUAL = "MANUAL"


class DomainError(ValueError):
    """Raised when a requested business operation is not valid."""


class NotFoundError(DomainError):
    """Raised when a referenced record does not exist."""


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


def has_face_embedding(student: Student) -> bool:
    """Whether the student can be recognized by the camera."""

    return bool(deserialize_embedding(student.embedding))


def is_late(state: SessionStudent, classroom_session: ClassroomSession) -> bool:
    """A student is late when the first check-in exceeds the grace period."""

    checked_in = as_utc(state.checked_in_at)
    started = as_utc(classroom_session.created_at)
    if not state.is_present or checked_in is None or started is None:
        return False
    return checked_in - started > timedelta(minutes=settings.late_after_minutes)


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
        normalized_name = " ".join(fullname.split())
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
        db.flush()

        # Enroll in the currently active session if one exists
        active_session = ClassroomService.get_active_session(db)
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
        db.refresh(student)
        return student

    @staticmethod
    def get(db: Session, student_id: int) -> Student:
        """Return one student or raise when it does not exist."""

        student = db.get(Student, student_id)
        if student is None:
            raise NotFoundError("Không tìm thấy học sinh")
        return student

    @staticmethod
    def update_face(
        db: Session,
        student_id: int,
        embedding: Sequence[float],
        avatar_path: str | None,
    ) -> tuple[Student, str | None]:
        """Replace a student's face sample and return the previous avatar name."""

        student = StudentService.get(db, student_id)
        previous_avatar = student.avatar_path
        student.embedding = serialize_embedding(embedding)
        student.avatar_path = avatar_path
        db.commit()
        db.refresh(student)
        return student, previous_avatar

    @staticmethod
    def delete(db: Session, student_id: int, storage: PrivateStorage) -> None:
        """Delete a student, keep anonymized behavior logs and remove the avatar."""

        student = StudentService.get(db, student_id)
        avatar = student.avatar_path
        db.execute(
            update(BehaviorLog)
            .where(BehaviorLog.student_id == student_id)
            .values(student_id=None)
        )
        db.delete(student)
        db.commit()
        if avatar:
            storage.delete_avatar(avatar)

    @staticmethod
    def list_all(db: Session) -> list[Student]:
        """Return registered students ordered by full name."""

        return list(db.scalars(select(Student).order_by(Student.fullname)))


@dataclass(frozen=True)
class SessionSummary:
    """Aggregated attendance numbers for one lesson."""

    total: int
    present: int
    late: int
    absent: int
    called: int
    manual: int
    behaviors: int

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-serializable summary."""

        return {
            "total": self.total,
            "present": self.present,
            "late": self.late,
            "absent": self.absent,
            "called": self.called,
            "manual": self.manual,
            "behaviors": self.behaviors,
        }


class ClassroomService:
    """Manage lesson lifecycle, attendance and random student calls."""

    @staticmethod
    def start_session(db: Session, title: str | None = None) -> ClassroomSession:
        """Start a lesson and initialize attendance state for all students."""

        active = ClassroomService.get_active_session(db)
        if active is not None:
            raise DomainError("Có phiên học đang hoạt động")
        normalized_title = " ".join((title or "").split()) or None
        if normalized_title and len(normalized_title) > 120:
            raise DomainError("Tên buổi học tối đa 120 ký tự")
        session = ClassroomSession(status="ACTIVE", title=normalized_title)
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
    def get_session(db: Session, session_id: int) -> ClassroomSession:
        """Return a lesson in any status."""

        classroom_session = db.get(ClassroomSession, session_id)
        if classroom_session is None:
            raise NotFoundError("Không tìm thấy phiên học")
        return classroom_session

    @staticmethod
    def list_sessions(db: Session, limit: int = 20) -> list[ClassroomSession]:
        """Return the newest lessons first."""

        return list(
            db.scalars(
                select(ClassroomSession)
                .order_by(
                    ClassroomSession.created_at.desc(), ClassroomSession.id.desc()
                )
                .limit(limit)
            )
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
    def mark_present(
        db: Session,
        session_id: int,
        student_id: int,
        now: datetime | None = None,
    ) -> bool:
        """Mark one student present from camera recognition.

        Returns ``True`` only when the attendance state actually changed. A
        teacher's manual decision is never overwritten by the camera.
        """

        ClassroomService._active_by_id(db, session_id)
        state = ClassroomService._state(db, session_id, student_id, create=True)
        if state.is_present or state.attendance_source == ATTENDANCE_MANUAL:
            return False
        state.is_present = True
        state.checked_in_at = now or utc_now()
        state.attendance_source = ATTENDANCE_AUTO
        db.commit()
        return True

    @staticmethod
    def set_attendance(
        db: Session,
        session_id: int,
        student_id: int,
        present: bool,
        note: str | None = None,
        now: datetime | None = None,
    ) -> SessionStudent:
        """Let the teacher confirm or correct attendance manually."""

        ClassroomService._active_by_id(db, session_id)
        StudentService.get(db, student_id)
        state = ClassroomService._state(db, session_id, student_id, create=True)
        normalized_note = " ".join((note or "").split()) or None
        if normalized_note and len(normalized_note) > 200:
            raise DomainError("Ghi chú tối đa 200 ký tự")
        if present and not state.is_present:
            state.checked_in_at = now or utc_now()
        if not present:
            state.checked_in_at = None
        state.is_present = present
        state.attendance_source = ATTENDANCE_MANUAL
        state.note = normalized_note
        db.commit()
        db.refresh(state)
        return state

    @staticmethod
    def pick_random(
        db: Session,
        session_id: int,
        chooser: random.Random | None = None,
    ) -> SessionStudent:
        """Pick one present student who has not yet been called.

        Absent students are only considered when nobody has been marked
        present yet (for example a lesson run without the camera).
        """

        ClassroomService._active_by_id(db, session_id)
        base = (
            select(SessionStudent)
            .options(joinedload(SessionStudent.student))
            .where(SessionStudent.session_id == session_id)
        )
        anyone_present = db.scalar(
            select(func.count())
            .select_from(SessionStudent)
            .where(
                SessionStudent.session_id == session_id,
                SessionStudent.is_present.is_(True),
            )
        )
        query = base.where(SessionStudent.is_called.is_(False))
        if anyone_present:
            query = query.where(SessionStudent.is_present.is_(True))
        candidates = list(db.scalars(query))
        if not candidates:
            if anyone_present:
                raise DomainError("Tất cả học sinh có mặt đã được gọi")
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
                .join(SessionStudent.student)
                .options(joinedload(SessionStudent.student))
                .where(SessionStudent.session_id == session_id)
                .order_by(Student.fullname, SessionStudent.id)
            )
        )

    @staticmethod
    def summary(db: Session, classroom_session: ClassroomSession) -> SessionSummary:
        """Aggregate attendance, random calls and behavior events."""

        states = ClassroomService.attendance(db, classroom_session.id)
        present = [state for state in states if state.is_present]
        behaviors = db.scalar(
            select(func.count())
            .select_from(BehaviorLog)
            .where(BehaviorLog.session_id == classroom_session.id)
        )
        return SessionSummary(
            total=len(states),
            present=len(present),
            late=sum(1 for state in present if is_late(state, classroom_session)),
            absent=len(states) - len(present),
            called=sum(1 for state in states if state.is_called),
            manual=sum(
                1 for state in states if state.attendance_source == ATTENDANCE_MANUAL
            ),
            behaviors=int(behaviors or 0),
        )

    @staticmethod
    def _state(
        db: Session, session_id: int, student_id: int, create: bool = False
    ) -> SessionStudent:
        state = db.scalar(
            select(SessionStudent).where(
                SessionStudent.session_id == session_id,
                SessionStudent.student_id == student_id,
            )
        )
        if state is None:
            if not create:
                raise NotFoundError("Học sinh không thuộc phiên học này")
            state = SessionStudent(
                session_id=session_id,
                student_id=student_id,
                is_present=False,
                is_called=False,
            )
            db.add(state)
            db.flush()
        return state

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
    def list_recent(
        db: Session, limit: int = 50, session_id: int | None = None
    ) -> list[BehaviorLog]:
        """Return the newest behavior events, optionally for one lesson."""

        query = select(BehaviorLog).options(joinedload(BehaviorLog.student))
        if session_id is not None:
            query = query.where(BehaviorLog.session_id == session_id)
        return list(
            db.scalars(
                query.order_by(BehaviorLog.timestamp.desc(), BehaviorLog.id.desc())
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
        """Delete selected behavior logs and any snapshots no longer referenced."""

        if not logs:
            return 0
        deleted_ids = [log.id for log in logs]
        snapshots = list(dict.fromkeys(log.snapshot_path for log in logs))
        db.execute(delete(BehaviorLog).where(BehaviorLog.id.in_(deleted_ids)))
        db.commit()
        # Several alerts from one frame share a snapshot; keep files still in use.
        still_used = set(db.scalars(select(BehaviorLog.snapshot_path)))
        for snapshot in snapshots:
            if snapshot in still_used:
                continue
            try:
                storage.delete_snapshot(snapshot)
            except FileNotFoundError:
                pass
        return len(logs)
