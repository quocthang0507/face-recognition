"""Tests for face matching and attendance stabilization."""

import pytest

from src.face_engine import best_embedding_match, cosine_similarity
from src.models import Student
from src.stream_processor import AttendanceStabilizer
from src.face_engine import BoundingBox, FaceMatch


def test_cosine_similarity_matches_same_direction() -> None:
    assert cosine_similarity([1, 2], [2, 4]) == pytest.approx(1.0)


def test_best_embedding_match_returns_student_above_threshold() -> None:
    student = Student(id=7, student_code="S07", fullname="Lan", embedding="[1,0]")

    matched, confidence = best_embedding_match([1, 0], [(student, [1, 0])], 80)

    assert matched is student
    assert confidence == pytest.approx(100)


def test_attendance_requires_five_consecutive_recognition_frames() -> None:
    stabilizer = AttendanceStabilizer(required_frames=5)
    match = FaceMatch(BoundingBox(0, 0, 10, 10), 3, "S03", "Minh", 90)

    for _ in range(4):
        assert stabilizer.observe([match]) == []
    assert stabilizer.observe([match]) == [3]


def test_attendance_streak_resets_when_face_disappears() -> None:
    stabilizer = AttendanceStabilizer(required_frames=2)
    match = FaceMatch(BoundingBox(0, 0, 10, 10), 3, "S03", "Minh", 90)

    assert stabilizer.observe([match]) == []
    assert stabilizer.observe([]) == []
    assert stabilizer.observe([match]) == []
