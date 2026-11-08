"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# Appears in the public repository and .env.example, so it can never sign tokens.
PUBLISHED_TOKEN_SECRET = "development-only-change-this-secret"


@lru_cache(maxsize=8)
def _persistent_secret(path: Path) -> str:
    """Return this installation's generated signing key, creating it once."""

    if path.exists():
        return path.read_text(encoding="ascii").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret, encoding="ascii")
    path.chmod(0o600)
    return secret


def _as_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _as_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the classroom application."""

    environment: str = field(
        default_factory=lambda: os.getenv("FACE_APP_ENV", "development")
    )
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("FACE_APP_DATA_DIR", str(BASE_DIR / "data"))
        )
    )
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "FACE_APP_DATABASE_URL",
            "sqlite:///"
            + str(
                Path(os.getenv("FACE_APP_DATA_DIR", str(BASE_DIR / "data")))
                / "classroom.db"
            ),
        )
    )
    teacher_password: str = field(
        default_factory=lambda: os.getenv("FACE_APP_TEACHER_PASSWORD", "change-me")
    )
    token_secret: str = field(
        default_factory=lambda: os.getenv("FACE_APP_TOKEN_SECRET", "")
    )
    cookie_name: str = "classroom_teacher"
    token_ttl_seconds: int = 8 * 60 * 60
    secure_cookie: bool = field(
        default_factory=lambda: _as_bool("FACE_APP_SECURE_COOKIE")
    )
    secure_transport_only: bool = field(
        default_factory=lambda: _as_bool("FACE_APP_SECURE_TRANSPORT_ONLY")
    )
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip()
            for origin in os.getenv(
                "FACE_APP_ALLOWED_ORIGINS",
                "http://127.0.0.1:8000,http://localhost:8000",
            ).split(",")
            if origin.strip()
        )
    )
    recognition_interval_seconds: float = 1.5
    recognition_confidence: float = 80.0
    attendance_frames: int = 5
    behavior_cooldown_seconds: float = 10.0
    retention_days: int = 30
    late_after_minutes: int = field(
        default_factory=lambda: _as_int("FACE_APP_LATE_AFTER_MINUTES", 15)
    )
    duplicate_face_confidence: float = 90.0
    # Performance tuning (phase 1 of docs/planning/architecture-proposal.md).
    behavior_fps: float = field(
        default_factory=lambda: _as_float("FACE_APP_BEHAVIOR_FPS", 8.0)
    )
    hand_fps: float = field(default_factory=lambda: _as_float("FACE_APP_HAND_FPS", 3.0))
    max_faces: int = field(default_factory=lambda: _as_int("FACE_APP_MAX_FACES", 8))
    embedding_detector: str = field(
        default_factory=lambda: os.getenv("FACE_APP_EMBED_DETECTOR", "skip")
    )
    cache_ttl_seconds: float = 5.0
    profile: bool = field(default_factory=lambda: _as_bool("FACE_APP_PROFILE"))
    tts_model: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "FACE_APP_TTS_MODEL",
                str(BASE_DIR.parent / "models" / "tts" / "vi_VN-vais1000-medium.onnx"),
            )
        )
    )
    login_max_failures: int = 5
    login_lockout_seconds: int = 5 * 60

    @property
    def embedding_model_id(self) -> str:
        """Identifier of the embedding pipeline; vectors from others are stale."""

        return f"Facenet:{self.embedding_detector}"

    @property
    def uses_default_credentials(self) -> bool:
        """Whether the development password or token secret is still in use."""

        return (
            self.teacher_password == "change-me"
            or self.token_secret == PUBLISHED_TOKEN_SECRET
        )

    @property
    def signing_key(self) -> str:
        """Return the configured token key, or a generated per-installation one."""

        if self.token_secret and self.token_secret != PUBLISHED_TOKEN_SECRET:
            return self.token_secret
        return _persistent_secret(self.data_dir / ".token.key")

    def check_safe_to_start(self) -> None:
        """Refuse a production start with the credentials published in the repo."""

        if self.environment == "production" and self.uses_default_credentials:
            raise RuntimeError(
                "Hãy đặt FACE_APP_TEACHER_PASSWORD và FACE_APP_TOKEN_SECRET "
                "trước khi chạy ở môi trường production"
            )

    @property
    def avatar_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    def ensure_directories(self) -> None:
        """Create private runtime directories when they do not exist."""

        for path in (self.data_dir, self.avatar_dir, self.snapshot_dir):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)


settings = Settings()
