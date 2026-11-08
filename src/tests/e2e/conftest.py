"""Fixtures that run the dashboard in a real browser against a real server.

Every run gets its own server and temporary data directory, so these tests can
never touch ``src/data``.

Environment variables:
    E2E_HEADED=1             show the browser window
    E2E_CHROMIUM_PATH=...    use an already installed Chromium
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest

from .helpers import ADMIN_USERNAME, PASSWORD

if find_spec("playwright") is None:
    # `pytest src/tests` must keep working on machines without Playwright.
    collect_ignore_glob = ["test_*.py"]

ROOT = Path(__file__).resolve().parents[3]
SERVER_START_TIMEOUT_SECONDS = 180


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_until_healthy(base_url: str, server: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + SERVER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"Server exited early:\n{log.read_text('utf-8')}")
        try:
            urllib.request.urlopen(f"{base_url}/api/health", timeout=2)
            return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise RuntimeError(f"Server did not become healthy:\n{log.read_text('utf-8')}")


@pytest.fixture(scope="session")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start the application on a free port with throwaway data."""

    data_dir = tmp_path_factory.mktemp("e2e-data")
    log_path = data_dir.parent / "server.log"
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "FACE_APP_DATA_DIR": str(data_dir),
        "FACE_APP_DATABASE_URL": f"sqlite:///{data_dir.as_posix()}/classroom.db",
        "FACE_APP_ALLOWED_ORIGINS": url,
        "FACE_APP_TEACHER_PASSWORD": PASSWORD,
        "FACE_APP_TOKEN_SECRET": "e2e-only-token-secret",
        "PYTHONUTF8": "1",
    }
    with log_path.open("w", encoding="utf-8") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_until_healthy(url, server, log_path)
            yield url
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


@pytest.fixture(scope="session")
def browser() -> Iterator:
    from playwright.sync_api import sync_playwright

    executable = os.environ.get("E2E_CHROMIUM_PATH") or None
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(
            headless=os.environ.get("E2E_HEADED") != "1",
            executable_path=executable,
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        )
        yield instance
        instance.close()


@pytest.fixture
def context(browser, base_url: str) -> Iterator:
    instance = browser.new_context(
        base_url=base_url,
        viewport={"width": 1440, "height": 900},
        locale="vi-VN",
        accept_downloads=True,
    )
    instance.grant_permissions(["camera"], origin=base_url)
    instance.set_default_timeout(8000)
    yield instance
    instance.close()


@pytest.fixture
def prompt_answer() -> dict[str, str]:
    """Text typed into the next ``window.prompt``; confirms are always accepted."""

    return {"text": ""}


@pytest.fixture
def anonymous_page(context, prompt_answer: dict[str, str]) -> Iterator:
    """A signed-out page that fails the test on any uncaught JavaScript error."""

    errors: list[str] = []
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            errors.append(message.text)
            if "Content Security Policy" in message.text
            else None
        ),
    )
    page.on(
        "dialog",
        lambda dialog: (
            dialog.accept(prompt_answer["text"])
            if dialog.type == "prompt"
            else dialog.accept()
        ),
    )
    yield page
    assert errors == []


def _reset_application(request) -> None:
    while active := request.get("/api/sessions/active").json():
        request.post(f"/api/sessions/{active['id']}/finish")
    for student in request.get("/api/students").json():
        request.delete(f"/api/students/{student['id']}")
    request.delete("/api/behaviors")


@pytest.fixture
def dashboard(anonymous_page, context):
    """A signed-in dashboard starting from an empty class and no active session."""

    response = context.request.post(
        "/api/auth/login", data={"username": ADMIN_USERNAME, "password": PASSWORD}
    )
    assert response.ok
    _reset_application(context.request)
    anonymous_page.goto("/")
    anonymous_page.wait_for_selector("#student-list tr")
    return anonymous_page
