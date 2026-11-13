"""Tests for biometric consent, data erasure and the access log."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src import main
from src.migrate import purge_expired_backups
from src.models import AccessLog, BehaviorLog, ConsentEvent
from src.services import (
    AccessLogService,
    BehaviorLogService,
    ClassroomService,
    ClassService,
    ConsentService,
    DomainError,
    StudentService,
    UserService,
    has_face_embedding,
)


class FakeStorage:
    def __init__(self) -> None:
        self.avatars_deleted: list[str] = []
        self.snapshots_deleted: list[str] = []

    def delete_avatar(self, name: str) -> None:
        self.avatars_deleted.append(name)

    def delete_snapshot(self, name: str) -> None:
        self.snapshots_deleted.append(name)

    def read_snapshot(self, _name: str) -> bytes:
        return b"snapshot"

    def read_avatar(self, _name: str) -> bytes:
        return b"avatar"


@pytest.fixture
def db(session_factory: sessionmaker) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> FakeStorage:
    fake = FakeStorage()
    monkeypatch.setattr(main, "storage", fake)
    return fake


@pytest.fixture
def school(db: Session):
    teacher = UserService.create(db, "gv.a", "mat-khau-gv", "GV A", "TEACHER")
    outsider = UserService.create(db, "gv.b", "mat-khau-gv", "GV B", "TEACHER")
    admin = UserService.create(db, "quan.tri", "mat-khau-gv", "QT", "ADMIN")
    school_class = ClassService.create(db, "Toán 7A")
    ClassService.assign_teacher(db, school_class.id, teacher.id)
    student = StudentService.register(
        db, "A1", "An", [1.0, 0.0], "a1.enc", class_ids=[school_class.id]
    )
    return {
        "teacher": teacher,
        "outsider": outsider,
        "admin": admin,
        "class": school_class,
        "student": student,
    }


def sign_in(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": "mat-khau-gv"}
    )
    assert response.status_code == 200


def add_evidence(db: Session, school, student_id: int | None, snapshot: str):
    session = ClassroomService.get_active_session(db, school["class"].id)
    if session is None:
        session = ClassroomService.start_session(db, class_id=school["class"].id)
    return BehaviorLogService.create(db, session.id, "TALKING", snapshot, student_id)


def test_new_student_waits_for_consent(db: Session) -> None:
    assert StudentService.register(db, "X", "Xuân").consent_status == "PENDING"


def test_only_consented_students_are_recognized(db: Session, school) -> None:
    class_id = school["class"].id
    assert StudentService.recognizable(db, class_id) == []

    ConsentService.record(
        db, school["student"].id, "GRANTED", school["teacher"].id, FakeStorage()
    )

    assert [s.student_code for s in StudentService.recognizable(db, class_id)] == ["A1"]


def test_every_change_is_recorded_with_its_author(db: Session, school) -> None:
    ConsentService.record(
        db,
        school["student"].id,
        "GRANTED",
        school["teacher"].id,
        FakeStorage(),
        note="Có đơn",
    )

    event = db.scalar(select(ConsentEvent))
    assert (event.status, event.recorded_by, event.note, event.student_code) == (
        "GRANTED",
        school["teacher"].id,
        "Có đơn",
        "A1",
    )


def test_unknown_status_is_rejected(db: Session, school) -> None:
    with pytest.raises(DomainError, match="không hợp lệ"):
        ConsentService.record(
            db, school["student"].id, "MAYBE", school["teacher"].id, FakeStorage()
        )


@pytest.mark.parametrize("status", ["WITHDRAWN", "REFUSED"])
def test_withdrawing_erases_face_and_avatar(db: Session, school, status: str) -> None:
    storage = FakeStorage()

    student = ConsentService.record(
        db, school["student"].id, status, school["teacher"].id, storage
    )

    assert not has_face_embedding(student)
    assert student.avatar_path is None
    assert storage.avatars_deleted == ["a1.enc"]


def test_withdrawing_removes_the_student_evidence(db: Session, school) -> None:
    storage = FakeStorage()
    add_evidence(db, school, school["student"].id, "shot.enc")

    ConsentService.record(
        db, school["student"].id, "WITHDRAWN", school["teacher"].id, storage
    )

    assert storage.snapshots_deleted == ["shot.enc"]
    assert list(db.scalars(select(BehaviorLog))) == []


def test_withdrawing_removes_shared_snapshots_too(db: Session, school) -> None:
    storage = FakeStorage()
    add_evidence(db, school, school["student"].id, "shared.enc")
    add_evidence(db, school, None, "shared.enc")
    add_evidence(db, school, None, "other.enc")

    ConsentService.record(
        db, school["student"].id, "WITHDRAWN", school["teacher"].id, storage
    )

    assert storage.snapshots_deleted == ["shared.enc"]
    assert [log.snapshot_path for log in db.scalars(select(BehaviorLog))] == [
        "other.enc"
    ]


def test_withdrawing_keeps_attendance_history(db: Session, school) -> None:
    session = ClassroomService.start_session(db, class_id=school["class"].id)
    ClassroomService.set_attendance(db, session.id, school["student"].id, True)

    ConsentService.record(
        db, school["student"].id, "WITHDRAWN", school["teacher"].id, FakeStorage()
    )

    assert ClassroomService.attendance(db, session.id)[0].is_present is True


def test_deleting_student_keeps_consent_history(db: Session, school) -> None:
    storage = FakeStorage()
    ConsentService.record(
        db, school["student"].id, "GRANTED", school["teacher"].id, storage
    )

    StudentService.delete(db, school["student"].id, storage)
    db.expire_all()

    event = db.scalar(select(ConsentEvent))
    assert (event.student_id, event.student_code) == (None, "A1")


def test_face_image_needs_consent_when_registering(client, school, storage) -> None:
    sign_in(client, "gv.a")

    response = client.post(
        "/api/students/register",
        data={"student_code": "N1", "fullname": "Mới", "class_id": school["class"].id},
        files={"image": ("a.jpg", b"jpeg", "image/jpeg")},
    )

    assert response.status_code == 409
    assert "đồng ý" in response.json()["detail"]


def test_registering_with_consent_records_it(client, db, school, storage) -> None:
    sign_in(client, "gv.a")

    response = client.post(
        "/api/students/register",
        data={
            "student_code": "N2",
            "fullname": "Mới",
            "class_id": school["class"].id,
            "consent": "true",
        },
    )

    assert response.json()["consent_status"] == "GRANTED"
    assert db.scalar(select(ConsentEvent)).recorded_by == school["teacher"].id


def test_face_update_needs_consent(client, school, storage) -> None:
    sign_in(client, "gv.a")

    response = client.post(
        f"/api/students/{school['student'].id}/face",
        files={"image": ("a.jpg", b"jpeg", "image/jpeg")},
    )

    assert response.status_code == 409


def test_teacher_records_consent_through_api(client, db, school, storage) -> None:
    sign_in(client, "gv.a")

    response = client.put(
        f"/api/students/{school['student'].id}/consent",
        json={"status": "GRANTED", "note": "Đơn số 12"},
    )

    assert response.json()["consent_status"] == "GRANTED"


def test_other_teacher_cannot_change_consent(client, school, storage) -> None:
    sign_in(client, "gv.b")

    response = client.put(
        f"/api/students/{school['student'].id}/consent", json={"status": "WITHDRAWN"}
    )

    assert response.status_code == 403
    assert school["student"].consent_status == "PENDING"


def test_viewing_evidence_is_logged(client, db, school, storage) -> None:
    add_evidence(db, school, school["student"].id, "shot.enc")
    sign_in(client, "gv.a")

    assert client.get("/api/snapshots/shot.enc").status_code == 200

    entry = db.scalar(select(AccessLog))
    assert (entry.user_id, entry.action, entry.target) == (
        school["teacher"].id,
        "VIEW_SNAPSHOT",
        "shot.enc",
    )


def test_viewing_avatar_is_logged(client, db, school, storage) -> None:
    sign_in(client, "gv.a")

    assert client.get("/api/avatars/a1.enc").status_code == 200

    assert db.scalar(select(AccessLog)).action == "VIEW_AVATAR"


def test_refused_view_is_not_served(client, db, school, storage) -> None:
    add_evidence(db, school, school["student"].id, "shot.enc")
    sign_in(client, "gv.b")

    assert client.get("/api/snapshots/shot.enc").status_code == 403
    assert db.scalar(select(AccessLog)) is None


def test_only_admin_reads_the_access_log(client, db, school, storage) -> None:
    AccessLogService.record(db, school["teacher"].id, "VIEW_SNAPSHOT", "shot.enc")
    sign_in(client, "gv.a")
    assert client.get("/api/access-logs").status_code == 403

    client.post("/api/auth/logout")
    client.cookies.clear()
    sign_in(client, "quan.tri")

    [entry] = client.get("/api/access-logs").json()
    assert entry["username"] == "gv.a"
    assert entry["target"] == "shot.enc"


def make_backup(directory: Path, name: str, age_days: float) -> Path:
    path = directory / name
    path.write_bytes(b"backup")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_expired_backups_are_deleted(tmp_path: Path) -> None:
    expired = make_backup(tmp_path, "classroom.db.bak-0001", 31)
    recent = make_backup(tmp_path, "classroom.db.bak-0002", 1)
    database = make_backup(tmp_path, "classroom.db", 400)

    assert purge_expired_backups(database, retention_days=30) == 1

    assert not expired.exists()
    assert recent.exists()
    assert database.exists()


def test_student_consent_events_endpoint_returns_audit_trail_and_enforces_access(
    client, db, school, storage
) -> None:
    ConsentService.record(
        db, school["student"].id, "GRANTED", school["teacher"].id, storage, note="Phiếu 01"
    )
    ConsentService.record(
        db, school["student"].id, "WITHDRAWN", school["teacher"].id, storage, note="Phụ huynh yêu cầu"
    )

    sign_in(client, "gv.b")
    assert (
        client.get(f"/api/students/{school['student'].id}/consent-events").status_code
        == 403
    )

    client.post("/api/auth/logout")
    client.cookies.clear()
    sign_in(client, "gv.a")
    response = client.get(f"/api/students/{school['student'].id}/consent-events")
    assert response.status_code == 200
    events = response.json()
    assert [item["status"] for item in events] == ["WITHDRAWN", "GRANTED"]
    assert events[0]["note"] == "Phụ huynh yêu cầu"
    assert events[0]["recorded_by_name"] == "GV A"


def test_delete_single_behavior_log_checks_access_and_cleans_unshared_snapshot(
    client, db, school, storage
) -> None:
    log_a = add_evidence(db, school, school["student"].id, "only-a.enc")
    session_a = ClassroomService.get_session(db, log_a.session_id)
    shared_1 = BehaviorLogService.create(
        db, session_a.id, "CHEATING", "shared-a.enc", school["student"].id
    )
    BehaviorLogService.create(db, session_a.id, "TALKING", "shared-a.enc", None)

    sign_in(client, "gv.b")
    assert client.delete(f"/api/behaviors/{log_a.id}").status_code == 403

    client.post("/api/auth/logout")
    client.cookies.clear()
    sign_in(client, "gv.a")
    assert client.delete(f"/api/behaviors/{shared_1.id}").status_code == 200
    assert storage.snapshots_deleted == []

    assert client.delete(f"/api/behaviors/{log_a.id}").status_code == 200
    assert storage.snapshots_deleted == ["only-a.enc"]
