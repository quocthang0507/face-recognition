"""Lightweight bounding-box tracking for faces between recognition passes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class BoundingBox:
    """Pixel coordinates for a detected face rectangle."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> tuple[float, float]:
        """Return the center point of this rectangle."""

        return self.x + self.width / 2, self.y + self.height / 2

    @property
    def diagonal(self) -> float:
        """Return the rectangle diagonal used to normalize movement."""

        return math.hypot(self.width, self.height)

    def to_dict(self) -> dict[str, int]:
        """Return a JSON-serializable box."""

        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class TrackedBox:
    """A current face rectangle associated with a stable local track ID."""

    track_id: int
    box: BoundingBox


@dataclass
class _TrackState:
    box: BoundingBox
    missed_frames: int = 0


class CentroidBoxTracker:
    """Associate nearby face rectangles without running a recognition model."""

    def __init__(
        self,
        max_missed_frames: int = 8,
        max_normalized_distance: float = 1.5,
    ) -> None:
        self.max_missed_frames = max_missed_frames
        self.max_normalized_distance = max_normalized_distance
        self._next_track_id = 1
        self._tracks: dict[int, _TrackState] = {}

    def update(self, boxes: Sequence[BoundingBox]) -> list[TrackedBox]:
        """Match current boxes to existing tracks and return input-order results."""

        assignments = self._match(boxes)
        matched_tracks = set(assignments.values())
        for track_id, state in list(self._tracks.items()):
            if track_id not in matched_tracks:
                state.missed_frames += 1
                if state.missed_frames > self.max_missed_frames:
                    del self._tracks[track_id]
        tracked_boxes: list[TrackedBox] = []
        for detection_index, box in enumerate(boxes):
            track_id = assignments.get(detection_index)
            if track_id is None:
                track_id = self._next_track_id
                self._next_track_id += 1
                self._tracks[track_id] = _TrackState(box)
            else:
                state = self._tracks[track_id]
                state.box = box
                state.missed_frames = 0
            tracked_boxes.append(TrackedBox(track_id, box))
        return tracked_boxes

    def _match(self, boxes: Sequence[BoundingBox]) -> dict[int, int]:
        candidates: list[tuple[float, int, int]] = []
        for detection_index, box in enumerate(boxes):
            for track_id, state in self._tracks.items():
                distance = _normalized_center_distance(state.box, box)
                if distance <= self.max_normalized_distance:
                    candidates.append((distance, detection_index, track_id))
        assignments: dict[int, int] = {}
        used_tracks: set[int] = set()
        for _, detection_index, track_id in sorted(candidates):
            if detection_index not in assignments and track_id not in used_tracks:
                assignments[detection_index] = track_id
                used_tracks.add(track_id)
        return assignments


def _normalized_center_distance(left: BoundingBox, right: BoundingBox) -> float:
    """Return center distance relative to the larger face diagonal."""

    distance = math.dist(left.center, right.center)
    scale = max(left.diagonal, right.diagonal)
    return distance / scale if scale else math.inf
