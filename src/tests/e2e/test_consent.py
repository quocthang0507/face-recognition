"""Recording biometric consent from the class list."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import seed_students

pytestmark = pytest.mark.e2e


def consent_select(page):
    return page.locator("#student-list [data-consent]")


def test_new_student_shows_waiting_for_consent(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))

    expect(consent_select(dashboard)).to_have_value("PENDING")
    expect(dashboard.locator("#consent-note")).to_contain_text("1 học sinh")


def test_recording_consent_clears_the_waiting_note(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))

    consent_select(dashboard).select_option("GRANTED")

    expect(consent_select(dashboard)).to_have_value("GRANTED")
    expect(dashboard.locator("#consent-note")).to_have_text("")


def test_server_refuses_face_image_without_consent(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    student_id = dashboard.evaluate("state.students[0].id")

    response = dashboard.request.post(
        f"/api/students/{student_id}/face",
        multipart={
            "image": {"name": "a.jpg", "mimeType": "image/jpeg", "buffer": b"jpeg"}
        },
    )

    assert response.status == 409


def test_registering_with_consent_box_marks_student_consented(dashboard) -> None:
    dashboard.click("#toggle-register-button")
    dashboard.fill('input[name="student_code"]', "HS005")
    dashboard.fill('input[name="fullname"]', "Phạm Thị Dung")
    dashboard.check('input[name="consent"]')

    dashboard.click('#register-form button[type="submit"]')

    expect(consent_select(dashboard)).to_have_value("GRANTED")


def test_registering_without_consent_stays_waiting(dashboard) -> None:
    dashboard.click("#toggle-register-button")
    dashboard.fill('input[name="student_code"]', "HS006")
    dashboard.fill('input[name="fullname"]', "Phạm Văn Em")

    dashboard.click('#register-form button[type="submit"]')

    expect(consent_select(dashboard)).to_have_value("PENDING")


def test_tv_mode_hides_consent_column(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))

    dashboard.click("#display-tv")

    expect(consent_select(dashboard)).to_be_hidden()
    expect(dashboard.locator("#consent-note")).to_be_hidden()


def test_admin_sees_the_access_log_section(dashboard) -> None:
    dashboard.click("#admin-button")

    expect(dashboard.locator("#admin-access")).to_be_visible()
