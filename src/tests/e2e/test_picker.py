"""The random student picker."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import PICK_TIMEOUT_MS, mark_attendance, seed_students, start_session

pytestmark = pytest.mark.e2e


def test_picker_only_calls_present_students(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"), ("HS002", "Trần Thị Bình"))
    start_session(dashboard)
    mark_attendance(dashboard, "HS002", present=True)

    dashboard.click("#pick-button")

    expect(dashboard.locator("#picked-code")).to_have_text(
        "HS002", timeout=PICK_TIMEOUT_MS
    )


def test_reset_opens_new_round(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    start_session(dashboard)
    dashboard.click("#pick-button")
    expect(dashboard.locator("#picked-code")).to_have_text(
        "HS001", timeout=PICK_TIMEOUT_MS
    )
    dashboard.click("#close-picker-button")
    expect(dashboard.locator("#called-stat")).to_have_text("1")

    dashboard.click("#reset-called-button")

    expect(dashboard.locator("#called-stat")).to_have_text("0")


def test_initials_stay_visible_while_shuffling_after_photo_pick(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    start_session(dashboard)
    picked = {
        "id": 1,
        "fullname": "Có Ảnh",
        "student_code": "HS777",
        "avatar_url": "/static/css/style.css",
    }
    dashboard.route("**/pick", lambda route: route.fulfill(json=picked))
    code = dashboard.locator("#picked-code")
    dashboard.click("#pick-button")
    expect(code).to_have_text("HS777", timeout=PICK_TIMEOUT_MS)
    dashboard.click("#close-picker-button")

    dashboard.click("#pick-button")

    expect(dashboard.locator("#picked-initials")).to_be_visible()
    expect(code).to_have_text("HS777", timeout=PICK_TIMEOUT_MS)
