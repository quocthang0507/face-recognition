"""Face detection, embedding extraction and periodic identity matching."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .config import settings
from .models import Student
from .services import deserialize_embedding
from .tracking import BoundingBox, TrackedBox


class FaceEngineUnavailable(RuntimeError):
    """Raised when an optional AI dependency is not installed."""


@dataclass(frozen=True)
class FaceMatch:
    """The best known identity for one detected face."""

    box: BoundingBox
    student_id: int | None
    student_code: str | None
    fullname: str
    confidence: float
    track_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable face match."""

        return {
            "box": self.box.to_dict(),
            "student_id": self.student_id,
            "student_code": self.student_code,
            "fullname": self.fullname,
            "confidence": round(self.confidence, 1),
            "track_id": self.track_id,
        }


class EmbeddingProvider(Protocol):
    """Extract a face embedding from a BGR image."""

    def embed(self, image: Any) -> list[float]:
        """Return one numeric face embedding."""


class DeepFaceEmbeddingProvider:
    """DeepFace Facenet128 embedding provider loaded only when required."""

    def __init__(self) -> None:
        try:
            from deepface import DeepFace
        except ImportError as exc:
            raise FaceEngineUnavailable(
                "Thư viện DeepFace là bắt buộc để đăng ký và nhận diện khuôn mặt. "
                "Vui lòng cài đặt requirements-ai.txt."
            ) from exc
        self._deepface = DeepFace

    def embed(self, image: Any) -> list[float]:
        """Extract one Facenet128 embedding from a cropped face image."""

        representations = self._deepface.represent(
            img_path=image,
            model_name="Facenet",
            detector_backend="opencv",
            enforce_detection=False,
        )
        if not representations:
            raise ValueError("No face embedding could be extracted")
        return [float(value) for value in representations[0]["embedding"]]


class MediaPipeFaceLocator:
    """Locate faces with MediaPipe face detection when available."""

    def __init__(self) -> None:
        self._detector: Any | None = None
        try:
            import mediapipe as mp

            self._detector = mp.solutions.face_detection.FaceDetection(
                model_selection=0,
                min_detection_confidence=0.55,
            )
        except (AttributeError, ImportError):
            self._detector = None

    @property
    def available(self) -> bool:
        """Whether MediaPipe face detection was initialized."""

        return self._detector is not None

    def locate(self, frame: Any) -> list[BoundingBox]:
        """Return valid face rectangles in a BGR image."""

        if self._detector is None:
            return []
        try:
            import cv2
        except ImportError:
            return []
        height, width = frame.shape[:2]
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._detector.process(rgb_frame)
        boxes: list[BoundingBox] = []
        for detection in result.detections or []:
            relative = detection.location_data.relative_bounding_box
            x = max(0, int(relative.xmin * width))
            y = max(0, int(relative.ymin * height))
            right = min(width, int((relative.xmin + relative.width) * width))
            bottom = min(height, int((relative.ymin + relative.height) * height))
            if right > x and bottom > y:
                boxes.append(BoundingBox(x, y, right - x, bottom - y))
        return boxes


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Calculate cosine similarity for equal-length numeric vectors."""

    if len(left) != len(right) or not left:
        raise ValueError("Embeddings must be non-empty and have equal dimensions")
    dot_product = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot_product / (left_norm * right_norm)


def best_embedding_match(
    embedding: Sequence[float],
    known_embeddings: Sequence[tuple[Student, Sequence[float]]],
    minimum_confidence: float,
) -> tuple[Student | None, float]:
    """Return the closest student when cosine confidence meets the threshold."""

    best_student: Student | None = None
    best_confidence = 0.0
    for student, known_embedding in known_embeddings:
        confidence = max(0.0, cosine_similarity(embedding, known_embedding) * 100)
        if confidence > best_confidence:
            best_student = student
            best_confidence = confidence
    if best_confidence < minimum_confidence:
        return None, best_confidence
    return best_student, best_confidence


def assign_unique_identities(
    embeddings: Sequence[Sequence[float] | None],
    known_embeddings: Sequence[tuple[Student, Sequence[float]]],
    minimum_confidence: float,
) -> list[tuple[Student | None, float]]:
    """Match faces to students so one student is never assigned to two faces.

    Pairs are assigned greedily from the highest confidence downwards, which
    prevents two look-alike faces in the same frame from both checking in the
    same student.
    """

    pairs: list[tuple[float, int, int]] = []
    best_scores = [0.0] * len(embeddings)
    for face_index, embedding in enumerate(embeddings):
        if not embedding:
            continue
        for student_index, (_, known) in enumerate(known_embeddings):
            try:
                confidence = max(0.0, cosine_similarity(embedding, known) * 100)
            except ValueError:
                continue
            best_scores[face_index] = max(best_scores[face_index], confidence)
            if confidence >= minimum_confidence:
                pairs.append((confidence, face_index, student_index))
    results: list[tuple[Student | None, float]] = [
        (None, score) for score in best_scores
    ]
    used_faces: set[int] = set()
    used_students: set[int] = set()
    for confidence, face_index, student_index in sorted(pairs, reverse=True):
        if face_index in used_faces or student_index in used_students:
            continue
        used_faces.add(face_index)
        used_students.add(student_index)
        results[face_index] = (known_embeddings[student_index][0], confidence)
    return results


def find_similar_student(
    embedding: Sequence[float],
    students: Sequence[Student],
    minimum_confidence: float,
    exclude_student_id: int | None = None,
) -> tuple[Student | None, float]:
    """Return an already registered student whose face matches this sample."""

    known = [
        (student, emb)
        for student in students
        if student.id != exclude_student_id
        and (emb := deserialize_embedding(student.embedding))
    ]
    if not known:
        return None, 0.0
    return best_embedding_match(embedding, known, minimum_confidence)


class FaceRecognitionEngine:
    """Run expensive face recognition periodically and cache identity boxes."""

    def __init__(
        self,
        locator: MediaPipeFaceLocator | None = None,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.locator = locator or MediaPipeFaceLocator()
        self._provider = provider
        self._last_run = 0.0
        self._cached_matches: list[FaceMatch] = []
        self._cached_by_track: dict[int, FaceMatch] = {}

    @property
    def detection_available(self) -> bool:
        """Whether a face locator is ready."""

        return self.locator.available

    def registration_embedding(self, frame: Any) -> list[float]:
        """Extract a face embedding from the largest face in an uploaded image."""

        if not self.locator.available:
            raise FaceEngineUnavailable("Tính năng phát hiện khuôn mặt MediaPipe không khả dụng")
        boxes = self.locator.locate(frame)
        if not boxes:
            raise ValueError("Không phát hiện khuôn mặt trong ảnh đăng ký")
        face_box = max(boxes, key=lambda box: box.width * box.height)
        return self._embedding_provider().embed(crop_face(frame, face_box))

    def recognize_if_due(
        self,
        frame: Any,
        students: Sequence[Student],
        tracked_boxes: Sequence[TrackedBox] | None = None,
        now: float | None = None,
    ) -> tuple[list[FaceMatch], bool]:
        """Recognize faces at the configured interval and reuse cached matches."""

        current_time = time.monotonic() if now is None else now
        if current_time - self._last_run < settings.recognition_interval_seconds:
            if tracked_boxes is not None:
                return self._project_cached_matches(tracked_boxes), False
            return self._cached_matches, False
        self._last_run = current_time
        candidates = (
            list(tracked_boxes)
            if tracked_boxes is not None
            else [TrackedBox(0, box) for box in self.locator.locate(frame)]
        )
        boxes = [candidate.box for candidate in candidates]
        if not boxes or not students:
            self._cached_matches = [
                FaceMatch(
                    candidate.box,
                    None,
                    None,
                    "Không rõ",
                    0.0,
                    candidate.track_id or None,
                )
                for candidate in candidates
            ]
            self._cache_tracked_matches()
            return self._cached_matches, True
        provider = self._embedding_provider()
        known_embeddings = []
        for student in students:
            emb = deserialize_embedding(student.embedding)
            if emb:
                known_embeddings.append((student, emb))
        embeddings: list[list[float] | None] = []
        for candidate in candidates:
            try:
                embeddings.append(provider.embed(crop_face(frame, candidate.box)))
            except (ValueError, RuntimeError):
                embeddings.append(None)
        identities = assign_unique_identities(
            embeddings, known_embeddings, settings.recognition_confidence
        )
        matches: list[FaceMatch] = []
        for candidate, (student, confidence) in zip(candidates, identities):
            matches.append(
                FaceMatch(
                    box=candidate.box,
                    student_id=student.id if student else None,
                    student_code=student.student_code if student else None,
                    fullname=student.fullname if student else "Không rõ",
                    confidence=confidence,
                    track_id=candidate.track_id or None,
                )
            )
        self._cached_matches = matches
        self._cache_tracked_matches()
        return matches, True

    def _cache_tracked_matches(self) -> None:
        self._cached_by_track = {
            match.track_id: match
            for match in self._cached_matches
            if match.track_id is not None
        }

    def _project_cached_matches(
        self, tracked_boxes: Sequence[TrackedBox]
    ) -> list[FaceMatch]:
        """Move cached identities to the current lightweight landmark boxes."""

        projected: list[FaceMatch] = []
        for tracked_box in tracked_boxes:
            cached = self._cached_by_track.get(tracked_box.track_id)
            if cached is None:
                projected.append(
                    FaceMatch(
                        tracked_box.box,
                        None,
                        None,
                        "Không rõ",
                        0.0,
                        tracked_box.track_id,
                    )
                )
                continue
            projected.append(
                FaceMatch(
                    tracked_box.box,
                    cached.student_id,
                    cached.student_code,
                    cached.fullname,
                    cached.confidence,
                    tracked_box.track_id,
                )
            )
        return projected

    def _embedding_provider(self) -> EmbeddingProvider:
        if self._provider is None:
            self._provider = DeepFaceEmbeddingProvider()
        return self._provider


def crop_face(frame: Any, box: BoundingBox) -> Any:
    """Crop a face rectangle from a BGR image."""

    return frame[box.y : box.y + box.height, box.x : box.x + box.width]


def closest_match(box: BoundingBox, matches: Sequence[FaceMatch]) -> FaceMatch | None:
    """Return the recognized box with the nearest center."""

    if not matches:
        return None
    center_x, center_y = box.center
    return min(
        matches,
        key=lambda match: (match.box.center[0] - center_x) ** 2
        + (match.box.center[1] - center_y) ** 2,
    )
