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
