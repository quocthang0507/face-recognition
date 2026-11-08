"""Which voice the dashboard uses to read Vietnamese aloud."""

from __future__ import annotations

import io
import json
import wave

import pytest
from playwright.sync_api import expect

from .helpers import open_settings, reload_dashboard

pytestmark = pytest.mark.e2e

SPY_BROWSER_SPEECH = """() => {
  window.browserSpeech = [];
  speechSynthesis.speak = (utterance) => window.browserSpeech.push(utterance.text);
}"""


def silent_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(22050)
        target.writeframes(b"\0\0" * 2205)
    return buffer.getvalue()


def use_server_speech(page, available: bool) -> None:
    page.route(
        "**/api/tts/status", lambda route: route.fulfill(json={"available": available})
    )
    reload_dashboard(page)
    page.evaluate(SPY_BROWSER_SPEECH)


def test_server_voice_reads_the_alert(dashboard) -> None:
    use_server_speech(dashboard, True)
    spoken: list[str] = []

    def answer(route) -> None:
        spoken.append(json.loads(route.request.post_data)["text"])
        route.fulfill(body=silent_wav(), content_type="audio/wav")

    dashboard.route("**/api/tts", answer)

    with dashboard.expect_response("**/api/tts"):
        dashboard.evaluate("speakWarning('Cảnh báo Ngủ gục, An')")

    assert spoken == ["Cảnh báo Ngủ gục, An"]
    assert dashboard.evaluate("window.browserSpeech") == []


def test_speech_setting_off_stays_silent(dashboard) -> None:
    use_server_speech(dashboard, True)
    requests: list[str] = []
    dashboard.on(
        "request",
        lambda r: requests.append(r.url) if r.url.endswith("/api/tts") else None,
    )
    open_settings(dashboard)
    dashboard.uncheck("#tts-alert-checkbox-modal")

    dashboard.evaluate("speakWarning('Cảnh báo')")

    assert requests == []


def test_never_reads_vietnamese_with_a_foreign_voice(dashboard) -> None:
    use_server_speech(dashboard, False)
    dashboard.evaluate(
        "voices = [{name: 'English', lang: 'en-US'}]; renderSpeechStatus()"
    )

    dashboard.evaluate("speakWarning('Cảnh báo')")

    assert dashboard.evaluate("window.browserSpeech") == []


def test_settings_explain_when_no_vietnamese_voice_exists(dashboard) -> None:
    use_server_speech(dashboard, False)
    dashboard.evaluate(
        "voices = [{name: 'English', lang: 'en-US'}]; renderSpeechStatus()"
    )

    open_settings(dashboard)

    expect(dashboard.locator("#tts-status")).to_contain_text("chưa có giọng tiếng Việt")


def test_settings_name_the_server_voice(dashboard) -> None:
    use_server_speech(dashboard, True)

    open_settings(dashboard)

    expect(dashboard.locator("#tts-status")).to_contain_text("tiếng Việt")
    expect(dashboard.locator("#tts-voice-container")).to_be_hidden()
