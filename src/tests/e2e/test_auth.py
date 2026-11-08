"""Signing in and out of the dashboard."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import ADMIN_USERNAME, PASSWORD

pytestmark = pytest.mark.e2e


def test_signed_out_visitor_sees_login(anonymous_page) -> None:
    anonymous_page.goto("/")

    expect(anonymous_page.locator("#login-modal")).to_be_visible()


def test_wrong_password_shows_reason_and_stays_signed_out(anonymous_page) -> None:
    anonymous_page.goto("/")
    anonymous_page.fill('input[name="username"]', ADMIN_USERNAME)
    anonymous_page.fill('input[name="password"]', "sai-mat-khau")
    anonymous_page.click('#login-form button[type="submit"]')

    expect(anonymous_page.locator("#login-error")).to_have_text(
        "Tên đăng nhập hoặc mật khẩu không chính xác"
    )
    expect(anonymous_page.locator("#login-modal")).to_be_visible()


def test_correct_password_opens_dashboard(anonymous_page) -> None:
    anonymous_page.goto("/")
    anonymous_page.fill('input[name="username"]', ADMIN_USERNAME)
    anonymous_page.fill('input[name="password"]', PASSWORD)
    anonymous_page.click('#login-form button[type="submit"]')

    expect(anonymous_page.locator("#login-modal")).to_be_hidden()


def test_logout_returns_to_login_and_locks_api(dashboard) -> None:
    dashboard.click("#logout-button")

    expect(dashboard.locator("#login-modal")).to_be_visible()
    assert dashboard.request.get("/api/students").status == 401
