"""Tests for settings that protect a real deployment."""

from __future__ import annotations

import pytest

from src.config import Settings

SAFE = {"teacher_password": "mat-khau-that", "token_secret": "khoa-ky-that-dai"}


@pytest.mark.parametrize(
    "unsafe",
    [
        {"token_secret": "development-only-change-this-secret"},
        {"teacher_password": "change-me"},
    ],
)
def test_production_refuses_published_default_credentials(unsafe) -> None:
    settings = Settings(environment="production", **{**SAFE, **unsafe})

    with pytest.raises(RuntimeError, match="FACE_APP_"):
        settings.check_safe_to_start()


def test_production_starts_with_own_credentials() -> None:
    Settings(environment="production", **SAFE).check_safe_to_start()


def test_development_allows_default_credentials() -> None:
    Settings(
        environment="development",
        teacher_password="change-me",
        token_secret="development-only-change-this-secret",
    ).check_safe_to_start()
