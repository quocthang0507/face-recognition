"""Regression tests for the OWASP review findings."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src import storage as storage_module
from src.config import BASE_DIR, Settings
from src.services import ClassroomService, ClassService, StudentService, UserService
from src.storage import PrivateStorage

COOKIE = "classroom_teacher"
PUBLISHED_SECRET = "development-only-change-this-secret"


@pytest.fixture
def signed_in(client: TestClient, session_factory: sessionmaker) -> TestClient:
    with session_factory() as db:
        UserService.create(db, "quan.tri", "mat-khau-goc", "QT", "ADMIN")
    response = client.post(
        "/api/auth/login", json={"username": "quan.tri", "password": "mat-khau-goc"}
    )
    assert response.status_code == 200
    return client


def test_password_change_ends_existing_sessions(signed_in, session_factory) -> None:
    with session_factory() as db:
        user = UserService.authenticate(db, "quan.tri", "mat-khau-goc")
        UserService.update(db, user.id, password="mat-khau-moi-1")

    assert signed_in.get("/api/auth/status").status_code == 401


def test_logged_out_token_cannot_be_replayed(signed_in) -> None:
    token = signed_in.cookies.get(COOKIE)

    signed_in.post("/api/auth/logout")
    signed_in.cookies.set(COOKIE, token)

    assert signed_in.get("/api/auth/status").status_code == 401


def test_logout_with_a_broken_token_still_succeeds(client: TestClient) -> None:
    client.cookies.set(COOKIE, "khong-hop-le")

    assert client.post("/api/auth/logout").status_code == 200


def test_missing_secret_is_generated_and_kept(tmp_path: Path) -> None:
    first = Settings(token_secret="", data_dir=tmp_path).signing_key
    second = Settings(token_secret="", data_dir=tmp_path).signing_key

    assert first == second
    assert len(first) >= 32
    assert first != PUBLISHED_SECRET


def test_published_secret_is_never_used_to_sign(tmp_path: Path) -> None:
    settings = Settings(token_secret=PUBLISHED_SECRET, data_dir=tmp_path)

    assert settings.signing_key != PUBLISHED_SECRET


def test_configured_secret_is_used(tmp_path: Path) -> None:
    settings = Settings(token_secret="khoa-rieng-cua-truong", data_dir=tmp_path)

    assert settings.signing_key == "khoa-rieng-cua-truong"


def test_pages_send_security_headers(client: TestClient) -> None:
    headers = client.get("/").headers

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "unsafe-inline" not in headers["content-security-policy"]


def test_api_responses_are_not_cached(signed_in) -> None:
    assert signed_in.get("/api/auth/status").headers["cache-control"] == "no-store"


def test_dashboard_has_no_inline_script_or_style() -> None:
    html = (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")

    assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html) == []
    assert re.findall(r"\sstyle=", html) == []


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_documentation_is_not_public(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    "formula", ['=HYPERLINK("http://x","y")', "+1+1", "-1+1", "@SUM(A1)"]
)
def test_csv_neutralizes_formulas(signed_in, session_factory, formula: str) -> None:
    with session_factory() as db:
        school_class = ClassService.create(db, "Toán 7A")
        StudentService.register(db, "F1", formula, class_ids=[school_class.id])
        session = ClassroomService.start_session(db, class_id=school_class.id)
        session_id = session.id

    body = signed_in.get(f"/api/sessions/{session_id}/export.csv").text

    assert f"'{formula[0]}" in body


def test_csv_keeps_ordinary_names(signed_in, session_factory) -> None:
    with session_factory() as db:
        school_class = ClassService.create(db, "Toán 7A")
        StudentService.register(db, "F1", "Nguyễn Văn An", class_ids=[school_class.id])
        session = ClassroomService.start_session(db, class_id=school_class.id)
        session_id = session.id

    body = signed_in.get(f"/api/sessions/{session_id}/export.csv").text

    assert ",Nguyễn Văn An," in body


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PrivateStorage:
    monkeypatch.setattr(storage_module, "settings", Settings(data_dir=tmp_path))
    return PrivateStorage()


def test_snapshots_are_encrypted_on_disk(storage, tmp_path: Path) -> None:
    name = storage.save_snapshot(b"\xff\xd8anh-hoc-sinh")

    assert b"anh-hoc-sinh" not in (tmp_path / "snapshots" / name).read_bytes()
    assert storage.read_snapshot(name) == b"\xff\xd8anh-hoc-sinh"


def test_snapshots_saved_before_encryption_stay_readable(
    storage, tmp_path: Path
) -> None:
    (tmp_path / "snapshots" / "cu.jpg").write_bytes(b"\xff\xd8cu")

    assert storage.read_snapshot("cu.jpg") == b"\xff\xd8cu"


def test_login_requires_https_when_secure_transport_only_is_enabled(
    client: TestClient, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import main
    from src.config import Settings

    with session_factory() as db:
        UserService.create(db, "quan.tri", "mat-khau-goc", "QT", "ADMIN")
    monkeypatch.setattr(main, "settings", Settings(secure_transport_only=True))

    response = client.post(
        "/api/auth/login",
        json={"username": "quan.tri", "password": "mat-khau-goc"},
    )

    assert response.status_code == 400
    assert response.cookies.get(COOKIE) is None


def test_cross_origin_mutating_request_is_rejected(
    signed_in: TestClient,
) -> None:
    response = signed_in.post(
        "/api/classes",
        json={"name": "Lớp CSRF"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_cross_site_fetch_metadata_on_mutation_is_rejected(
    signed_in: TestClient,
) -> None:
    response = signed_in.post(
        "/api/classes",
        json={"name": "Lớp CSRF"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


def test_role_change_revokes_existing_session_tokens(
    client: TestClient, session_factory: sessionmaker
) -> None:
    with session_factory() as db:
        admin1 = UserService.create(db, "admin1", "mat-khau-goc", "A1", "ADMIN")
        UserService.create(db, "admin2", "mat-khau-goc", "A2", "ADMIN")
    client.post("/api/auth/login", json={"username": "admin1", "password": "mat-khau-goc"})
    assert client.get("/api/auth/status").status_code == 200

    with session_factory() as db:
        UserService.update(db, admin1.id, role="TEACHER")

    assert client.get("/api/auth/status").status_code == 401


def test_shared_ip_lockout_only_blocks_targeted_username(
    client: TestClient, session_factory: sessionmaker
) -> None:
    with session_factory() as db:
        UserService.create(db, "gv.a", "mat-khau-gv-1", "GV A", "TEACHER")
        UserService.create(db, "gv.b", "mat-khau-gv-2", "GV B", "TEACHER")

    for _ in range(5):
        client.post("/api/auth/login", json={"username": "gv.a", "password": "sai"})

    blocked = client.post(
        "/api/auth/login", json={"username": "gv.a", "password": "mat-khau-gv-1"}
    )
    other_user = client.post(
        "/api/auth/login", json={"username": "gv.b", "password": "mat-khau-gv-2"}
    )

    assert blocked.status_code == 429
    assert other_user.status_code == 200


def test_get_avatar_uses_detected_image_media_type(
    signed_in: TestClient, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import main

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    class FakeStorage:
        def read_avatar(self, _name: str) -> bytes:
            return png_bytes

    monkeypatch.setattr(main, "storage", FakeStorage())
    with session_factory() as db:
        school_class = ClassService.create(db, "7A")
        StudentService.register(
            db, "S1", "An", [1.0, 0.0], "avatar-png.enc", class_ids=[school_class.id]
        )

    response = signed_in.get("/api/avatars/avatar-png.enc")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_websocket_rejects_oversized_frame(
    signed_in: TestClient, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import main

    with session_factory() as db:
        school_class = ClassService.create(db, "7A")
        class_id = school_class.id
    monkeypatch.setattr(main, "MAX_WS_FRAME_BYTES", 32)

    with signed_in.websocket_connect(f"/ws?class_id={class_id}") as ws:
        ws.send_bytes(b"\xff\xd8" + b"x" * 64)
        message = ws.receive_json()

    assert message["type"] == "error"
    assert "kích thước" in message["message"].lower() or "dung lượng" in message["message"].lower()


def test_websocket_revokes_active_stream_after_logout(
    signed_in: TestClient, session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.websockets import WebSocketDisconnect
    from src import main

    with session_factory() as db:
        school_class = ClassService.create(db, "7A")
        class_id = school_class.id
    monkeypatch.setattr(main, "WS_REVERIFY_SECONDS", 0.0)

    with signed_in.websocket_connect(f"/ws?class_id={class_id}") as ws:
        with session_factory() as db:
            user = UserService.authenticate(db, "quan.tri", "mat-khau-goc")
            UserService.revoke_tokens(db, user)
        ws.send_json({"type": "behavior_config", "enabled_behaviors": ["SLEEPING"]})
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()

    assert exc_info.value.code == 1008
