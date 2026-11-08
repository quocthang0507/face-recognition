"""Managing accounts from the admin panel."""

from __future__ import annotations

from uuid import uuid4

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def open_accounts(page) -> None:
    page.click("#admin-button")
    page.wait_for_selector("#admin-modal.visible")


def create_teacher(page, username: str) -> None:
    open_accounts(page)
    page.fill("#new-user-username", username)
    page.fill("#new-user-fullname", "Giáo viên Thử")
    page.fill("#new-user-password", "mat-khau-giao-vien")
    page.click('#new-user-form button[type="submit"]')
    expect(page.locator("#admin-users")).to_contain_text(username)


def sign_in(page, username: str, password: str) -> None:
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('#login-form button[type="submit"]')


def test_admin_creates_teacher_who_can_sign_in(dashboard) -> None:
    username = f"gv.{uuid4().hex[:8]}"
    create_teacher(dashboard, username)
    dashboard.click("#close-admin-button")
    dashboard.click("#logout-button")
    expect(dashboard.locator("#login-modal")).to_be_visible()

    sign_in(dashboard, username, "mat-khau-giao-vien")

    expect(dashboard.locator("#login-modal")).to_be_hidden()
    expect(dashboard.locator("#current-user")).to_contain_text("Giáo viên Thử")


def test_teacher_does_not_see_admin_panel(dashboard) -> None:
    username = f"gv.{uuid4().hex[:8]}"
    create_teacher(dashboard, username)
    dashboard.click("#close-admin-button")
    dashboard.click("#logout-button")

    sign_in(dashboard, username, "mat-khau-giao-vien")

    expect(dashboard.locator("#current-user")).to_contain_text("Giáo viên Thử")
    expect(dashboard.locator("#admin-button")).to_be_hidden()


def test_disabled_teacher_cannot_sign_in(dashboard) -> None:
    username = f"gv.{uuid4().hex[:8]}"
    create_teacher(dashboard, username)
    row = dashboard.locator("#admin-users tr", has_text=username)

    row.locator("[data-user-toggle]").click()

    expect(row).to_contain_text("Đã khóa")
    dashboard.click("#close-admin-button")
    dashboard.click("#logout-button")
    sign_in(dashboard, username, "mat-khau-giao-vien")
    expect(dashboard.locator("#login-error")).to_contain_text("không chính xác")


def test_short_password_shows_reason(dashboard) -> None:
    open_accounts(dashboard)
    dashboard.fill("#new-user-username", f"gv.{uuid4().hex[:8]}")
    dashboard.fill("#new-user-fullname", "Giáo viên Thử")
    dashboard.fill("#new-user-password", "ngan")

    dashboard.click('#new-user-form button[type="submit"]')

    expect(dashboard.locator(".toast.error")).to_contain_text("8 ký tự")


def test_tv_mode_hides_admin_button(dashboard) -> None:
    dashboard.click("#display-tv")

    expect(dashboard.locator("#admin-button")).to_be_hidden()
