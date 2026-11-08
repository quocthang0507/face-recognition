"""MediaPipe landmark extraction and extensible classroom behavior detectors."""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from .config import settings
from .tracking import BoundingBox, CentroidBoxTracker

Point = tuple[float, float]
LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)
FACE_BOUNDARY = (10, 234, 93, 132, 152, 361, 323, 454)
POSE_LANDMARKS = (1, 152, 33, 263, 61, 291)
BEHAVIOR_TYPES = frozenset({"SLEEPING", "HAND_ON_FACE", "CHEATING", "TALKING"})
HEAD_POSE_BEHAVIORS = frozenset({"SLEEPING", "CHEATING", "TALKING"})


def euclidean_distance(left: Point, right: Point) -> float:
    """Return the two-dimensional Euclidean distance between points."""

    return math.hypot(left[0] - right[0], left[1] - right[1])


def eye_aspect_ratio(points: Sequence[Point]) -> float:
    """Calculate EAR for six ordered eye landmarks."""

    if len(points) != 6:
        raise ValueError("EAR requires exactly six eye landmarks")
    horizontal = 2 * euclidean_distance(points[0], points[3])
    if not horizontal:
        return 0.0
    return (
        euclidean_distance(points[1], points[5])
        + euclidean_distance(points[2], points[4])
    ) / horizontal


def mouth_aspect_ratio(
    left_corner: Point, right_corner: Point, upper_lip: Point, lower_lip: Point
) -> float:
    """Calculate mouth opening ratio from lip landmarks."""

    width = euclidean_distance(left_corner, right_corner)
    return euclidean_distance(upper_lip, lower_lip) / width if width else 0.0


def minimum_relative_hand_face_distance(
    hand_points: Sequence[Point],
    face_points: Sequence[Point],
    face_width: float,
) -> float:
    """Return the smallest hand-to-face distance relative to face width."""

    if not hand_points or not face_points or face_width <= 0:
        return math.inf
    return (
        min(
            euclidean_distance(hand, face)
            for hand in hand_points
            for face in face_points
        )
        / face_width
    )


def estimate_head_pose(
    image_points: Sequence[Point], frame_shape: Sequence[int]
) -> tuple[float, float, float]:
    """Estimate pitch, yaw and roll in degrees using OpenCV solvePnP."""

    if len(image_points) != 6:
        raise ValueError("Head pose requires exactly six image points")
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.0, 0.0, 0.0
    model_points = np.array(
        [
            (0.0, 0.0, 0.0),
            (0.0, -330.0, -65.0),
            (-225.0, 170.0, -135.0),
            (225.0, 170.0, -135.0),
            (-150.0, -150.0, -125.0),
            (150.0, -150.0, -125.0),
        ],
        dtype="double",
    )
    height, width = frame_shape[:2]
    focal_length = float(width)
    camera_matrix = np.array(
        [
            (focal_length, 0.0, width / 2),
            (0.0, focal_length, height / 2),
            (0.0, 0.0, 1.0),
        ],
        dtype="double",
    )
    success, rotation_vector, _ = cv2.solvePnP(
        model_points,
        np.array(image_points, dtype="double"),
        camera_matrix,
        np.zeros((4, 1)),
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        return 0.0, 0.0, 0.0
    rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
    angles, *_ = cv2.RQDecomp3x3(rotation_matrix)
    return float(angles[0]), float(angles[1]), float(angles[2])


@dataclass(frozen=True)
class DetectorContext:
    """Measurements used by behavior detectors for one face."""

    track_key: str
    now: float
    ear: float
    mar: float
    pitch: float
    yaw: float
    roll: float
    hand_face_distance: float
    face_count: int


class RateLimiter:
    """Allow an expensive step to run at most ``fps`` times per second."""

    def __init__(self, fps: float) -> None:
        self.interval = 1.0 / fps if fps > 0 else 0.0
        self._last_run = -math.inf

    def due(self, now: float) -> bool:
        """Return true (and record the run) when the next run is allowed."""

        if now - self._last_run + 1e-9 < self.interval:
            return False
        self._last_run = now
        return True


@dataclass
class TimedState:
    """Per-face duration and cooldown state."""

    started_at: float | None = None
    last_alert_at: float = -math.inf


class BehaviorDetector(ABC):
    """Open extension point for one abnormal classroom behavior."""

    behavior_type: str

    def __init__(self, duration_seconds: float, cooldown_seconds: float = 10.0) -> None:
        self.duration_seconds = duration_seconds
        self.cooldown_seconds = cooldown_seconds
        self.states: dict[str, TimedState] = defaultdict(TimedState)

    def evaluate(self, context: DetectorContext) -> bool:
        """Update temporal state and return true once per alert cooldown."""

        state = self.states[context.track_key]
        if not self.is_active(context):
            state.started_at = None
            return False
        if state.started_at is None:
            state.started_at = context.now
        long_enough = context.now - state.started_at >= self.duration_seconds
        cooled_down = context.now - state.last_alert_at >= self.cooldown_seconds
        if long_enough and cooled_down:
            state.last_alert_at = context.now
            return True
        return False

    def reset(self) -> None:
        """Discard temporal state when this detector is disabled."""

        self.states.clear()

    @abstractmethod
    def is_active(self, context: DetectorContext) -> bool:
        """Return whether measurements currently indicate this behavior."""


class SleepingDetector(BehaviorDetector):
    """Detect continuously closed eyes together with downward head pitch."""

    behavior_type = "SLEEPING"

    def __init__(self) -> None:
        super().__init__(duration_seconds=3.0)

    def is_active(self, context: DetectorContext) -> bool:
        return context.ear < 0.21 and context.pitch > 12.0


class HandOnFaceDetector(BehaviorDetector):
    """Detect a hand resting on cheek or chin."""

    behavior_type = "HAND_ON_FACE"

    def __init__(self) -> None:
        super().__init__(duration_seconds=2.0)

    def is_active(self, context: DetectorContext) -> bool:
        return context.hand_face_distance < 0.18


class CheatingDetector(BehaviorDetector):
    """Detect prolonged looking sideways or down."""

    behavior_type = "CHEATING"

    def __init__(self) -> None:
        super().__init__(duration_seconds=2.0)

    def is_active(self, context: DetectorContext) -> bool:
        return abs(context.yaw) > 30.0 or context.pitch > 25.0


class TalkingDetector(BehaviorDetector):
    """Detect repeated mouth state changes while facing another student."""

    behavior_type = "TALKING"

    def __init__(self) -> None:
        super().__init__(duration_seconds=0.0)
        self._transitions: dict[str, deque[tuple[float, bool]]] = defaultdict(deque)
        self._last_open: dict[str, bool] = {}

    def is_active(self, context: DetectorContext) -> bool:
        mouth_open = context.mar > 0.08
        last_open = self._last_open.get(context.track_key)
        transitions = self._transitions[context.track_key]
        if last_open is not None and last_open != mouth_open:
            transitions.append((context.now, mouth_open))
        self._last_open[context.track_key] = mouth_open
        while transitions and context.now - transitions[0][0] > 4.0:
            transitions.popleft()
        facing_peer = context.face_count > 1 and abs(context.yaw) > 12.0
        return facing_peer and len(transitions) >= 4

    def reset(self) -> None:
        """Discard mouth-transition history when talking checks are disabled."""

        super().reset()
        self._transitions.clear()
        self._last_open.clear()


@dataclass(frozen=True)
class FaceBehavior:
    """Measurements and emitted alerts for a face in the current frame."""

    box: BoundingBox
    track_id: int
    track_key: str
    ear: float
    mar: float
    pitch: float
    yaw: float
    roll: float
    alerts: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable behavior result."""

        return {
            "box": self.box.to_dict(),
            "track_id": self.track_id,
            "track_key": self.track_key,
            "ear": round(self.ear, 3),
            "mar": round(self.mar, 3),
            "pitch": round(self.pitch, 1),
            "yaw": round(self.yaw, 1),
            "roll": round(self.roll, 1),
            "alerts": list(self.alerts),
        }

    def without_alerts(self) -> "FaceBehavior":
        """Return a copy reused between analysis runs that emits no new alert."""

        return replace(self, alerts=())


class BehaviorEngine:
    """Extract MediaPipe landmarks and run each registered detector."""

    def __init__(
        self,
        detectors: Sequence[BehaviorDetector] | None = None,
        enabled_behaviors: Iterable[str] | None = None,
        behavior_fps: float | None = None,
        hand_fps: float | None = None,
        max_faces: int | None = None,
    ) -> None:
        self.detectors = list(
            detectors
            or (
                SleepingDetector(),
                HandOnFaceDetector(),
                CheatingDetector(),
                TalkingDetector(),
            )
        )
        self._enabled_behaviors = normalize_behavior_types(
            BEHAVIOR_TYPES if enabled_behaviors is None else enabled_behaviors
        )
        self._face_mesh: Any | None = None
        self._hands: Any | None = None
        self._tracker = CentroidBoxTracker()
        # Behavior rules need 2-3 s of evidence, so analysing every camera frame
        # wastes CPU. Results are reused between scheduled runs.
        self._behavior_rate = RateLimiter(
            settings.behavior_fps if behavior_fps is None else behavior_fps
        )
        self._hand_rate = RateLimiter(
            settings.hand_fps if hand_fps is None else hand_fps
        )
        self._last_results: list[FaceBehavior] = []
        self._last_hands: list[list[Point]] = []
        face_limit = max(1, max_faces or settings.max_faces)
        try:
            import mediapipe as mp

            # Iris refinement is not used by any detector and costs extra time.
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=face_limit,
                refine_landmarks=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._hands = mp.solutions.hands.Hands(
                max_num_hands=face_limit,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        except (AttributeError, ImportError):
            self._face_mesh = None
            self._hands = None

    @property
    def available(self) -> bool:
        """Whether MediaPipe landmark models were initialized."""

        return self._face_mesh is not None and self._hands is not None

    @property
    def enabled_behaviors(self) -> frozenset[str]:
        """Return the behavior checks currently enabled for this camera stream."""

        return self._enabled_behaviors

    def set_enabled_behaviors(self, behavior_types: Iterable[str]) -> None:
        """Enable selected checks and reset state for checks that were disabled."""

        enabled_behaviors = normalize_behavior_types(behavior_types)
        disabled_behaviors = self._enabled_behaviors - enabled_behaviors
        for detector in self.detectors:
            if detector.behavior_type in disabled_behaviors:
                detector.reset()
        self._enabled_behaviors = enabled_behaviors

    def evaluate_detectors(self, context: DetectorContext) -> tuple[str, ...]:
        """Evaluate only checks selected by the current camera client."""

        return tuple(
            detector.behavior_type
            for detector in self.detectors
            if detector.behavior_type in self._enabled_behaviors
            and detector.evaluate(context)
        )

    def analyze(self, frame: Any, now: float | None = None) -> list[FaceBehavior]:
        """Analyze all faces and hands found in one BGR frame."""

        if not self.available:
            return []
        current_time = time.monotonic() if now is None else now
        if not self._behavior_rate.due(current_time):
            return [behavior.without_alerts() for behavior in self._last_results]
        try:
            import cv2
        except ImportError:
            return []
        height, width = frame.shape[:2]
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_result = self._face_mesh.process(rgb_frame)
        if "HAND_ON_FACE" not in self._enabled_behaviors:
            self._last_hands = []
        elif self._hand_rate.due(current_time):
            hand_result = self._hands.process(rgb_frame)
            self._last_hands = [
                [(point.x * width, point.y * height) for point in landmarks.landmark]
                for landmarks in hand_result.multi_hand_landmarks or []
            ]
        hands = self._last_hands
        faces = face_result.multi_face_landmarks or []
        face_points = [
            [(point.x * width, point.y * height) for point in face.landmark]
            for face in faces
        ]
        tracked_boxes = self._tracker.update(
            [_face_box(points, width, height) for points in face_points]
        )
        results: list[FaceBehavior] = []
        for points, tracked_box in zip(face_points, tracked_boxes):
            box = tracked_box.box
            ear = 0.0
            if "SLEEPING" in self._enabled_behaviors:
                ear = (
                    eye_aspect_ratio([points[i] for i in LEFT_EYE])
                    + eye_aspect_ratio([points[i] for i in RIGHT_EYE])
                ) / 2
            mar = 0.0
            if "TALKING" in self._enabled_behaviors:
                mar = mouth_aspect_ratio(
                    points[61], points[291], points[13], points[14]
                )
            pitch, yaw, roll = 0.0, 0.0, 0.0
            if self._enabled_behaviors & HEAD_POSE_BEHAVIORS:
                pitch, yaw, roll = estimate_head_pose(
                    [points[i] for i in POSE_LANDMARKS], frame.shape
                )
            hand_distance = math.inf
            if "HAND_ON_FACE" in self._enabled_behaviors:
                hand_distance = min(
                    (
                        minimum_relative_hand_face_distance(
                            hand, [points[i] for i in FACE_BOUNDARY], box.width
                        )
                        for hand in hands
                    ),
                    default=math.inf,
                )
            track_key = f"face-{tracked_box.track_id}"
            context = DetectorContext(
                track_key=track_key,
                now=current_time,
                ear=ear,
                mar=mar,
                pitch=pitch,
                yaw=yaw,
                roll=roll,
                hand_face_distance=hand_distance,
                face_count=len(faces),
            )
            alerts = self.evaluate_detectors(context)
            results.append(
                FaceBehavior(
                    box,
                    tracked_box.track_id,
                    track_key,
                    ear,
                    mar,
                    pitch,
                    yaw,
                    roll,
                    alerts,
                )
            )
        self._last_results = results
        return results


def _face_box(points: Sequence[Point], width: int, height: int) -> BoundingBox:
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    left = max(0, int(min(x_values)))
    top = max(0, int(min(y_values)))
    right = min(width, int(max(x_values)))
    bottom = min(height, int(max(y_values)))
    return BoundingBox(left, top, max(1, right - left), max(1, bottom - top))


def normalize_behavior_types(behavior_types: Iterable[str]) -> frozenset[str]:
    """Validate and normalize behavior names received from a camera client."""

    normalized = frozenset(behavior_types)
    unknown = normalized - BEHAVIOR_TYPES
    if unknown:
        raise ValueError(f"Unknown behavior types: {', '.join(sorted(unknown))}")
    return normalized
