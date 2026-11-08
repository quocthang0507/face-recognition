"""Student-supplied text must stay text wherever the dashboard renders it."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from .helpers import seed_students

pytestmark = pytest.mark.e2e

HOSTILE_NAME = 'An" onfocus="window.injected=1'


def test_quote_in_name_cannot_add_attributes(dashboard) -> None:
    seed_students(dashboard, ("HS004", HOSTILE_NAME))

    select = dashboard.locator("[data-consent]")

    assert select.get_attribute("onfocus") is None
    expect(select).to_have_attribute("aria-label", f"Đồng ý của {HOSTILE_NAME}")


def test_quote_in_name_is_displayed_literally(dashboard) -> None:
    seed_students(dashboard, ("HS004", HOSTILE_NAME))

    expect(dashboard.locator("#student-list")).to_contain_text(HOSTILE_NAME)
