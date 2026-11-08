"""Small actions shared by the browser tests."""

from __future__ import annotations

ADMIN_USERNAME = "admin"
PASSWORD = "e2e-test-password"
PICK_TIMEOUT_MS = 15000


def seed_students(page, *students: tuple[str, str]) -> None:
    """Create students without photos through the API and reload the roster."""

    class_id = page.evaluate("state.classId")
    for code, name in students:
        response = page.request.post(
            "/api/students/register",
            multipart={"student_code": code, "fullname": name, "class_id": class_id},
        )
        assert response.ok, response.text()
    reload_dashboard(page)


def reload_dashboard(page) -> None:
    page.reload()
    page.wait_for_selector("#student-list tr")


def start_session(page, title: str = "Toán 7A - Tiết 2") -> None:
    page.fill("#session-title-input", title)
    page.click("#start-session-button")
    page.wait_for_selector("#finish-session-button:enabled")


def mark_attendance(page, code: str, present: bool, note: str | None = None) -> None:
    """Record attendance through the API for tests that only need the result."""

    session_id = page.evaluate("state.session.id")
    student_id = page.evaluate(
        "code => state.students.find((s) => s.student_code === code).id", code
    )
    response = page.request.put(
        f"/api/sessions/{session_id}/attendance/{student_id}",
        data={"present": present, "note": note},
    )
    assert response.ok, response.text()
    reload_dashboard(page)


def open_settings(page) -> None:
    page.click("#settings-button")
    page.wait_for_selector("#settings-modal.visible")


def close_settings(page) -> None:
    page.click("#close-settings-button")
