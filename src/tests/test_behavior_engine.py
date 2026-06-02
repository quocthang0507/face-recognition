"""Tests for behavior geometry and temporal detectors."""

import math

import pytest

from src.behavior_engine import (
    CheatingDetector,
    DetectorContext,
    HandOnFaceDetector,
    SleepingDetector,
    eye_aspect_ratio,
    minimum_relative_hand_face_distance,
    mouth_aspect_ratio,
)


def context(**overrides: float | int | str) -> DetectorContext:
    values: dict[str, float | int | str] = {
        "track_key": "face-1",
        "now": 0.0,
        "ear": 0.3,
        "mar": 0.02,
        "pitch": 0.0,
        "yaw": 0.0,
        "roll": 0.0,
        "hand_face_distance": math.inf,
        "face_count": 1,
    }
    values.update(overrides)
    return DetectorContext(**values)  # type: ignore[arg-type]


def test_eye_aspect_ratio_uses_vertical_opening() -> None:
    points = [(0, 0), (1, 1), (3, 1), (4, 0), (3, -1), (1, -1)]

    assert eye_aspect_ratio(points) == pytest.approx(0.5)


def test_mouth_aspect_ratio_uses_lip_gap() -> None:
    assert mouth_aspect_ratio((0, 0), (10, 0), (5, -1), (5, 2)) == pytest.approx(0.3)


def test_hand_distance_is_relative_to_face_width() -> None:
    result = minimum_relative_hand_face_distance([(5, 2)], [(5, 0)], face_width=10)

    assert result == pytest.approx(0.2)


def test_sleeping_requires_closed_eyes_and_downward_pitch_for_three_seconds() -> None:
    detector = SleepingDetector()

    assert not detector.evaluate(context(ear=0.1, pitch=15, now=0))
    assert not detector.evaluate(context(ear=0.1, pitch=15, now=2.9))
    assert detector.evaluate(context(ear=0.1, pitch=15, now=3.0))


def test_hand_on_face_requires_two_seconds() -> None:
    detector = HandOnFaceDetector()

    assert not detector.evaluate(context(hand_face_distance=0.1, now=0))
    assert detector.evaluate(context(hand_face_distance=0.1, now=2))


def test_cheating_detects_sideways_yaw() -> None:
    detector = CheatingDetector()

    assert not detector.evaluate(context(yaw=-31, now=0))
    assert detector.evaluate(context(yaw=-31, now=2))
