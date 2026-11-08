"""Business services for students, lessons and behavior audit logs."""

from __future__ import annotations

import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, joinedload

from . import cache
from .auth import hash_password, verify_password
from .config import settings
from .models import (
    AccessLog,
    BehaviorLog,
    ClassroomSession,
    ConsentEvent,
    SchoolClass,
    SessionStudent,
    Student,
    User,
    class_students,
    class_teachers,
    as_utc,
    utc_now,
)
from .storage import PrivateStorage

ATTENDANCE_AUTO = "AUTO"
ATTENDANCE_MANUAL = "MANUAL"
ROLE_ADMIN = "ADMIN"
ROLE_TEACHER = "TEACHER"
ROLES = (ROLE_ADMIN, ROLE_TEACHER)
ADMIN_USERNAME = "admin"
DEFAULT_CLASS_NAME = "Lớp mặc định"
CONSENT_PENDING = "PENDING"
CONSENT_GRANTED = "GRANTED"
CONSENT_REFUSED = "REFUSED"
CONSENT_WITHDRAWN = "WITHDRAWN"
RECORDABLE_CONSENT = (CONSENT_GRANTED, CONSENT_REFUSED, CONSENT_WITHDRAWN)
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"[a-z0-9._-]{3,50}")
# Verified when the username is unknown, so both failures take the same time.
_UNKNOWN_USER_HASH = hash_password("unknown-user-placeholder")


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


class UserService:
    """Manage dashboard accounts."""

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise DomainError(f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự")

    @staticmethod
    def _validate_role(role: str) -> None:
        if role not in ROLES:
            raise DomainError("Vai trò không hợp lệ")

    @staticmethod
    def _normalize_fullname(fullname: str) -> str:
        normalized = " ".join(fullname.split())
        if not normalized or len(normalized) > 100:
            raise DomainError("Họ và tên phải có từ 1-100 ký tự")
        return normalized

    @staticmethod
    def create(
        db: Session, username: str, password: str, fullname: str, role: str
    ) -> User:
        """Create one account after validating its fields."""

        normalized_username = username.strip().lower()
        if not USERNAME_PATTERN.fullmatch(normalized_username):
            raise DomainError(
                "Tên đăng nhập gồm 3-50 ký tự: chữ không dấu, số, dấu chấm, gạch"
            )
        UserService._validate_password(password)
        UserService._validate_role(role)
        normalized_name = UserService._normalize_fullname(fullname)
        if db.scalar(select(User).where(User.username == normalized_username)):
            raise DomainError("Tên đăng nhập đã tồn tại")
        user = User(
            username=normalized_username,
            password_hash=hash_password(password),
            fullname=normalized_name,
            role=role,
        )
        db.add(user)
        db.commit()
        return user

    @staticmethod
    def authenticate(db: Session, username: str, password: str) -> User | None:
        """Return the active account matching the credentials, if any."""

        user = db.scalar(select(User).where(User.username == username.strip().lower()))
        stored = user.password_hash if user else _UNKNOWN_USER_HASH
        if not verify_password(password, stored):
            return None
        return user if user and user.is_active else None

    @staticmethod
    def get(db: Session, user_id: int) -> User:
        user = db.get(User, user_id)
        if user is None:
            raise NotFoundError("Không tìm thấy tài khoản")
        return user

    @staticmethod
    def list_all(db: Session) -> list[User]:
        return list(db.scalars(select(User).order_by(User.username)))

    @staticmethod
    def update(
        db: Session,
        user_id: int,
        fullname: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> User:
        """Change an account while always keeping one active administrator."""

        user = UserService.get(db, user_id)
        if role is not None:
            UserService._validate_role(role)
        loses_admin = user.role == ROLE_ADMIN and user.is_active and (
            is_active is False or (role is not None and role != ROLE_ADMIN)
        )
        if loses_admin:
            active_admins = db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == ROLE_ADMIN, User.is_active.is_(True))
            )
            if active_admins <= 1:
                raise DomainError("Phải còn ít nhất một tài khoản Quản trị đang hoạt động")
        if fullname is not None:
            user.fullname = UserService._normalize_fullname(fullname)
        if password is not None:
            UserService._validate_password(password)
            user.password_hash = hash_password(password)
            user.token_version += 1
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        db.commit()
        return user

    @staticmethod
    def revoke_tokens(db: Session, user: User) -> None:
        """End every session of this account."""

        user.token_version += 1
        db.commit()

    @staticmethod
    def ensure_admin(db: Session, password: str) -> None:
        """Create the first administrator from the deployment's existing password."""

        if db.scalar(select(func.count()).select_from(User)):
            return
        db.add(
            User(
                username=ADMIN_USERNAME,
                password_hash=hash_password(password),
                fullname="Quản trị viên",
                role=ROLE_ADMIN,
            )
        )
        db.commit()


class StudentService:
    """Manage registered students."""

    @staticmethod
    def register(
        db: Session,
        student_code: str,
        fullname: str,
        embedding: Sequence[float] | None = None,
        avatar_path: str | None = None,
        class_ids: Sequence[int] = (),
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
            embedding_model=settings.embedding_model_id if embedding else None,
            avatar_path=avatar_path,
        )
        db.add(student)
        db.flush()

        for class_id in class_ids:
            student.classes.append(ClassService.get(db, class_id))
        # Join the lessons running right now for this student's classes.
        active_query = select(ClassroomSession).where(
            ClassroomSession.status == "ACTIVE"
        )
        if class_ids:
            active_query = active_query.where(ClassroomSession.class_id.in_(class_ids))
        for active_session in db.scalars(active_query):
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
        cache.bump("students")
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
        student.embedding_model = settings.embedding_model_id
        student.avatar_path = avatar_path
        db.commit()
        db.refresh(student)
        cache.bump("students")
        return student, previous_avatar

    @staticmethod
    def replace_embedding(
        db: Session, student: Student, embedding: Sequence[float]
    ) -> None:
        """Store a recomputed embedding for the current model, keeping the avatar."""

        student.embedding = serialize_embedding(embedding)
        student.embedding_model = settings.embedding_model_id
        db.commit()
        cache.bump("students")

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
        db.execute(
            update(ConsentEvent)
            .where(ConsentEvent.student_id == student_id)
            .values(student_id=None)
        )
        db.delete(student)
        db.commit()
        cache.bump("students")
        if avatar:
            storage.delete_avatar(avatar)

    @staticmethod
    def list_all(db: Session, class_id: int | None = None) -> list[Student]:
        """Return students ordered by full name, optionally for one class."""

        query = select(Student).order_by(Student.fullname)
        if class_id is not None:
            query = query.join(class_students).where(
                class_students.c.class_id == class_id
            )
        return list(db.scalars(query))

    @staticmethod
    def recognizable(db: Session, class_id: int | None = None) -> list[Student]:
        """Return the students the camera is allowed to identify."""

        return [
            student
            for student in StudentService.list_all(db, class_id)
            if student.consent_status == CONSENT_GRANTED
        ]

    @staticmethod
    def find_by_code(db: Session, student_code: str) -> Student:
        student = db.scalar(
            select(Student).where(Student.student_code == student_code.strip())
        )
        if student is None:
            raise NotFoundError("Không tìm thấy học sinh có mã này")
        return student


class ConsentService:
    """Record biometric consent and erase data when it is not given."""

    @staticmethod
    def record(
        db: Session,
        student_id: int,
        status: str,
        user_id: int,
        storage: PrivateStorage,
        note: str | None = None,
    ) -> Student:
        """Store one decision; refusal or withdrawal erases biometric data."""

        if status not in RECORDABLE_CONSENT:
            raise DomainError("Trạng thái đồng ý không hợp lệ")
        normalized_note = " ".join((note or "").split()) or None
        if normalized_note and len(normalized_note) > 200:
            raise DomainError("Ghi chú tối đa 200 ký tự")
        student = StudentService.get(db, student_id)
        if student.consent_status == status:
            return student

        avatar = None
        evidence: list[BehaviorLog] = []
        if status != CONSENT_GRANTED:
            avatar = student.avatar_path
            evidence = ConsentService._evidence_of(db, student_id)
            student.embedding = serialize_embedding(None)
            student.embedding_model = None
            student.avatar_path = None
        student.consent_status = status
        db.add(
            ConsentEvent(
                student_id=student_id,
                student_code=student.student_code,
                status=status,
                recorded_by=user_id,
                note=normalized_note,
            )
        )
        db.commit()
        cache.bump("students")
        BehaviorLogService._delete_logs(db, storage, evidence)
        if avatar:
            storage.delete_avatar(avatar)
        return student

    @staticmethod
    def _evidence_of(db: Session, student_id: int) -> list[BehaviorLog]:
        """Return the student's logs and any others sharing the same image."""

        snapshots = select(BehaviorLog.snapshot_path).where(
            BehaviorLog.student_id == student_id
        )
        return list(
            db.scalars(select(BehaviorLog).where(BehaviorLog.snapshot_path.in_(snapshots)))
        )


class AccessLogService:
    """Keep a trail of who opened protected student images."""

    @staticmethod
    def record(db: Session, user_id: int, action: str, target: str) -> None:
        db.add(AccessLog(user_id=user_id, action=action, target=target))
        db.commit()

    @staticmethod
    def list_recent(db: Session, limit: int = 100) -> list[AccessLog]:
        return list(
            db.scalars(
                select(AccessLog)
                .options(joinedload(AccessLog.user))
                .order_by(AccessLog.created_at.desc(), AccessLog.id.desc())
                .limit(limit)
            )
        )


class ClassService:
    """Manage classes, teacher assignments and class membership."""

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = " ".join(name.split())
        if not normalized or len(normalized) > 100:
            raise DomainError("Tên lớp phải có từ 1-100 ký tự")
        return normalized

    @staticmethod
    def create(db: Session, name: str, school_year: str | None = None) -> SchoolClass:
        normalized = ClassService._normalize_name(name)
        if db.scalar(select(SchoolClass).where(SchoolClass.name == normalized)):
            raise DomainError("Tên lớp đã tồn tại")
        school_class = SchoolClass(
            name=normalized, school_year=(school_year or "").strip() or None
        )
        db.add(school_class)
        db.commit()
        return school_class

    @staticmethod
    def ensure_default(db: Session) -> None:
        """Give a brand-new installation one class to start from."""

        if not db.scalar(select(func.count()).select_from(SchoolClass)):
            ClassService.create(db, DEFAULT_CLASS_NAME)

    @staticmethod
    def get(db: Session, class_id: int) -> SchoolClass:
        school_class = db.get(SchoolClass, class_id)
        if school_class is None:
            raise NotFoundError("Không tìm thấy lớp")
        return school_class

    @staticmethod
    def list_all(db: Session) -> list[SchoolClass]:
        return list(
            db.scalars(
                select(SchoolClass)
                .where(SchoolClass.is_archived.is_(False))
                .order_by(SchoolClass.name)
            )
        )

    @staticmethod
    def list_for_teacher(db: Session, user_id: int) -> list[SchoolClass]:
        return list(
            db.scalars(
                select(SchoolClass)
                .join(class_teachers)
                .where(
                    class_teachers.c.user_id == user_id,
                    SchoolClass.is_archived.is_(False),
                )
                .order_by(SchoolClass.name)
            )
        )

    @staticmethod
    def update(
        db: Session,
        class_id: int,
        name: str | None = None,
        school_year: str | None = None,
        is_archived: bool | None = None,
    ) -> SchoolClass:
        school_class = ClassService.get(db, class_id)
        if name is not None:
            normalized = ClassService._normalize_name(name)
            duplicate = db.scalar(
                select(SchoolClass).where(
                    SchoolClass.name == normalized, SchoolClass.id != class_id
                )
            )
            if duplicate:
                raise DomainError("Tên lớp đã tồn tại")
            school_class.name = normalized
        if school_year is not None:
            school_class.school_year = school_year.strip() or None
        if is_archived is not None:
            school_class.is_archived = is_archived
        db.commit()
        return school_class

    @staticmethod
    def is_assigned(db: Session, class_id: int, user_id: int) -> bool:
        return bool(
            db.scalar(
                select(class_teachers.c.user_id).where(
                    class_teachers.c.class_id == class_id,
                    class_teachers.c.user_id == user_id,
                )
            )
        )

    @staticmethod
    def has_student(db: Session, class_id: int, student_id: int) -> bool:
        return bool(
            db.scalar(
                select(class_students.c.student_id).where(
                    class_students.c.class_id == class_id,
                    class_students.c.student_id == student_id,
                )
            )
        )

    @staticmethod
    def teacher_has_student(db: Session, user_id: int, student_id: int) -> bool:
        return bool(
            db.scalar(
                select(class_students.c.student_id)
                .join(
                    class_teachers,
                    class_teachers.c.class_id == class_students.c.class_id,
                )
                .where(
                    class_teachers.c.user_id == user_id,
                    class_students.c.student_id == student_id,
                )
                .limit(1)
            )
        )

    @staticmethod
    def assign_teacher(db: Session, class_id: int, user_id: int) -> None:
        school_class = ClassService.get(db, class_id)
        user = UserService.get(db, user_id)
        if user not in school_class.teachers:
            school_class.teachers.append(user)
            db.commit()

    @staticmethod
    def unassign_teacher(db: Session, class_id: int, user_id: int) -> None:
        school_class = ClassService.get(db, class_id)
        user = UserService.get(db, user_id)
        if user in school_class.teachers:
            school_class.teachers.remove(user)
            db.commit()

    @staticmethod
    def add_student(db: Session, class_id: int, student_id: int) -> None:
        """Add an existing student, joining the class's lesson if one is running."""

        school_class = ClassService.get(db, class_id)
        student = StudentService.get(db, student_id)
        if student not in school_class.students:
            school_class.students.append(student)
            db.flush()
        active = ClassroomService.get_active_session(db, class_id)
        if active is not None:
            ClassroomService._state(db, active.id, student_id, create=True)
        db.commit()
        cache.bump("students")

    @staticmethod
    def remove_student(
        db: Session, class_id: int, student_id: int, storage: PrivateStorage
    ) -> None:
        """Remove a student from a class, deleting them after their last class."""

        school_class = ClassService.get(db, class_id)
        student = StudentService.get(db, student_id)
        if student not in school_class.students:
            raise NotFoundError("Học sinh không thuộc lớp này")
        if len(student.classes) <= 1:
            StudentService.delete(db, student_id, storage)
            return
        school_class.students.remove(student)
        active = ClassroomService.get_active_session(db, class_id)
        if active is not None:
            db.execute(
                delete(SessionStudent).where(
                    SessionStudent.session_id == active.id,
                    SessionStudent.student_id == student_id,
                )
            )
        db.commit()
        cache.bump("students")


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
    def start_session(
        db: Session,
        title: str | None = None,
        class_id: int | None = None,
        teacher_id: int | None = None,
    ) -> ClassroomSession:
        """Start a lesson and initialize attendance state for its students."""

        active = ClassroomService.get_active_session(db, class_id)
        if active is not None:
            raise DomainError("Có phiên học đang hoạt động")
        normalized_title = " ".join((title or "").split()) or None
        if normalized_title and len(normalized_title) > 120:
            raise DomainError("Tên buổi học tối đa 120 ký tự")
        session = ClassroomSession(
            status="ACTIVE",
            title=normalized_title,
            class_id=class_id,
            teacher_id=teacher_id,
        )
        db.add(session)
        db.flush()

        for student in StudentService.list_all(db, class_id):
            db.add(
                SessionStudent(
                    session_id=session.id,
                    student_id=student.id,
                    is_present=False,
                    is_called=False,
                )
            )
        db.commit()
        cache.bump("sessions")
        return session

    @staticmethod
    def get_active_session(
        db: Session, class_id: int | None = None
    ) -> ClassroomSession | None:
        """Return the active lesson of one class, or any active lesson."""

        query = select(ClassroomSession).where(ClassroomSession.status == "ACTIVE")
        if class_id is not None:
            query = query.where(ClassroomSession.class_id == class_id)
        return db.scalar(query.limit(1))

    @staticmethod
    def get_session(db: Session, session_id: int) -> ClassroomSession:
        """Return a lesson in any status."""

        classroom_session = db.get(ClassroomSession, session_id)
        if classroom_session is None:
            raise NotFoundError("Không tìm thấy phiên học")
        return classroom_session

    @staticmethod
    def list_sessions(
        db: Session, limit: int = 20, class_id: int | None = None
    ) -> list[ClassroomSession]:
        """Return the newest lessons first, optionally for one class."""

        query = select(ClassroomSession)
        if class_id is not None:
            query = query.where(ClassroomSession.class_id == class_id)
        return list(
            db.scalars(
                query.order_by(
                    ClassroomSession.created_at.desc(), ClassroomSession.id.desc()
                ).limit(limit)
            )
        )

    @staticmethod
    def finish_session(db: Session, session_id: int) -> ClassroomSession:
        """Finish an active lesson."""

        classroom_session = ClassroomService._active_by_id(db, session_id)
        classroom_session.status = "FINISHED"
        classroom_session.finished_at = utc_now()
        db.commit()
        cache.bump("sessions")
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
        """Start a new picker round.

        ``called_at`` is kept so reports still show who answered in the lesson.
        """

        ClassroomService._active_by_id(db, session_id)
        states = db.scalars(
            select(SessionStudent).where(SessionStudent.session_id == session_id)
        )
        for state in states:
            state.is_called = False
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
            called=sum(1 for state in states if state.called_at is not None),
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
        db: Session,
        limit: int = 50,
        session_id: int | None = None,
        class_id: int | None = None,
    ) -> list[BehaviorLog]:
        """Return the newest behavior events, optionally for a lesson or class."""

        query = select(BehaviorLog).options(joinedload(BehaviorLog.student))
        if class_id is not None:
            query = query.join(BehaviorLog.session).where(
                ClassroomSession.class_id == class_id
            )
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
    def clear_all(
        db: Session, storage: PrivateStorage, class_id: int | None = None
    ) -> int:
        """Delete behavior logs and snapshots, optionally for one class."""

        query = select(BehaviorLog)
        if class_id is not None:
            query = query.join(BehaviorLog.session).where(
                ClassroomSession.class_id == class_id
            )
        logs = list(db.scalars(query))
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
