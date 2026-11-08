"""Tests for teacher accounts, password storage and role checks."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from src import auth
from src.models import User
from src.services import DomainError, UserService


@pytest.fixture
def db(session_factory: sessionmaker) -> Iterator[Session]:
    with session_factory() as session:
        yield session


def create_teacher(db: Session, username: str = "gv.an") -> User:
    return UserService.create(db, username, "mat-khau-gv", "Giáo viên An", "TEACHER")


def create_admin(db: Session, username: str = "admin") -> User:
    return UserService.create(db, username, "mat-khau-admin", "Quản trị", "ADMIN")


def login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def test_password_hash_verifies_only_the_original_password() -> None:
    stored = auth.hash_password("mat-khau-dung")

    assert auth.verify_password("mat-khau-dung", stored)
    assert not auth.verify_password("mat-khau-sai", stored)


def test_password_is_not_stored_in_plain_text() -> None:
    assert "mat-khau-dung" not in auth.hash_password("mat-khau-dung")


def test_same_password_gets_different_hashes() -> None:
    assert auth.hash_password("giong-nhau") != auth.hash_password("giong-nhau")


def test_malformed_stored_hash_never_verifies() -> None:
    assert not auth.verify_password("bat-ky", "khong-phai-hash")


def test_token_identifies_the_user() -> None:
    token = auth.issue_user_token(42, now=100)

    assert auth.verify_user_token(token, now=101).user_id == 42


def test_username_is_normalized_and_unique(db: Session) -> None:
    user = UserService.create(db, "  GV.An ", "mat-khau-gv", "An", "TEACHER")

    assert user.username == "gv.an"
    with pytest.raises(DomainError, match="đã tồn tại"):
        UserService.create(db, "gv.an", "mat-khau-gv", "An 2", "TEACHER")


def test_short_password_is_rejected(db: Session) -> None:
    with pytest.raises(DomainError, match="8 ký tự"):
        UserService.create(db, "gv.an", "ngan", "An", "TEACHER")


def test_unknown_role_is_rejected(db: Session) -> None:
    with pytest.raises(DomainError, match="Vai trò"):
        UserService.create(db, "gv.an", "mat-khau-gv", "An", "STUDENT")


def test_authenticate_rejects_wrong_password(db: Session) -> None:
    create_teacher(db)

    assert UserService.authenticate(db, "gv.an", "sai-mat-khau") is None


def test_authenticate_rejects_disabled_account(db: Session) -> None:
    teacher = create_teacher(db)
    UserService.update(db, teacher.id, is_active=False)

    assert UserService.authenticate(db, "gv.an", "mat-khau-gv") is None


def test_first_start_creates_admin_from_existing_password(db: Session) -> None:
    UserService.ensure_admin(db, "mat-khau-cu")

    assert UserService.authenticate(db, "admin", "mat-khau-cu").role == "ADMIN"


def test_later_starts_do_not_reset_the_admin(db: Session) -> None:
    UserService.ensure_admin(db, "mat-khau-cu")
    admin = UserService.authenticate(db, "admin", "mat-khau-cu")
    UserService.update(db, admin.id, password="mat-khau-moi")

    UserService.ensure_admin(db, "mat-khau-cu")

    assert UserService.authenticate(db, "admin", "mat-khau-moi") is not None
    assert UserService.authenticate(db, "admin", "mat-khau-cu") is None


def test_last_active_admin_cannot_be_disabled(db: Session) -> None:
    admin = create_admin(db)

    with pytest.raises(DomainError, match="Quản trị"):
        UserService.update(db, admin.id, is_active=False)


def test_last_active_admin_cannot_be_demoted(db: Session) -> None:
    admin = create_admin(db)

    with pytest.raises(DomainError, match="Quản trị"):
        UserService.update(db, admin.id, role="TEACHER")


def test_admin_can_be_disabled_when_another_remains(db: Session) -> None:
    first = create_admin(db)
    create_admin(db, "admin2")

    assert UserService.update(db, first.id, is_active=False).is_active is False


def test_login_sets_cookie_and_status_reports_user(
    client: TestClient, db: Session
) -> None:
    create_teacher(db)

    assert login(client, "gv.an", "mat-khau-gv").status_code == 200

    user = client.get("/api/auth/status").json()["user"]
    assert user["username"] == "gv.an"
    assert user["role"] == "TEACHER"
    assert "password_hash" not in user


def test_wrong_login_is_refused(client: TestClient, db: Session) -> None:
    create_teacher(db)

    assert login(client, "gv.an", "sai-mat-khau").status_code == 401


def test_api_requires_login(client: TestClient) -> None:
    assert client.get("/api/students").status_code == 401


def test_disabled_account_loses_access_immediately(
    client: TestClient, db: Session
) -> None:
    teacher = create_teacher(db)
    login(client, "gv.an", "mat-khau-gv")

    UserService.update(db, teacher.id, is_active=False)

    assert client.get("/api/auth/status").status_code == 401


def test_teacher_cannot_manage_accounts(client: TestClient, db: Session) -> None:
    create_teacher(db)
    login(client, "gv.an", "mat-khau-gv")

    assert client.get("/api/users").status_code == 403
    response = client.post(
        "/api/users",
        json={
            "username": "gv.moi",
            "password": "mat-khau-gv",
            "fullname": "Mới",
            "role": "ADMIN",
        },
    )
    assert response.status_code == 403


def test_admin_creates_account_that_can_sign_in(
    client: TestClient, db: Session
) -> None:
    create_admin(db)
    login(client, "admin", "mat-khau-admin")

    response = client.post(
        "/api/users",
        json={
            "username": "gv.moi",
            "password": "mat-khau-gv",
            "fullname": "Giáo viên Mới",
            "role": "TEACHER",
        },
    )

    assert response.status_code == 200
    assert "password_hash" not in response.json()
    assert UserService.authenticate(db, "gv.moi", "mat-khau-gv") is not None


def test_admin_resets_a_password(client: TestClient, db: Session) -> None:
    teacher = create_teacher(db)
    create_admin(db)
    login(client, "admin", "mat-khau-admin")

    client.patch(f"/api/users/{teacher.id}", json={"password": "mat-khau-moi"})

    db.expire_all()
    assert UserService.authenticate(db, "gv.an", "mat-khau-moi") is not None
