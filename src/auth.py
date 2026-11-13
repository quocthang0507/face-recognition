"""Signed-cookie sessions and password hashing for teacher accounts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from .config import settings

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


class AuthenticationError(ValueError):
    """Raised when an authentication token is invalid or expired."""


@dataclass(frozen=True)
class TokenClaims:
    """The account a token belongs to and the session generation it was issued in."""

    user_id: int
    version: int


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _sign(payload: str) -> bytes:
    return hmac.new(
        settings.signing_key.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).digest()


def issue_user_token(user_id: int, version: int = 0, now: int | None = None) -> str:
    """Issue an expiring access token for one account, signed with HMAC SHA-256."""

    issued_at = int(time.time() if now is None else now)
    payload = _encode(
        json.dumps(
            {
                "uid": user_id,
                "ver": version,
                "exp": issued_at + settings.token_ttl_seconds,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return f"{payload}.{_encode(_sign(payload))}"


def verify_user_token(token: str | None, now: int | None = None) -> TokenClaims:
    """Return the claims of a valid token and raise on invalid input."""

    if not token:
        raise AuthenticationError("Thiếu token đăng nhập")
    try:
        payload, supplied_signature = token.split(".", maxsplit=1)
        if not hmac.compare_digest(_sign(payload), _decode(supplied_signature)):
            raise AuthenticationError("Token đăng nhập không hợp lệ")
        content = json.loads(_decode(payload))
        current_time = int(time.time() if now is None else now)
        if int(content["exp"]) < current_time:
            raise AuthenticationError("Token đăng nhập đã hết hạn")
        return TokenClaims(int(content["uid"]), int(content["ver"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, AuthenticationError):
            raise
        raise AuthenticationError("Token đăng nhập không hợp lệ") from exc


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32, maxmem=64 << 20
    )


def hash_password(password: str) -> str:
    """Return a salted scrypt hash that stores its own parameters."""

    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Compare a password with a stored hash without timing leaks."""

    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = _scrypt(password, _decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(candidate, _decode(digest))
    except ValueError:
        return False


class LoginThrottle:
    """Lock a client out for a while after repeated wrong passwords."""

    def __init__(
        self,
        max_failures: int | None = None,
        lockout_seconds: int | None = None,
        max_entries: int = 4096,
    ) -> None:
        self.max_failures = max_failures or settings.login_max_failures
        self.lockout_seconds = lockout_seconds or settings.login_lockout_seconds
        self.max_entries = max(1, max_entries)
        self._failures: dict[str, tuple[int, float, float]] = {}

    def _prune(self, current: float) -> None:
        stale_cutoff = current - self.lockout_seconds
        expired = [
            key
            for key, (count, locked_until, updated_at) in self._failures.items()
            if (count >= self.max_failures and locked_until <= current)
            or updated_at < stale_cutoff
        ]
        for key in expired:
            self._failures.pop(key, None)
        if len(self._failures) >= self.max_entries:
            overflow = len(self._failures) - self.max_entries + 1
            oldest = sorted(
                self._failures.items(), key=lambda item: item[1][2]
            )[:overflow]
            for key, _ in oldest:
                self._failures.pop(key, None)

    def retry_after(self, client: str, now: float | None = None) -> int:
        """Return remaining lockout seconds for a client, or zero."""

        current = time.time() if now is None else now
        count, locked_until, _ = self._failures.get(client, (0, 0.0, 0.0))
        if count >= self.max_failures and locked_until > current:
            return int(locked_until - current) + 1
        if count >= self.max_failures:
            self._failures.pop(client, None)
        return 0

    def record_failure(self, client: str, now: float | None = None) -> None:
        """Count one failed login and start the lockout at the limit."""

        current = time.time() if now is None else now
        if len(self._failures) >= self.max_entries:
            self._prune(current)
        count, locked_until, _ = self._failures.get(client, (0, 0.0, current))
        if count >= self.max_failures and locked_until <= current:
            count = 0
        count += 1
        next_locked_until = (
            current + self.lockout_seconds if count >= self.max_failures else 0.0
        )
        self._failures[client] = (count, next_locked_until, current)

    def record_success(self, client: str) -> None:
        """Clear failures after a correct password."""

        self._failures.pop(client, None)
