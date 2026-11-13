"""Registering and removing students from the dashboard."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import seed_students

pytestmark = pytest.mark.e2e


def submit_registration(page, code: str, name: str) -> None:
    if page.locator("#register-form.hidden").count():
        page.click("#toggle-register-button")
    page.fill('input[name="student_code"]', code)
    page.fill('input[name="fullname"]', name)
    page.click('#register-form button[type="submit"]')


def test_empty_roster_explains_how_to_add_students(dashboard) -> None:
    expect(dashboard.locator("#student-list")).to_contain_text("Đăng ký học sinh")


def test_registering_without_photo_adds_row_with_warning(dashboard) -> None:
    submit_registration(dashboard, "HS001", "Nguyễn Văn An")

    row = dashboard.locator("#student-list tr", has_text="Nguyễn Văn An")
    expect(row).to_contain_text("Chưa có ảnh khuôn mặt")


def test_duplicate_code_is_rejected(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))

    submit_registration(dashboard, "HS001", "Trùng Mã")

    expect(dashboard.locator(".toast.error")).to_have_text("Mã học sinh đã tồn tại")
    expect(dashboard.locator("#student-list tr")).to_have_count(1)


def test_whitespace_only_name_is_rejected(dashboard) -> None:
    submit_registration(dashboard, "HS009", "   ")

    expect(dashboard.locator(".toast.error")).to_be_visible()
    expect(dashboard.locator("#student-list")).not_to_contain_text("HS009")


def test_name_with_markup_is_shown_literally(dashboard) -> None:
    seed_students(dashboard, ("HS003", "<b>Lê</b> Cường"))

    row = dashboard.locator("#student-list tr")
    expect(row.locator(".mini-avatar")).to_have_text("<C")
    expect(row.locator("b")).to_have_count(0)


def test_deleting_student_removes_row(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"), ("HS002", "Trần Thị Bình"))

    row = dashboard.locator("#student-list tr", has_text="Trần Thị Bình")
    row.locator("[data-delete]").click()

    expect(dashboard.locator("#student-list tr")).to_have_count(1)


def test_student_consent_history_modal(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    row = dashboard.locator("#student-list tr", has_text="Nguyễn Văn An")
    row.locator("[data-consent]").select_option("GRANTED")
    expect(row.locator("[data-consent]")).to_have_value("GRANTED")

    row.locator("[data-consent-history]").click()
    expect(dashboard.locator("#report-title")).to_contain_text("Nguyễn Văn An")
    expect(dashboard.locator("#report-body")).to_contain_text("Đã đồng ý")
