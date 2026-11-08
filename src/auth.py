"""Small signed-cookie authentication helper for teacher access."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from .config import settings


class AuthenticationError(ValueError):
    """Raised when an authentication token is invalid or expired."""


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def issue_teacher_token(now: int | None = None) -> str:
    """Issue an expiring teacher access token signed with HMAC SHA-256."""

    issued_at = int(time.time() if now is None else now)
    payload = _encode(
        json.dumps(
            {"role": "teacher", "exp": issued_at + settings.token_ttl_seconds},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = hmac.new(
        settings.token_secret.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload}.{_encode(signature)}"


def verify_teacher_token(token: str | None, now: int | None = None) -> None:
    """Validate a teacher token and raise on invalid input."""

    if not token:
        raise AuthenticationError("Thiếu token giáo viên")
    try:
        payload, supplied_signature = token.split(".", maxsplit=1)
        expected_signature = hmac.new(
            settings.token_secret.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected_signature, _decode(supplied_signature)):
            raise AuthenticationError("Token giáo viên không hợp lệ")
        content = json.loads(_decode(payload))
        current_time = int(time.time() if now is None else now)
        if content.get("role") != "teacher" or int(content["exp"]) < current_time:
            raise AuthenticationError("Token giáo viên đã hết hạn")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, AuthenticationError):
            raise
        raise AuthenticationError("Token giáo viên không hợp lệ") from exc


def password_matches(password: str) -> bool:
    """Compare the supplied teacher password without timing leaks."""

    return hmac.compare_digest(password, settings.teacher_password)


class LoginThrottle:
    """Lock a client out for a while after repeated wrong passwords."""

    def __init__(
        self,
        max_failures: int | None = None,
        lockout_seconds: int | None = None,
    ) -> None:
        self.max_failures = max_failures or settings.login_max_failures
        self.lockout_seconds = lockout_seconds or settings.login_lockout_seconds
        self._failures: dict[str, tuple[int, float]] = {}

    def retry_after(self, client: str, now: float | None = None) -> int:
        """Return remaining lockout seconds for a client, or zero."""

        current = time.time() if now is None else now
        count, locked_until = self._failures.get(client, (0, 0.0))
        if count >= self.max_failures and locked_until > current:
            return int(locked_until - current) + 1
        if count >= self.max_failures:
            self._failures.pop(client, None)
        return 0

    def record_failure(self, client: str, now: float | None = None) -> None:
        """Count one failed login and start the lockout at the limit."""

        current = time.time() if now is None else now
        count, _ = self._failures.get(client, (0, 0.0))
        count += 1
        locked_until = 0.0
        if count >= self.max_failures:
            locked_until = current + self.lockout_seconds
        self._failures[client] = (count, locked_until)

    def record_success(self, client: str) -> None:
        """Clear failures after a correct password."""

        self._failures.pop(client, None)
