"""The teacher-computer and classroom-TV display modes."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import (
    close_settings,
    mark_attendance,
    open_settings,
    reload_dashboard,
    seed_students,
    start_session,
)

pytestmark = pytest.mark.e2e

ALERT = "addAlert({behavior_type:'TALKING',label:'Nói chuyện',fullname:'Tên Nhạy Cảm'})"
CHECK_IN = "announceCheckIn({fullname: 'Điểm Danh Thử'})"
FACE_LABELS = """() => {
  const seen = [];
  const original = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text, ...rest) {
    seen.push(text);
    return original.call(this, text, ...rest);
  };
  state.lastPayload = {
    frame_size: {width: 640, height: 360},
    behaviors: [],
    faces: [{student_id: 1, fullname: "Tên Nhạy Cảm", confidence: 91,
             box: {x: 10, y: 40, width: 80, height: 80}}],
  };
  drawOverlay();
  CanvasRenderingContext2D.prototype.fillText = original;
  state.lastPayload = null;
  clearOverlay();
  return seen;
}"""


@pytest.fixture
def lesson(dashboard):
    """A running lesson with one absent student whose absence has a reason."""

    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    start_session(dashboard)
    mark_attendance(dashboard, "HS001", present=False, note="có phép")
    return dashboard


def use_tv(page) -> None:
    page.click("#display-tv")


def test_teacher_computer_is_the_default(dashboard) -> None:
    expect(dashboard.locator("html")).to_have_attribute("data-display", "desk")


@pytest.mark.parametrize(
    "selector",
    [
        "#toggle-register-button",
        "#clear-alerts-button",
        "#reset-called-button",
        "#export-session-button",
        ".behavior-toggle >> nth=0",
        "[data-delete]",
    ],
)
def test_tv_hides_admin_tools(lesson, selector: str) -> None:
    use_tv(lesson)

    expect(lesson.locator(selector)).to_be_hidden()


def test_tv_keeps_lesson_controls(lesson) -> None:
    use_tv(lesson)

    expect(lesson.locator("#pick-button")).to_be_visible()
    expect(lesson.locator("#student-list")).to_be_visible()


def test_tv_choice_survives_reload(dashboard) -> None:
    use_tv(dashboard)

    reload_dashboard(dashboard)

    expect(dashboard.locator("html")).to_have_attribute("data-display", "tv")
    expect(dashboard.locator("#display-tv")).to_have_attribute("aria-pressed", "true")


def test_tv_always_hides_names_in_alerts(dashboard) -> None:
    use_tv(dashboard)

    dashboard.evaluate(ALERT)

    expect(dashboard.locator("#toast-container")).not_to_contain_text("Tên Nhạy Cảm")


def test_tv_hides_absence_reason_in_roster(lesson) -> None:
    use_tv(lesson)

    assert "có phép" not in lesson.inner_text("#student-list")


def test_tv_hides_absence_reason_in_report(lesson) -> None:
    use_tv(lesson)

    lesson.evaluate("showSessionReport(state.session.id)")

    expect(lesson.locator("#report-body")).to_contain_text("Nguyễn Văn An")
    assert "có phép" not in lesson.inner_text("#report-body")


def test_face_label_is_anonymous_on_tv(dashboard) -> None:
    use_tv(dashboard)

    assert dashboard.evaluate(FACE_LABELS) == ["Đã nhận diện"]


def test_face_label_shows_name_on_teacher_computer(dashboard) -> None:
    assert dashboard.evaluate(FACE_LABELS) == ["Tên Nhạy Cảm 91%"]


def test_teacher_computer_shows_absence_reason(lesson) -> None:
    expect(lesson.locator("#student-list")).to_contain_text("có phép")


def test_tv_hides_check_in_toast_by_default(dashboard) -> None:
    use_tv(dashboard)

    dashboard.evaluate(CHECK_IN)

    expect(dashboard.locator("#toast-container")).not_to_contain_text("Điểm Danh Thử")


def test_tv_hides_missing_face_note_by_default(lesson) -> None:
    use_tv(lesson)

    expect(lesson.locator(".missing-face")).to_be_hidden()


def test_turning_off_tv_options_shows_them_again(lesson) -> None:
    use_tv(lesson)
    open_settings(lesson)
    lesson.uncheck("#tv-hide-checkin-checkbox-modal")
    lesson.uncheck("#tv-hide-missing-face-checkbox-modal")
    close_settings(lesson)

    lesson.evaluate(CHECK_IN)

    expect(lesson.locator(".missing-face")).to_be_visible()
    expect(lesson.locator("#toast-container")).to_contain_text("Điểm Danh Thử")


def test_tv_options_do_not_affect_teacher_computer(lesson) -> None:
    lesson.evaluate(CHECK_IN)

    expect(lesson.locator(".missing-face")).to_be_visible()
    expect(lesson.locator("#toast-container")).to_contain_text("Điểm Danh Thử")
