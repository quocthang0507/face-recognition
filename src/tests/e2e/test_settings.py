"""The settings dialog and behavior toggles."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import close_settings, open_settings, reload_dashboard

pytestmark = pytest.mark.e2e

ALERT = "addAlert({behavior_type:'TALKING',label:'Nói chuyện',fullname:'Tên Nhạy Cảm'})"


def test_theme_and_fps_survive_reload(dashboard) -> None:
    open_settings(dashboard)
    dashboard.select_option("#theme-select-modal", "dark")
    dashboard.select_option("#video-fps-select-modal", "200")
    close_settings(dashboard)

    reload_dashboard(dashboard)

    expect(dashboard.locator("html")).to_have_attribute("data-theme", "dark")
    expect(dashboard.locator("#video-fps-select-modal")).to_have_value("200")


def test_turning_off_speech_disables_voice_choice(dashboard) -> None:
    open_settings(dashboard)

    dashboard.uncheck("#tts-alert-checkbox-modal")

    expect(dashboard.locator("#tts-voice-select-modal")).to_be_disabled()


def test_escape_closes_settings(dashboard) -> None:
    open_settings(dashboard)

    dashboard.keyboard.press("Escape")

    expect(dashboard.locator("#settings-modal")).to_be_hidden()


def test_clicking_outside_closes_settings(dashboard) -> None:
    open_settings(dashboard)

    dashboard.mouse.click(5, 5)

    expect(dashboard.locator("#settings-modal")).to_be_hidden()


def test_behavior_toggle_reports_its_state(dashboard) -> None:
    toggle = dashboard.locator('.behavior-toggle[data-behavior="TALKING"]')

    toggle.click()

    expect(toggle).to_have_attribute("aria-pressed", "false")


def test_hiding_names_applies_to_alerts_on_teacher_computer(dashboard) -> None:
    open_settings(dashboard)
    dashboard.check("#hide-alert-names-checkbox-modal")
    close_settings(dashboard)

    dashboard.evaluate(ALERT)

    expect(dashboard.locator("#alert-list")).to_contain_text("Một học sinh")
    expect(dashboard.locator("#alert-list")).not_to_contain_text("Tên Nhạy Cảm")
    expect(dashboard.locator("#toast-container")).not_to_contain_text("Tên Nhạy Cảm")
