"""Tests for face matching and attendance stabilization."""

import pytest
import numpy as np

from src.face_engine import (
    FaceRecognitionEngine,
    assign_unique_identities,
    best_embedding_match,
    cosine_similarity,
    find_similar_student,
)
from src.models import Student
from src.stream_processor import AttendanceStabilizer
from src.face_engine import BoundingBox, FaceMatch
from src.tracking import TrackedBox


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


def test_registration_rejects_image_without_detected_face() -> None:
    class EmptyLocator:
        available = True

        def locate(self, frame):
            return []

    engine = FaceRecognitionEngine(locator=EmptyLocator())

    with pytest.raises(ValueError, match="Không phát hiện"):
        engine.registration_embedding(frame=None)


def test_identity_cache_moves_with_landmark_track_between_recognition_runs() -> None:
    class Locator:
        available = True

        def locate(self, frame):
            return []

    class Provider:
        def __init__(self) -> None:
            self.calls = 0

        def embed(self, frame):
            self.calls += 1
            return [1.0, 0.0]

    provider = Provider()
    engine = FaceRecognitionEngine(locator=Locator(), provider=provider)
    student = Student(id=7, student_code="S07", fullname="Lan", embedding="[1,0]")
    frame = np.zeros((20, 20, 3), dtype=np.uint8)

    first, refreshed = engine.recognize_if_due(
        frame=frame,
        students=[student],
        tracked_boxes=[TrackedBox(42, BoundingBox(0, 0, 10, 10))],
        now=2,
    )
    moved, moved_refreshed = engine.recognize_if_due(
        frame=frame,
        students=[student],
        tracked_boxes=[TrackedBox(42, BoundingBox(5, 3, 10, 10))],
        now=2.2,
    )

    assert refreshed
    assert not moved_refreshed
    assert provider.calls == 1
    assert first[0].student_id == 7
    assert moved[0].student_id == 7
    assert moved[0].box == BoundingBox(5, 3, 10, 10)


def test_one_student_is_never_assigned_to_two_faces() -> None:
    student = Student(id=1, student_code="S01", fullname="An", embedding="[1,0]")

    results = assign_unique_identities(
        [[1.0, 0.05], [1.0, 0.0]], [(student, [1.0, 0.0])], 80
    )

    assert results[1][0] is student
    assert results[0][0] is None


def test_find_similar_student_detects_duplicate_registration() -> None:
    student = Student(id=1, student_code="S01", fullname="An", embedding="[1,0]")

    duplicate, _ = find_similar_student([1.0, 0.01], [student], 90)
    excluded, _ = find_similar_student(
        [1.0, 0.01], [student], 90, exclude_student_id=1
    )

    assert duplicate is student
    assert excluded is None


def test_attendance_stabilizer_reset_allows_check_in_in_next_session() -> None:
    stabilizer = AttendanceStabilizer(required_frames=2)
    match = FaceMatch(BoundingBox(0, 0, 10, 10), 3, "S03", "Minh", 90)
    stabilizer.observe([match])
    assert stabilizer.observe([match]) == [3]
    stabilizer.observe([match])

    stabilizer.reset()

    assert stabilizer.observe([match]) == []
    assert stabilizer.observe([match]) == [3]


def test_crop_face_clamps_to_frame_and_rejects_empty_box() -> None:
    from src.face_engine import crop_face

    frame = np.zeros((20, 30, 3), dtype=np.uint8)

    cropped = crop_face(frame, BoundingBox(-5, -5, 15, 15))
    assert cropped.shape == (10, 10, 3)

    with pytest.raises(ValueError, match="không hợp lệ"):
        crop_face(frame, BoundingBox(50, 50, 10, 10))
