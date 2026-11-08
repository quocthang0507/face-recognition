"""Streaming from a fake camera over the WebSocket."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_camera_streams_then_stops(dashboard) -> None:
    status = dashboard.locator("#socket-status")

    dashboard.click("#start-camera-button")

    expect(status).to_have_class(re.compile("online"), timeout=20000)
    expect(status).to_contain_text(" ms", timeout=30000)

    dashboard.click("#stop-camera-button")

    expect(status).to_have_class(re.compile("offline"))
    expect(dashboard.locator("#start-camera-button")).to_be_enabled()
