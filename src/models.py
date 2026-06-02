"""Database models for students, classroom sessions and behavior logs."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class Student(Base):
    """A registered student with a non-reversible face embedding."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    fullname: Mapped[str] = mapped_column(String(100))
    embedding: Mapped[str] = mapped_column(Text)
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    session_entries: Mapped[list["SessionStudent"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
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

    students: Mapped[list["SessionStudent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    behavior_logs: Mapped[list["BehaviorLog"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


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
