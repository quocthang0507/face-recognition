"""Choosing classes and limiting what each teacher can see."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from .helpers import seed_students

pytestmark = pytest.mark.e2e


def unique(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8]}"


def create_teacher(page, username: str, fullname: str) -> None:
    response = page.request.post(
        "/api/users",
        data={
            "username": username,
            "password": "mat-khau-giao-vien",
            "fullname": fullname,
        },
    )
    assert response.ok, response.text()


def create_class(page, name: str) -> None:
    page.click("#admin-button")
    page.fill("#new-class-name", name)
    page.click('#new-class-form button[type="submit"]')
    expect(page.locator("#admin-class-list")).to_contain_text(name)


def sign_in_as(page, username: str) -> None:
    page.click("#close-admin-button")
    page.click("#logout-button")
    expect(page.locator("#login-modal")).to_be_visible()
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', "mat-khau-giao-vien")
    page.click('#login-form button[type="submit"]')
    expect(page.locator("#login-modal")).to_be_hidden()


def test_teacher_sees_only_the_assigned_class(dashboard) -> None:
    username, fullname, class_name = unique("gv."), unique("GV "), unique("Zz ")
    create_teacher(dashboard, username, fullname)
    create_class(dashboard, class_name)
    card = dashboard.locator(".admin-class", has_text=class_name)
    card.get_by_label(fullname).check()
    expect(card.get_by_label(fullname)).to_be_checked()

    sign_in_as(dashboard, username)

    expect(dashboard.locator("#class-select option")).to_have_text([class_name])


def test_teacher_without_a_class_is_told_why_the_page_is_empty(dashboard) -> None:
    username = unique("gv.")
    create_teacher(dashboard, username, unique("GV "))
    dashboard.click("#admin-button")

    sign_in_as(dashboard, username)

    expect(dashboard.locator("#student-list")).to_contain_text("chưa được phân công")


def test_switching_class_shows_that_class_roster(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    class_name = unique("Zz ")
    create_class(dashboard, class_name)
    dashboard.click("#close-admin-button")

    dashboard.select_option("#class-select", label=class_name)

    expect(dashboard.locator("#student-list")).not_to_contain_text("Nguyễn Văn An")


def test_admin_adds_existing_student_to_another_class(dashboard) -> None:
    seed_students(dashboard, ("HS001", "Nguyễn Văn An"))
    class_name = unique("Zz ")
    create_class(dashboard, class_name)
    card = dashboard.locator(".admin-class", has_text=class_name)

    card.locator(".add-student-form input").fill("HS001")
    card.locator('.add-student-form button[type="submit"]').click()

    expect(card).to_contain_text("1 học sinh")
    dashboard.click("#close-admin-button")
    dashboard.select_option("#class-select", label=class_name)
    expect(dashboard.locator("#student-list")).to_contain_text("Nguyễn Văn An")


def test_camera_follows_the_selected_class(dashboard) -> None:
    class_name = unique("Zz ")
    create_class(dashboard, class_name)
    dashboard.click("#close-admin-button")
    status = dashboard.locator("#socket-status")
    dashboard.click("#start-camera-button")
    expect(status).to_have_class(re.compile("online"), timeout=20000)

    dashboard.select_option("#class-select", label=class_name)

    expect(status).to_have_class(re.compile("online"), timeout=20000)
    dashboard.click("#stop-camera-button")


def test_tv_mode_hides_class_selector(dashboard) -> None:
    dashboard.click("#display-tv")

    expect(dashboard.locator("#class-select")).to_be_hidden()
