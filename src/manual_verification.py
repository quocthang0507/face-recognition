"""Webcam preview for manually verifying MediaPipe tracking and behaviors."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from typing import Any

from .behavior_engine import BehaviorEngine, FaceBehavior
from .stream_processor import BEHAVIOR_LABELS


def parse_args() -> argparse.Namespace:
    """Parse webcam verification command-line options."""

    parser = argparse.ArgumentParser(
        description="Preview face tracks and behavior measurements from a webcam."
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Stop after this many seconds. Zero runs until q is pressed.",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Capture metrics without opening an OpenCV window.",
    )
    return parser.parse_args()


def run(camera_index: int, duration: float, no_preview: bool) -> dict[str, object]:
    """Capture webcam frames and return a compact verification summary."""

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for webcam verification") from exc
    if no_preview and duration <= 0:
        raise ValueError("--no-preview requires a positive --duration")
    behavior_engine = BehaviorEngine()
    if not behavior_engine.available:
        raise RuntimeError("MediaPipe Face Mesh and Hands are not available")
    camera = cv2.VideoCapture(camera_index)
    if not camera.isOpened():
        raise RuntimeError(f"Could not open webcam index {camera_index}")
    started_at = time.monotonic()
    frames = 0
    maximum_faces = 0
    observed_tracks: set[int] = set()
    alert_counts: Counter[str] = Counter()
    try:
        while True:
            success, frame = camera.read()
            if not success:
                raise RuntimeError("Could not read a frame from the webcam")
            behaviors = behavior_engine.analyze(frame)
            frames += 1
            maximum_faces = max(maximum_faces, len(behaviors))
            for behavior in behaviors:
                observed_tracks.add(behavior.track_id)
                alert_counts.update(behavior.alerts)
                _draw_behavior(frame, behavior)
            elapsed = time.monotonic() - started_at
            if duration > 0 and elapsed >= duration:
                break
            if not no_preview:
                cv2.imshow(
                    "Smart Classroom Manual Verification - press q to stop", frame
                )
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        camera.release()
        if not no_preview:
            cv2.destroyAllWindows()
    elapsed = time.monotonic() - started_at
    return {
        "frames": frames,
        "elapsed_seconds": round(elapsed, 2),
        "fps": round(frames / elapsed, 1) if elapsed else 0.0,
        "maximum_faces": maximum_faces,
        "observed_track_ids": sorted(observed_tracks),
        "alerts": dict(sorted(alert_counts.items())),
    }


def _draw_behavior(frame: Any, behavior: FaceBehavior) -> None:
    """Draw measurements and emitted alerts for visual manual inspection."""

    import cv2

    box = behavior.box
    cv2.rectangle(
        frame,
        (box.x, box.y),
        (box.x + box.width, box.y + box.height),
        (40, 220, 130),
        2,
    )
    measurements = (
        f"track={behavior.track_id} EAR={behavior.ear:.2f} MAR={behavior.mar:.2f} "
        f"P={behavior.pitch:.0f} Y={behavior.yaw:.0f} R={behavior.roll:.0f}"
    )
    cv2.putText(
        frame,
        measurements,
        (box.x, max(22, box.y - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (40, 220, 130),
        2,
    )
    if behavior.alerts:
        labels = ", ".join(BEHAVIOR_LABELS[item] for item in behavior.alerts)
        cv2.putText(
            frame,
            labels,
            (box.x, box.y + box.height + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (30, 30, 230),
            2,
        )


def main() -> None:
    """Run webcam verification and print machine-readable metrics."""

    args = parse_args()
    try:
        summary = run(args.camera_index, args.duration, args.no_preview)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
