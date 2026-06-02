"""Per-camera frame pipeline for recognition, attendance and behavior alerts."""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .behavior_engine import BehaviorEngine, FaceBehavior
from .config import settings
from .face_engine import (
    FaceEngineUnavailable,
    FaceMatch,
    FaceRecognitionEngine,
    closest_match,
)
from .models import ClassroomSession
from .services import BehaviorLogService, ClassroomService, StudentService
from .storage import PrivateStorage

BEHAVIOR_LABELS = {
    "SLEEPING": "Sleeping",
    "HAND_ON_FACE": "Hand on face",
    "CHEATING": "Looking away",
    "TALKING": "Talking",
}


@dataclass
class FrameResult:
    """Processed JPEG and JSON metadata returned to the browser."""

    image_base64: str
    faces: list[dict[str, object]]
    behaviors: list[dict[str, object]]
    alerts: list[dict[str, object]]
    errors: list[str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable frame payload."""

        return {
            "type": "frame",
            "image": self.image_base64,
            "faces": self.faces,
            "behaviors": self.behaviors,
            "alerts": self.alerts,
            "errors": self.errors,
        }


class AttendanceStabilizer:
    """Require repeated confident recognition before marking attendance."""

    def __init__(self, required_frames: int | None = None) -> None:
        self.required_frames = required_frames or settings.attendance_frames
        self._streaks: dict[int, int] = defaultdict(int)

    def observe(self, matches: list[FaceMatch]) -> list[int]:
        """Return student IDs that have reached the attendance threshold."""

        confident_ids = {
            match.student_id
            for match in matches
            if match.student_id is not None
            and match.confidence >= settings.recognition_confidence
        }
        for student_id in list(self._streaks):
            if student_id not in confident_ids:
                self._streaks[student_id] = 0
        confirmed: list[int] = []
        for student_id in confident_ids:
            self._streaks[student_id] += 1
            if self._streaks[student_id] == self.required_frames:
                confirmed.append(student_id)
        return confirmed


class StreamProcessor:
    """Process one WebSocket camera stream without blocking the event loop."""

    def __init__(
        self,
        storage: PrivateStorage,
        face_engine: FaceRecognitionEngine | None = None,
        behavior_engine: BehaviorEngine | None = None,
    ) -> None:
        self.storage = storage
        self.face_engine = face_engine or FaceRecognitionEngine()
        self.behavior_engine = behavior_engine or BehaviorEngine()
        self.attendance = AttendanceStabilizer()

    def process(self, raw_jpeg: bytes, db: Session) -> FrameResult:
        """Decode, analyze, annotate and encode one camera frame."""

        frame = decode_jpeg(raw_jpeg)
        students = StudentService.list_all(db)
        errors: list[str] = []
        try:
            matches, refreshed = self.face_engine.recognize_if_due(frame, students)
        except FaceEngineUnavailable as exc:
            matches, refreshed = [], False
            errors.append(str(exc))
        active_session = ClassroomService.get_active_session(db)
        if active_session and refreshed:
            for student_id in self.attendance.observe(matches):
                ClassroomService.mark_present(db, active_session.id, student_id)
        behaviors = self.behavior_engine.analyze(frame)
        alerts = self._save_alerts(frame, behaviors, matches, active_session, db)
        draw_overlay(frame, matches, behaviors)
        encoded = encode_jpeg(frame)
        return FrameResult(
            image_base64=base64.b64encode(encoded).decode("ascii"),
            faces=[match.to_dict() for match in matches],
            behaviors=[behavior.to_dict() for behavior in behaviors],
            alerts=alerts,
            errors=errors,
        )

    def _save_alerts(
        self,
        frame: Any,
        behaviors: list[FaceBehavior],
        matches: list[FaceMatch],
        active_session: ClassroomSession | None,
        db: Session,
    ) -> list[dict[str, object]]:
        if active_session is None:
            return []
        alerts: list[dict[str, object]] = []
        snapshot: bytes | None = None
        for behavior in behaviors:
            identity = closest_match(behavior.box, matches)
            for behavior_type in behavior.alerts:
                if snapshot is None:
                    snapshot = encode_jpeg(frame)
                snapshot_path = self.storage.save_snapshot(snapshot)
                log = BehaviorLogService.create(
                    db,
                    session_id=active_session.id,
                    behavior_type=behavior_type,
                    snapshot_path=snapshot_path,
                    student_id=identity.student_id if identity else None,
                )
                alerts.append(
                    {
                        "id": log.id,
                        "behavior_type": behavior_type,
                        "label": BEHAVIOR_LABELS[behavior_type],
                        "student_id": identity.student_id if identity else None,
                        "fullname": identity.fullname if identity else "Unknown",
                        "snapshot_url": f"/api/snapshots/{snapshot_path}",
                    }
                )
        return alerts


def decode_jpeg(content: bytes) -> Any:
    """Decode browser JPEG bytes into an OpenCV BGR image."""

    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("OpenCV and numpy are required to process video") from exc
    frame = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Invalid JPEG frame")
    return frame


def encode_jpeg(frame: Any) -> bytes:
    """Encode an OpenCV BGR image as JPEG bytes."""

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required to process video") from exc
    success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not success:
        raise ValueError("Could not encode JPEG frame")
    return encoded.tobytes()


def draw_overlay(
    frame: Any, matches: list[FaceMatch], behaviors: list[FaceBehavior]
) -> None:
    """Draw face labels, boxes and emitted alerts onto a BGR frame."""

    try:
        import cv2
    except ImportError:
        return
    for match in matches:
        box = match.box
        color = (40, 220, 130) if match.student_id else (70, 170, 255)
        cv2.rectangle(
            frame, (box.x, box.y), (box.x + box.width, box.y + box.height), color, 2
        )
        label = f"{match.fullname} {match.confidence:.0f}%"
        cv2.putText(
            frame,
            label,
            (box.x, max(22, box.y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )
    for behavior in behaviors:
        if not behavior.alerts:
            continue
        label = ", ".join(BEHAVIOR_LABELS[item] for item in behavior.alerts)
        cv2.putText(
            frame,
            label,
            (behavior.box.x, behavior.box.y + behavior.box.height + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (30, 30, 230),
            2,
        )
