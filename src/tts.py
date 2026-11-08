"""Vietnamese text-to-speech that runs entirely on this server."""

from __future__ import annotations

import io
import threading
import wave
from collections import OrderedDict
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path

from .config import settings

MAX_TEXT_LENGTH = 200
CACHE_SIZE = 128


class SpeechUnavailable(RuntimeError):
    """Piper or its Vietnamese voice model is not installed."""


def _load_piper_voice(model_path: Path):
    from piper import PiperVoice

    return PiperVoice.load(str(model_path))


class VietnameseSpeech:
    """Turn short Vietnamese sentences into WAV audio with a Piper voice."""

    def __init__(
        self,
        model_path: Path | None = None,
        load_voice: Callable[[Path], object] | None = None,
    ) -> None:
        self.model_path = Path(model_path or settings.tts_model)
        self._load_voice = load_voice or _load_piper_voice
        self._library_present = load_voice is not None or find_spec("piper") is not None
        self._voice = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, bytes] = OrderedDict()

    @property
    def available(self) -> bool:
        return self._library_present and self.model_path.is_file()

    def preload(self) -> None:
        """Load the voice ahead of time so the first alert is not delayed."""

        if self.available:
            with self._lock:
                self._ensure_voice()

    def _ensure_voice(self):
        if self._voice is None:
            self._voice = self._load_voice(self.model_path)
        return self._voice

    def synthesize(self, text: str) -> bytes:
        """Return WAV audio for one sentence, reusing recent results."""

        if not self.available:
            raise SpeechUnavailable("Chưa cài giọng đọc tiếng Việt trên máy chủ")
        normalized = " ".join(text.split())
        if not normalized or len(normalized) > MAX_TEXT_LENGTH:
            raise ValueError(f"Nội dung đọc phải có từ 1-{MAX_TEXT_LENGTH} ký tự")
        # One lock: the voice is shared and alerts repeat the same few sentences.
        with self._lock:
            cached = self._cache.get(normalized)
            if cached is not None:
                self._cache.move_to_end(normalized)
                return cached
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as target:
                self._ensure_voice().synthesize_wav(normalized, target)
            audio = buffer.getvalue()
            self._cache[normalized] = audio
            if len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
            return audio
