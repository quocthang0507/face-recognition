"""Private encrypted avatar and evidence snapshot storage."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet

from .config import settings


class PrivateStorage:
    """Store avatars and behavior evidence encrypted at rest."""

    def __init__(self) -> None:
        settings.ensure_directories()
        self._key_path = settings.data_dir / ".avatar.key"
        self._cipher = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        self._key_path.chmod(0o600)
        return key

    def save_avatar(self, content: bytes) -> str:
        """Encrypt and store an uploaded avatar image."""

        name = f"{uuid4().hex}.enc"
        path = settings.avatar_dir / name
        path.write_bytes(self._cipher.encrypt(content))
        path.chmod(0o600)
        return name

    def read_avatar(self, name: str) -> bytes:
        """Decrypt a stored avatar after validating its relative path."""

        return self._cipher.decrypt(
            self._safe_path(settings.avatar_dir, name).read_bytes()
        )

    def delete_avatar(self, name: str) -> None:
        """Delete an encrypted avatar if it still exists."""

        try:
            self._safe_path(settings.avatar_dir, name).unlink()
        except FileNotFoundError:
            pass

    def save_snapshot(self, content: bytes) -> str:
        """Encrypt and store a JPEG evidence snapshot."""

        name = f"{uuid4().hex}.enc"
        path = settings.snapshot_dir / name
        path.write_bytes(self._cipher.encrypt(content))
        path.chmod(0o600)
        return name

    def read_snapshot(self, name: str) -> bytes:
        """Read a snapshot; plain .jpg files predate encryption and age out."""

        content = self._safe_path(settings.snapshot_dir, name).read_bytes()
        return content if name.endswith(".jpg") else self._cipher.decrypt(content)

    def delete_snapshot(self, name: str) -> None:
        """Delete a snapshot if it still exists."""

        path = self._safe_path(settings.snapshot_dir, name)
        if path.exists():
            path.unlink()

    @staticmethod
    def _safe_path(parent: Path, name: str) -> Path:
        if Path(name).name != name:
            raise FileNotFoundError("Invalid private file name")
        path = parent / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return path
