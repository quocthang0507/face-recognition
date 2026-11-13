"""Per-camera frame pipeline for recognition, attendance and behavior alerts."""

from __future__ import annotations

import base64
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Generic, Iterable, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import cache
from .behavior_engine import BehaviorEngine, FaceBehavior
from .config import settings
from .face_engine import (
    FaceEngineUnavailable,
    FaceMatch,
    FaceRecognitionEngine,
    Gallery,
    closest_match,
)
from .models import ClassroomSession, Student
from .services import (
    BehaviorLogService,
    CONSENT_GRANTED,
    ClassroomService,
    DomainError,
    StudentService,
)
from .storage import PrivateStorage
from .tracking import TrackedBox

BEHAVIOR_LABELS = {
    "SLEEPING": "Ngủ gục",
    "HAND_ON_FACE": "Chống tay",
    "CHEATING": "Quay cóp",
    "TALKING": "Nói chuyện",
}


T = TypeVar("T")


@dataclass
class FrameResult:
    """Frame metadata returned to the browser.

    The browser draws boxes and labels itself on top of the live video, so the
    annotated JPEG (``image_base64``) is only produced in the optional
    ``?overlay=server`` debug mode.
    """

    image_base64: str | None
    faces: list[dict[str, object]]
    behaviors: list[dict[str, object]]
    alerts: list[dict[str, object]]
    errors: list[str]
    attendance: list[dict[str, object]] = field(default_factory=list)
    session_id: int | None = None
    frame_size: tuple[int, int] | None = None
    timings: dict[str, float] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable frame payload."""

        payload: dict[str, object] = {
            "type": "frame",
            "faces": self.faces,
            "behaviors": self.behaviors,
            "alerts": self.alerts,
            "errors": self.errors,
            "attendance": self.attendance,
            "session_id": self.session_id,
        }
        if self.image_base64 is not None:
            payload["image"] = self.image_base64
        if self.frame_size is not None:
            width, height = self.frame_size
            payload["frame_size"] = {"width": width, "height": height}
        if self.timings is not None:
            payload["timings"] = self.timings
        return payload


class StageTimer:
    """Measure pipeline stages in milliseconds (``FACE_APP_PROFILE=true``)."""

    def __init__(self, enabled: bool | None = None) -> None:
        self.enabled = settings.profile if enabled is None else enabled
        self._started = time.perf_counter()
        self._stages: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time one block when profiling is enabled."""

        if not self.enabled:
            yield
            return
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self._stages[name] = round(self._stages.get(name, 0.0) + elapsed, 2)

    def result(self) -> dict[str, float]:
        """Return stage timings plus the total server time."""

        total = round((time.perf_counter() - self._started) * 1000, 2)
        return {**self._stages, "total": total}


class VersionedCache(Generic[T]):
    """Keep hot data in memory until it changes or a short TTL expires."""

    def __init__(
        self,
        name: str,
        loader: Callable[..., T],
        ttl: float | None = None,
    ) -> None:
        self.name = name
        self.loader = loader
        self.ttl = settings.cache_ttl_seconds if ttl is None else ttl
        self._value: T | None = None
        self._version: int | None = None
        self._loaded_at = 0.0

    def get(self, *args: Any, now: float | None = None) -> T:
        """Return the cached value, reloading it with ``loader(*args)`` if stale."""

        current_time = time.monotonic() if now is None else now
        current_version = cache.version(self.name)
        stale = (
            self._version != current_version
            or current_time - self._loaded_at >= self.ttl
        )
        if stale:
            self._value = self.loader(*args)
            self._version = current_version
            self._loaded_at = current_time
        return self._value  # type: ignore[return-value]

    def invalidate(self) -> None:
        """Force a reload on the next access."""

        self._version = None


class AttendanceStabilizer:
    """Require repeated confident recognition before marking attendance."""

    def __init__(self, required_frames: int | None = None) -> None:
        self.required_frames = required_frames or settings.attendance_frames
        self._streaks: dict[int, int] = defaultdict(int)

    def reset(self) -> None:
        """Forget streaks, e.g. when a new lesson starts on the same camera."""

        self._streaks.clear()

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
        class_id: int | None = None,
    ) -> None:
        self.storage = storage
        self.class_id = class_id
        self.face_engine = face_engine or FaceRecognitionEngine()
        self.behavior_engine = behavior_engine or BehaviorEngine()
        self.attendance = AttendanceStabilizer()
        self._session_id: int | None = None
        # Avoid two SQLite queries and a JSON decode of every embedding per frame.
        self._gallery = VersionedCache(
            "students",
            lambda db: Gallery.build(StudentService.recognizable(db, self.class_id)),
        )
        self._active_session = VersionedCache(
            "sessions",
            lambda db: ClassroomService.get_active_session(db, self.class_id),
        )

    @property
    def enabled_behaviors(self) -> frozenset[str]:
        """Return behavior checks enabled for this camera stream."""

        return self.behavior_engine.enabled_behaviors

    def set_enabled_behaviors(self, behavior_types: Iterable[str]) -> None:
        """Update behavior checks without restarting the camera stream."""

        self.behavior_engine.set_enabled_behaviors(behavior_types)

    def process(
        self, raw_jpeg: bytes, db: Session, server_overlay: bool = False
    ) -> FrameResult:
        """Decode and analyze one camera frame; annotate it only on request."""

        timer = StageTimer()
        with timer.stage("decode"):
            frame = decode_jpeg(raw_jpeg)
        with timer.stage("cache"):
            gallery = self._gallery.get(db)
            active_session = self._active_session.get(db)
        errors: list[str] = []
        with timer.stage("behavior"):
            behaviors = (
                self.behavior_engine.analyze(frame)
                if active_session is not None
                else []
            )
        tracked_boxes = [
            TrackedBox(behavior.track_id, behavior.box) for behavior in behaviors
        ]
        # When behavior analysis is skipped (no active session), pass None
        # so the face engine falls back to its own MediaPipe face locator.
        use_tracked_boxes = (
            tracked_boxes if (self.behavior_engine.available and behaviors) else None
        )
        try:
            with timer.stage("recognize"):
                matches, refreshed = self.face_engine.recognize_if_due(
                    frame,
                    list(gallery.students),
                    tracked_boxes=use_tracked_boxes,
                    gallery=gallery,
                )
        except FaceEngineUnavailable as exc:
            matches, refreshed = [], False
            errors.append(str(exc))
        current_session_id = active_session.id if active_session else None
        if current_session_id != self._session_id:
            # Streaks from a previous lesson must not leak into the new one,
            # otherwise students already counted would never reach the
            # threshold again and stay absent.
            self.attendance.reset()
            self.behavior_engine.reset()
            self._session_id = current_session_id
        checked_in: list[dict[str, object]] = []
        if active_session and refreshed:
            names = {match.student_id: match.fullname for match in matches}
            try:
                with timer.stage("attendance"):
                    for student_id in self.attendance.observe(matches):
                        consented = db.scalar(
                            select(Student.id).where(
                                Student.id == student_id,
                                Student.consent_status == CONSENT_GRANTED,
                            )
                        )
                        if not consented:
                            self._gallery.invalidate()
                            continue
                        if ClassroomService.mark_present(
                            db, active_session.id, student_id
                        ):
                            checked_in.append(
                                {
                                    "student_id": student_id,
                                    "fullname": names.get(student_id),
                                }
                            )
            except DomainError:
                # The cached lesson was finished by another worker process.
                self._active_session.invalidate()
        with timer.stage("alerts"):
            alerts = self._save_alerts(frame, behaviors, matches, active_session, db)
        image_base64: str | None = None
        if server_overlay:
            with timer.stage("overlay"):
                draw_overlay(frame, matches, behaviors)
                image_base64 = base64.b64encode(encode_jpeg(frame)).decode("ascii")
        height, width = frame.shape[:2]
        return FrameResult(
            image_base64=image_base64,
            faces=[match.to_dict() for match in matches],
            behaviors=[behavior.to_dict() for behavior in behaviors],
            alerts=alerts,
            errors=errors,
            attendance=checked_in,
            session_id=current_session_id,
            frame_size=(width, height),
            timings=timer.result(),
        )

    def _save_alerts(
        self,
        frame: Any,
        behaviors: list[FaceBehavior],
        matches: list[FaceMatch],
        active_session: ClassroomSession | None,
        db: Session,
    ) -> list[dict[str, object]]:
        alerts: list[dict[str, object]] = []
        snapshot_path: str | None = None
        persist_session_id: int | None = None
        if active_session is not None and any(behavior.alerts for behavior in behaviors):
            status = db.scalar(
                select(ClassroomSession.status).where(
                    ClassroomSession.id == active_session.id
                )
            )
            if status == "ACTIVE":
                persist_session_id = active_session.id
            elif hasattr(self, "_active_session"):
                self._active_session.invalidate()
        for behavior in behaviors:
            identity = next(
                (
                    match
                    for match in matches
                    if match.track_id is not None
                    and match.track_id == behavior.track_id
                ),
                None,
            ) or closest_match(behavior.box, matches)
            for behavior_type in behavior.alerts:
                alert = {
                    "id": None,
                    "behavior_type": behavior_type,
                    "label": BEHAVIOR_LABELS[behavior_type],
                    "student_id": identity.student_id if identity else None,
                    "fullname": identity.fullname if identity else "Không rõ",
                    "snapshot_url": None,
                }
                if persist_session_id is not None:
                    if snapshot_path is None:
                        # One evidence image per frame, shared by every alert.
                        snapshot_path = self.storage.save_snapshot(encode_jpeg(frame))
                    log = BehaviorLogService.create(
                        db,
                        session_id=persist_session_id,
                        behavior_type=behavior_type,
                        snapshot_path=snapshot_path,
                        student_id=identity.student_id if identity else None,
                    )
                    alert["id"] = log.id
                    alert["snapshot_url"] = f"/api/snapshots/{snapshot_path}"
                alerts.append(alert)
        return alerts


@lru_cache(maxsize=1)
def _overlay_font() -> Any:
    """Load the Unicode overlay font once instead of on every frame."""

    from PIL import ImageFont

    for candidate in (
        "Arial.ttf",
        "arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "DejaVuSans.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, 15)
        except OSError:
            continue
    return ImageFont.load_default()


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
        import numpy as np
    except ImportError:
        return
    for match in matches:
        box = match.box
        color = (40, 220, 130) if match.student_id else (70, 170, 255)
        cv2.rectangle(
            frame, (box.x, box.y), (box.x + box.width, box.y + box.height), color, 2
        )

    if not matches and not behaviors:
        return

    def draw_fallback():
        for match in matches:
            box = match.box
            color = (40, 220, 130) if match.student_id else (70, 170, 255)
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

    try:
        from PIL import Image, ImageDraw

        # Convert to PIL RGB for Unicode drawing
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)

        font = _overlay_font()

        for match in matches:
            box = match.box
            color = (130, 220, 40) if match.student_id else (255, 170, 70)  # RGB
            label = f"{match.fullname} {match.confidence:.0f}%"
            y_pos = max(5, box.y - 20)
            try:
                bbox = draw.textbbox((box.x, y_pos), label, font=font)
                draw.rectangle(bbox, fill=(0, 0, 0))
            except Exception:
                pass
            draw.text((box.x, y_pos), label, font=font, fill=color)

        for behavior in behaviors:
            if not behavior.alerts:
                continue
            label = ", ".join(BEHAVIOR_LABELS[item] for item in behavior.alerts)
            color = (230, 30, 30)  # RGB (Red)
            y_pos = behavior.box.y + behavior.box.height + 5
            try:
                bbox = draw.textbbox((behavior.box.x, y_pos), label, font=font)
                draw.rectangle(bbox, fill=(0, 0, 0))
            except Exception:
                pass
            draw.text(
                (behavior.box.x, y_pos),
                label,
                font=font,
                fill=color,
            )

        # Convert back to BGR and copy in-place
        bgr_img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        frame[:] = bgr_img
    except Exception as exc:
        print(f"Pillow drawing error: {exc}. Falling back to OpenCV draw.")
        draw_fallback()
