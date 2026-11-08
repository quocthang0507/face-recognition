"""Tests for server-side Vietnamese speech."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src import main
from src.services import UserService
from src.tts import SpeechUnavailable, VietnameseSpeech


class FakeVoice:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synthesize_wav(self, text: str, target: wave.Wave_write) -> None:
        self.spoken.append(text)
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(22050)
        target.writeframes(b"\0\0" * 100)


def make_speech(tmp_path: Path, voice: FakeVoice) -> VietnameseSpeech:
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    return VietnameseSpeech(model, load_voice=lambda _path: voice)


def test_missing_model_is_reported_as_unavailable(tmp_path: Path) -> None:
    speech = VietnameseSpeech(tmp_path / "none.onnx", load_voice=lambda _p: FakeVoice())

    assert speech.available is False
    with pytest.raises(SpeechUnavailable):
        speech.synthesize("Xin chào")


def test_synthesize_returns_wav_audio(tmp_path: Path) -> None:
    audio = make_speech(tmp_path, FakeVoice()).synthesize("Xin chào")

    assert audio[:4] == b"RIFF"


def test_repeated_text_is_not_synthesized_twice(tmp_path: Path) -> None:
    voice = FakeVoice()
    speech = make_speech(tmp_path, voice)

    speech.synthesize("Cảnh báo")
    speech.synthesize("Cảnh báo")

    assert voice.spoken == ["Cảnh báo"]


def test_whitespace_is_normalized(tmp_path: Path) -> None:
    voice = FakeVoice()

    make_speech(tmp_path, voice).synthesize("  Cảnh   báo ")

    assert voice.spoken == ["Cảnh báo"]


@pytest.mark.parametrize("text", ["", "   ", "a" * 201])
def test_invalid_text_is_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError):
        make_speech(tmp_path, FakeVoice()).synthesize(text)


@pytest.fixture
def signed_in(client: TestClient, session_factory: sessionmaker) -> TestClient:
    with session_factory() as db:
        UserService.create(db, "gv.a", "mat-khau-gv", "GV", "TEACHER")
    client.post("/api/auth/login", json={"username": "gv.a", "password": "mat-khau-gv"})
    return client


def test_speech_requires_login(client: TestClient) -> None:
    assert client.post("/api/tts", json={"text": "Xin chào"}).status_code == 401


def test_api_returns_audio(signed_in, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "speech", make_speech(tmp_path, FakeVoice()))

    response = signed_in.post("/api/tts", json={"text": "Xin chào"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert signed_in.get("/api/tts/status").json() == {"available": True}


def test_api_reports_missing_voice(signed_in, tmp_path, monkeypatch) -> None:
    speech = VietnameseSpeech(tmp_path / "none.onnx", load_voice=lambda _p: FakeVoice())
    monkeypatch.setattr(main, "speech", speech)

    assert signed_in.post("/api/tts", json={"text": "Xin"}).status_code == 503
    assert signed_in.get("/api/tts/status").json() == {"available": False}


def test_api_rejects_overlong_text(signed_in, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main, "speech", make_speech(tmp_path, FakeVoice()))

    assert signed_in.post("/api/tts", json={"text": "a" * 201}).status_code == 422
