"""Tests for signed account cookies."""

import pytest

from src.auth import (
    AuthenticationError,
    LoginThrottle,
    issue_user_token,
    verify_user_token,
)


def test_token_can_be_verified_before_expiry() -> None:
    token = issue_user_token(1, now=100)

    assert verify_user_token(token, now=101) == 1


def test_token_rejects_expired_timestamp() -> None:
    token = issue_user_token(1, now=100)

    with pytest.raises(AuthenticationError):
        verify_user_token(token, now=100_000)


def test_token_rejects_modified_signature() -> None:
    token = issue_user_token(1, now=100)

    with pytest.raises(AuthenticationError):
        verify_user_token(f"{token}broken", now=101)


def test_login_throttle_locks_out_after_repeated_failures() -> None:
    throttle = LoginThrottle(max_failures=3, lockout_seconds=60)

    for _ in range(3):
        assert throttle.retry_after("10.0.0.1", now=0) == 0
        throttle.record_failure("10.0.0.1", now=0)

    assert throttle.retry_after("10.0.0.1", now=10) > 0
    assert throttle.retry_after("10.0.0.2", now=10) == 0
    assert throttle.retry_after("10.0.0.1", now=61) == 0


def test_login_throttle_clears_after_success() -> None:
    throttle = LoginThrottle(max_failures=2, lockout_seconds=60)
    throttle.record_failure("ip", now=0)

    throttle.record_success("ip")
    throttle.record_failure("ip", now=1)

    assert throttle.retry_after("ip", now=1) == 0
