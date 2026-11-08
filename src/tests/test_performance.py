"""Tests for the phase-1 performance changes (docs/architecture-proposal.md)."""

import sys
import types

import numpy as np
import pytest

from src import cache
from src.behavior_engine import BehaviorEngine, FaceBehavior, RateLimiter
from src.face_engine import (
    DeepFaceEmbeddingProvider,
    FaceRecognitionEngine,
    Gallery,
)
from src.models import Student
from src.stream_processor import FrameResult, StageTimer, VersionedCache
from src.tracking import BoundingBox, TrackedBox


def student(student_id: int, embedding: str) -> Student:
    return Student(
        id=student_id,
        student_code=f"S{student_id:02d}",
        fullname=f"HS {student_id}",
        embedding=embedding,
    )


# --- Gallery: vectorised matching -------------------------------------------


def test_gallery_skips_students_without_embedding() -> None:
    gallery = Gallery.build([student(1, "[1,0]"), student(2, "[]")])

    assert [item.id for item in gallery.students] == [1]


def test_gallery_ignores_vectors_from_a_different_model_dimension() -> None:
    gallery = Gallery.build(
        [student(1, "[1,0]"), student(2, "[0,1]"), student(3, "[1,0,0]")]
    )

    assert [item.id for item in gallery.students] == [1, 2]


def test_gallery_scores_match_cosine_similarity_in_percent() -> None:
    gallery = Gallery.build([student(1, "[1,0]"), student(2, "[0,2]")])

    scores = gallery.scores([[3.0, 3.0]])

    assert scores.shape == (1, 2)
    assert scores[0] == pytest.approx([70.71, 70.71], abs=0.01)


def test_recognition_skips_embedding_when_nobody_has_a_face_sample() -> None:
    class Provider:
        calls = 0

        def embed(self, image):
            Provider.calls += 1
            return [1.0, 0.0]

    engine = FaceRecognitionEngine(locator=object(), provider=Provider())
    frame = np.zeros((20, 20, 3), dtype=np.uint8)

    matches, refreshed = engine.recognize_if_due(
        frame,
        [student(1, "[]")],
        tracked_boxes=[TrackedBox(1, BoundingBox(0, 0, 10, 10))],
        now=10,
    )

    assert refreshed
    assert Provider.calls == 0
    assert matches[0].student_id is None


def test_recognition_uses_prebuilt_gallery() -> None:
    class Provider:
        def embed(self, image):
            return [1.0, 0.0]

    engine = FaceRecognitionEngine(locator=object(), provider=Provider())
    frame = np.zeros((20, 20, 3), dtype=np.uint8)
    gallery = Gallery.build([student(7, "[1,0]")])

    matches, _ = engine.recognize_if_due(
        frame,
        [],
        tracked_boxes=[TrackedBox(1, BoundingBox(0, 0, 10, 10))],
        now=10,
        gallery=gallery,
    )

    assert matches[0].student_id == 7


def test_deepface_provider_does_not_run_a_second_face_detector(monkeypatch) -> None:
    calls = {}

    def represent(**kwargs):
        calls.update(kwargs)
        return [{"embedding": [0.1, 0.2]}]

    fake = types.ModuleType("deepface")
    fake.DeepFace = types.SimpleNamespace(represent=represent)
    monkeypatch.setitem(sys.modules, "deepface", fake)

    DeepFaceEmbeddingProvider().embed(np.zeros((8, 8, 3), dtype=np.uint8))

    assert calls["detector_backend"] == "skip"


# --- Behavior analysis at a lower, fixed rate ---------------------------------


def test_rate_limiter_allows_one_run_per_interval() -> None:
    limiter = RateLimiter(fps=5)

    assert limiter.due(0.0)
    assert not limiter.due(0.1)
    assert limiter.due(0.21)


def test_rate_limiter_with_zero_fps_always_runs() -> None:
    limiter = RateLimiter(fps=0)

    assert limiter.due(0.0)
    assert limiter.due(0.0)


class _CountingModel:
    def __init__(self, attribute: str) -> None:
        self.calls = 0
        self.attribute = attribute

    def process(self, image):
        self.calls += 1
        return types.SimpleNamespace(**{self.attribute: []})


def _engine_with_fake_models(behavior_fps: float, hand_fps: float) -> BehaviorEngine:
    engine = BehaviorEngine(behavior_fps=behavior_fps, hand_fps=hand_fps)
    engine._face_mesh = _CountingModel("multi_face_landmarks")
    engine._hands = _CountingModel("multi_hand_landmarks")
    return engine


def test_behavior_engine_reuses_last_result_between_scheduled_runs() -> None:
    engine = _engine_with_fake_models(behavior_fps=5, hand_fps=5)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    engine.analyze(frame, now=0.0)
    engine.analyze(frame, now=0.05)
    engine.analyze(frame, now=0.25)

    assert engine._face_mesh.calls == 2


def test_hand_model_runs_less_often_than_face_mesh() -> None:
    engine = _engine_with_fake_models(behavior_fps=10, hand_fps=2)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)

    for step in range(10):
        engine.analyze(frame, now=step * 0.11)

    assert engine._face_mesh.calls == 10
    assert engine._hands.calls == 2


def test_reused_behavior_never_repeats_an_alert() -> None:
    behavior = FaceBehavior(
        BoundingBox(0, 0, 4, 4), 1, "face-1", 0.1, 0.0, 20, 0, 0, ("SLEEPING",)
    )

    assert behavior.without_alerts().alerts == ()


# --- Hot-path caches and payload ----------------------------------------------


def test_versioned_cache_reloads_only_after_change_or_ttl() -> None:
    loads = []
    hot = VersionedCache("students", lambda: loads.append(1) or len(loads), ttl=5)

    assert hot.get(now=0) == 1
    assert hot.get(now=1) == 1
    cache.bump("students")
    assert hot.get(now=2) == 2
    assert hot.get(now=8) == 3


def test_frame_payload_omits_annotated_image_by_default() -> None:
    payload = FrameResult(None, [], [], [], []).to_dict()

    assert "image" not in payload
    assert payload["type"] == "frame"


def test_frame_payload_reports_frame_size_and_server_time() -> None:
    timer = StageTimer(enabled=True)
    with timer.stage("decode"):
        pass

    payload = FrameResult(
        None, [], [], [], [], frame_size=(640, 360), timings=timer.result()
    ).to_dict()

    assert payload["frame_size"] == {"width": 640, "height": 360}
    assert "decode" in payload["timings"]
    assert payload["timings"]["total"] >= 0
