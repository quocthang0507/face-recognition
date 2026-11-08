"""Database models for students, classroom sessions and behavior logs."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive timestamps returned by SQLite."""

    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def iso_utc(value: datetime | None) -> str | None:
    """Serialize a stored timestamp as ISO 8601 with an explicit UTC offset."""

    normalized = as_utc(value)
    return normalized.isoformat() if normalized else None


class User(Base):
    """A person who can sign in to the dashboard."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    fullname: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class_teachers = Table(
    "class_teachers",
    Base.metadata,
    Column("class_id", ForeignKey("classes.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)
class_students = Table(
    "class_students",
    Base.metadata,
    Column("class_id", ForeignKey("classes.id"), primary_key=True),
    Column("student_id", ForeignKey("students.id"), primary_key=True),
)


class SchoolClass(Base):
    """A class or subject group taught by assigned teachers."""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    school_year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    teachers: Mapped[list["User"]] = relationship(secondary=class_teachers)
    students: Mapped[list["Student"]] = relationship(
        secondary=class_students, back_populates="classes"
    )


class Student(Base):
    """A registered student with a non-reversible face embedding."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    fullname: Mapped[str] = mapped_column(String(100))
    embedding: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(40), nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    consent_status: Mapped[str] = mapped_column(
        String(10), default="PENDING", server_default="PENDING"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    session_entries: Mapped[list["SessionStudent"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    classes: Mapped[list[SchoolClass]] = relationship(
        secondary=class_students, back_populates="students"
    )


class ClassroomSession(Base):
    """A lesson during which attendance and random calls are tracked."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id"), nullable=True, index=True
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    students: Mapped[list["SessionStudent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    behavior_logs: Mapped[list["BehaviorLog"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ConsentEvent(Base):
    """One recorded consent decision. Rows are only ever added."""

    __tablename__ = "consent_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True, index=True
    )
    student_code: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10))
    recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AccessLog(Base):
    """Who opened a protected student image, and when."""

    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))
    target: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    user: Mapped[User] = relationship()


class SessionStudent(Base):
    """Attendance and random-call state for one student in one lesson."""

    __tablename__ = "session_students"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_session_student"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    is_present: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attendance_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_called: Mapped[bool] = mapped_column(Boolean, default=False)
    called_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped[ClassroomSession] = relationship(back_populates="students")
    student: Mapped[Student] = relationship(back_populates="session_entries")


class BehaviorLog(Base):
    """An abnormal-behavior event with an evidence snapshot."""

    __tablename__ = "behavior_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True, index=True
    )
    behavior_type: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    snapshot_path: Mapped[str] = mapped_column(String(255))

    session: Mapped[ClassroomSession] = relationship(back_populates="behavior_logs")
    student: Mapped[Student | None] = relationship()
