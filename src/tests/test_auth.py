"""Tests for signed teacher cookies."""

import pytest

from src.auth import AuthenticationError, issue_teacher_token, verify_teacher_token


def test_teacher_token_can_be_verified_before_expiry() -> None:
    token = issue_teacher_token(now=100)

    verify_teacher_token(token, now=101)


def test_teacher_token_rejects_expired_timestamp() -> None:
    token = issue_teacher_token(now=100)

    with pytest.raises(AuthenticationError):
        verify_teacher_token(token, now=100_000)


def test_teacher_token_rejects_modified_signature() -> None:
    token = issue_teacher_token(now=100)

    with pytest.raises(AuthenticationError):
        verify_teacher_token(f"{token}broken", now=101)
