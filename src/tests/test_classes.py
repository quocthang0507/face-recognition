"""Tests for classes, teacher assignment and per-class access."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from src.models import User
from src.services import (
    ClassService,
    ClassroomService,
    DomainError,
    StudentService,
    UserService,
)


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_avatar(self, name: str) -> None:
        self.deleted.append(name)


@pytest.fixture
def db(session_factory: sessionmaker) -> Iterator[Session]:
    with session_factory() as session:
        yield session


def make_user(db: Session, username: str, role: str = "TEACHER") -> User:
    return UserService.create(db, username, "mat-khau-gv", username, role)


def sign_in(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": "mat-khau-gv"}
    )
    assert response.status_code == 200


@pytest.fixture
def school(db: Session):
    """Two classes, each with one assigned teacher and one student."""

    admin = make_user(db, "quan.tri", "ADMIN")
    teacher_a = make_user(db, "gv.a")
    teacher_b = make_user(db, "gv.b")
    class_a = ClassService.create(db, "Toán 7A")
    class_b = ClassService.create(db, "Văn 7B")
    ClassService.assign_teacher(db, class_a.id, teacher_a.id)
    ClassService.assign_teacher(db, class_b.id, teacher_b.id)
    student_a = StudentService.register(db, "A1", "An", class_ids=[class_a.id])
    student_b = StudentService.register(db, "B1", "Bình", class_ids=[class_b.id])
    return {
        "admin": admin,
        "teacher_a": teacher_a,
        "teacher_b": teacher_b,
        "class_a": class_a,
        "class_b": class_b,
        "student_a": student_a,
        "student_b": student_b,
    }


def test_class_name_must_be_unique(db: Session) -> None:
    ClassService.create(db, "Toán 7A")

    with pytest.raises(DomainError, match="đã tồn tại"):
        ClassService.create(db, "  Toán   7A ")


def test_student_can_belong_to_several_classes(db: Session, school) -> None:
    ClassService.add_student(db, school["class_b"].id, school["student_a"].id)

    assert school["student_a"].id in {
        student.id for student in StudentService.list_all(db, school["class_b"].id)
    }
    assert school["student_a"].id in {
        student.id for student in StudentService.list_all(db, school["class_a"].id)
    }


def test_session_only_enrolls_students_of_its_class(db: Session, school) -> None:
    session = ClassroomService.start_session(db, class_id=school["class_a"].id)

    enrolled = {
        state.student_id for state in ClassroomService.attendance(db, session.id)
    }

    assert enrolled == {school["student_a"].id}


def test_different_classes_can_run_lessons_at_once(db: Session, school) -> None:
    ClassroomService.start_session(db, class_id=school["class_a"].id)

    second = ClassroomService.start_session(db, class_id=school["class_b"].id)

    assert second.class_id == school["class_b"].id


def test_one_class_cannot_run_two_lessons_at_once(db: Session, school) -> None:
    ClassroomService.start_session(db, class_id=school["class_a"].id)

    with pytest.raises(DomainError, match="đang hoạt động"):
        ClassroomService.start_session(db, class_id=school["class_a"].id)


def test_student_added_mid_lesson_joins_that_class_lesson(db: Session, school) -> None:
    session = ClassroomService.start_session(db, class_id=school["class_a"].id)
    other = ClassroomService.start_session(db, class_id=school["class_b"].id)

    new = StudentService.register(db, "A2", "Mới", class_ids=[school["class_a"].id])

    enrolled = {
        state.student_id for state in ClassroomService.attendance(db, session.id)
    }
    enrolled_other = {
        state.student_id for state in ClassroomService.attendance(db, other.id)
    }
    assert new.id in enrolled
    assert new.id not in enrolled_other


def test_removing_from_one_of_two_classes_keeps_the_student(
    db: Session, school
) -> None:
    storage = FakeStorage()
    student_id = school["student_a"].id
    ClassService.add_student(db, school["class_b"].id, student_id)

    ClassService.remove_student(db, school["class_a"].id, student_id, storage)

    assert StudentService.get(db, student_id) is not None
    assert student_id not in {
        s.id for s in StudentService.list_all(db, school["class_a"].id)
    }


def test_removing_from_last_class_deletes_the_student(db: Session, school) -> None:
    storage = FakeStorage()
    student_id = school["student_a"].id

    ClassService.remove_student(db, school["class_a"].id, student_id, storage)

    assert StudentService.list_all(db, school["class_a"].id) == []


def test_default_class_is_created_once(db: Session) -> None:
    ClassService.ensure_default(db)
    ClassService.ensure_default(db)

    assert [item.name for item in ClassService.list_all(db)] == ["Lớp mặc định"]


def test_teacher_sees_only_assigned_classes(client, school) -> None:
    sign_in(client, "gv.a")

    names = [item["name"] for item in client.get("/api/classes").json()]

    assert names == ["Toán 7A"]


def test_admin_sees_every_class(client, school) -> None:
    sign_in(client, "quan.tri")

    assert len(client.get("/api/classes").json()) == 2


def test_teacher_cannot_create_classes(client, school) -> None:
    sign_in(client, "gv.a")

    assert client.post("/api/classes", json={"name": "Lớp mới"}).status_code == 403


def test_teacher_lists_students_only_for_own_class(client, school) -> None:
    sign_in(client, "gv.a")

    own = client.get(f"/api/students?class_id={school['class_a'].id}")
    other = client.get(f"/api/students?class_id={school['class_b'].id}")

    assert [item["student_code"] for item in own.json()] == ["A1"]
    assert other.status_code == 403


def test_teacher_must_choose_a_class_to_list_students(client, school) -> None:
    sign_in(client, "gv.a")

    assert client.get("/api/students").status_code == 400


def test_teacher_cannot_register_into_other_class(client, school) -> None:
    sign_in(client, "gv.a")

    response = client.post(
        "/api/students/register",
        data={
            "student_code": "X1",
            "fullname": "Lạ",
            "class_id": school["class_b"].id,
        },
    )

    assert response.status_code == 403


def test_teacher_cannot_delete_student_of_other_class(client, school) -> None:
    sign_in(client, "gv.a")

    response = client.delete(
        f"/api/students/{school['student_b'].id}" f"?class_id={school['class_b'].id}"
    )

    assert response.status_code == 403


def test_teacher_cannot_start_lesson_for_other_class(client, school) -> None:
    sign_in(client, "gv.a")

    response = client.post("/api/sessions", json={"class_id": school["class_b"].id})

    assert response.status_code == 403


def test_lesson_records_the_teacher_who_started_it(client, db, school) -> None:
    sign_in(client, "gv.a")

    body = client.post("/api/sessions", json={"class_id": school["class_a"].id}).json()

    assert ClassroomService.get_session(db, body["id"]).teacher_id == (
        school["teacher_a"].id
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/sessions/{id}"),
        ("post", "/api/sessions/{id}/finish"),
        ("post", "/api/sessions/{id}/pick"),
        ("post", "/api/sessions/{id}/reset-called"),
        ("get", "/api/sessions/{id}/export.csv"),
    ],
)
def test_teacher_cannot_touch_lessons_of_other_class(
    client, db, school, method: str, path: str
) -> None:
    session = ClassroomService.start_session(db, class_id=school["class_b"].id)
    sign_in(client, "gv.a")

    response = getattr(client, method)(path.format(id=session.id))

    assert response.status_code == 403


def test_teacher_cannot_mark_attendance_in_other_class(client, db, school) -> None:
    session = ClassroomService.start_session(db, class_id=school["class_b"].id)
    sign_in(client, "gv.a")

    response = client.put(
        f"/api/sessions/{session.id}/attendance/{school['student_b'].id}",
        json={"present": True},
    )

    assert response.status_code == 403


def test_attendance_rejects_student_outside_the_class(client, db, school) -> None:
    session = ClassroomService.start_session(db, class_id=school["class_a"].id)
    sign_in(client, "quan.tri")

    response = client.put(
        f"/api/sessions/{session.id}/attendance/{school['student_b'].id}",
        json={"present": True},
    )

    assert response.status_code == 404


def test_history_is_limited_to_the_class(client, db, school) -> None:
    ClassroomService.start_session(db, "Của lớp B", class_id=school["class_b"].id)
    ClassroomService.start_session(db, "Của lớp A", class_id=school["class_a"].id)
    sign_in(client, "gv.a")

    titles = [
        item["title"]
        for item in client.get(f"/api/sessions?class_id={school['class_a'].id}").json()
    ]

    assert titles == ["Của lớp A"]


def test_active_session_is_per_class(client, db, school) -> None:
    ClassroomService.start_session(db, class_id=school["class_b"].id)
    sign_in(client, "gv.a")

    response = client.get(f"/api/sessions/active?class_id={school['class_a'].id}")

    assert response.json() is None


def test_admin_assigns_teacher_who_gains_access(client, db, school) -> None:
    sign_in(client, "quan.tri")
    class_id, teacher_id = school["class_b"].id, school["teacher_a"].id

    assert (
        client.put(f"/api/classes/{class_id}/teachers/{teacher_id}").status_code == 200
    )

    assert ClassService.is_assigned(db, class_id, teacher_id)


def test_admin_adds_existing_student_by_code(client, db, school) -> None:
    sign_in(client, "quan.tri")

    response = client.post(
        f"/api/classes/{school['class_b'].id}/students",
        json={"student_code": "A1"},
    )

    assert response.status_code == 200
    codes = {s.student_code for s in StudentService.list_all(db, school["class_b"].id)}
    assert codes == {"A1", "B1"}


def test_teacher_cannot_add_existing_student_by_code(client, school) -> None:
    sign_in(client, "gv.a")

    response = client.post(
        f"/api/classes/{school['class_a'].id}/students",
        json={"student_code": "B1"},
    )

    assert response.status_code == 403


def test_unassigned_student_does_not_join_active_class_sessions(db: Session, school) -> None:
    session_a = ClassroomService.start_session(db, class_id=school["class_a"].id)

    unassigned = StudentService.register(db, "U1", "Chưa xếp lớp")

    enrolled_ids = {
        state.student_id for state in ClassroomService.attendance(db, session_a.id)
    }
    assert unassigned.id not in enrolled_ids


def test_archived_class_rejects_new_sessions_and_students(db: Session, school) -> None:
    ClassService.update(db, school["class_a"].id, is_archived=True)

    with pytest.raises(DomainError, match="lưu trữ"):
        ClassroomService.start_session(db, class_id=school["class_a"].id)
    with pytest.raises(DomainError, match="lưu trữ"):
        StudentService.register(
            db, "A9", "Học sinh mới", class_ids=[school["class_a"].id]
        )
    with pytest.raises(DomainError, match="lưu trữ"):
        ClassService.add_student(db, school["class_a"].id, school["student_b"].id)


def test_cannot_archive_class_with_active_session(db: Session, school) -> None:
    ClassroomService.start_session(db, class_id=school["class_a"].id)

    with pytest.raises(DomainError, match="phiên học"):
        ClassService.update(db, school["class_a"].id, is_archived=True)


def test_mark_present_ignores_student_removed_from_class(db: Session, school) -> None:
    session_a = ClassroomService.start_session(db, class_id=school["class_a"].id)

    changed = ClassroomService.mark_present(
        db, session_a.id, school["student_b"].id
    )

    assert changed is False
    enrolled_ids = {
        state.student_id for state in ClassroomService.attendance(db, session_a.id)
    }
    assert school["student_b"].id not in enrolled_ids


def test_admin_can_list_archived_classes_when_requested(client, db, school) -> None:
    ClassService.update(db, school["class_a"].id, is_archived=True)

    sign_in(client, "gv.a")
    teacher_classes = client.get("/api/classes?include_archived=true").json()
    assert [item["id"] for item in teacher_classes] == []

    client.post("/api/auth/logout")
    client.cookies.clear()
    sign_in(client, "quan.tri")
    active_only = client.get("/api/classes").json()
    with_archived = client.get("/api/classes?include_archived=true").json()
    assert [item["name"] for item in active_only] == ["Văn 7B"]
    assert {item["name"] for item in with_archived} == {"Toán 7A", "Văn 7B"}


def test_class_attendance_report_summarizes_sessions_and_respects_access(
    client, db, school
) -> None:
    s1 = ClassroomService.start_session(db, title="Tiết 1", class_id=school["class_a"].id)
    ClassroomService.set_attendance(db, s1.id, school["student_a"].id, True)
    ClassroomService.pick_random(db, s1.id)
    ClassroomService.finish_session(db, s1.id)

    s2 = ClassroomService.start_session(db, title="Tiết 2", class_id=school["class_a"].id)
    ClassroomService.set_attendance(db, s2.id, school["student_a"].id, False, note="nghỉ")
    ClassroomService.finish_session(db, s2.id)

    sign_in(client, "gv.b")
    assert client.get(f"/api/classes/{school['class_a'].id}/report").status_code == 403

    client.post("/api/auth/logout")
    client.cookies.clear()
    sign_in(client, "gv.a")
    report = client.get(f"/api/classes/{school['class_a'].id}/report").json()
    assert report["total_sessions"] == 2
    assert len(report["students"]) == 1
    row = report["students"][0]
    assert row["student_code"] == "A1"
    assert row["present"] == 1
    assert row["absent"] == 1
    assert row["called"] == 1
    assert row["attendance_rate"] == 50
