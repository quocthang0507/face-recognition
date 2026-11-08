"""Running a lesson: attendance, finishing, history and CSV export."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import mark_attendance, seed_students, start_session

pytestmark = pytest.mark.e2e


def test_starting_session_shows_title_and_locks_start(dashboard) -> None:
    start_session(dashboard, "Toán 7A - Tiết 2")

    expect(dashboard.locator("#session-stat")).to_have_text("Toán 7A - Tiết 2")
    expect(dashboard.locator("#start-session-button")).to_be_disabled()


def test_clicking_status_marks_student_present(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    start_session(dashboard)

    dashboard.locator('[data-attendance][data-present="0"]').click()

    expect(dashboard.locator("#present-stat")).to_have_text("1 / 1")


def test_marking_absent_records_reason(dashboard, prompt_answer) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    start_session(dashboard)
    mark_attendance(dashboard, "HS001", present=True)
    prompt_answer["text"] = "có phép"

    dashboard.locator('[data-attendance][data-present="1"]').click()

    expect(dashboard.locator("#present-stat")).to_have_text("0 / 1")
    expect(dashboard.locator("#student-list")).to_contain_text("có phép")


def test_finishing_session_shows_report_and_resets(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"), ("HS002", "Trần Thị Bình"))
    start_session(dashboard)
    mark_attendance(dashboard, "HS001", present=True)

    dashboard.click("#finish-session-button")

    expect(dashboard.locator("#report-body")).to_contain_text("Trần Thị Bình (HS002)")
    dashboard.click("#close-report-button")
    expect(dashboard.locator("#session-stat")).to_have_text("Chưa bắt đầu")
    expect(dashboard.locator("#session-title-input")).to_have_value("")


def test_history_opens_details_of_finished_session(dashboard) -> None:
    start_session(dashboard, "Buổi để xem lịch sử")
    dashboard.click("#finish-session-button")
    dashboard.click("#close-report-button")

    dashboard.click("#history-button")
    item = dashboard.locator(".history-item", has_text="Buổi để xem lịch sử").first
    item.locator("[data-report]").click()

    expect(dashboard.locator("#report-title")).to_have_text("Buổi để xem lịch sử")


def test_csv_export_opens_in_excel_with_student_names(dashboard, tmp_path) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    start_session(dashboard)

    with dashboard.expect_download() as download:
        dashboard.click("#export-session-button")
    target = tmp_path / "export.csv"
    download.value.save_as(target)

    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "Nguyễn Văn An" in raw.decode("utf-8-sig")
