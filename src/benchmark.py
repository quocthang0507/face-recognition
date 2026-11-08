"""Measure the camera pipeline without a browser.

Examples::

    python -m src.benchmark --video lop_mau.mp4 --session
    python -m src.benchmark --camera 0 --frames 200 --data-dir src/data --session
    python -m src.benchmark --video lop_mau.mp4 --overlay   # old annotated mode

The script always works on a temporary copy of the data directory, so the
real classroom database is never modified.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import tempfile
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the frame pipeline.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--video", help="Video file to replay")
    source.add_argument("--camera", type=int, help="Webcam index")
    parser.add_argument("--frames", type=int, default=150, help="Frames to process")
    parser.add_argument("--width", type=int, default=640, help="Client max width")
    parser.add_argument("--quality", type=int, default=70, help="Client JPEG quality")
    parser.add_argument(
        "--data-dir",
        help="Copy this data directory (students, avatars) for realistic matching",
    )
    parser.add_argument(
        "--session", action="store_true", help="Start a lesson (enables behaviors)"
    )
    parser.add_argument(
        "--overlay", action="store_true", help="Measure the server-overlay mode"
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    return parser.parse_args()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))
    return ordered[index]


def main() -> None:
    args = parse_args()
    workdir = Path(tempfile.mkdtemp(prefix="classroom-bench-"))
    data_dir = workdir / "data"
    if args.data_dir:
        shutil.copytree(args.data_dir, data_dir)
    os.environ["FACE_APP_DATA_DIR"] = str(data_dir)
    os.environ["FACE_APP_DATABASE_URL"] = f"sqlite:///{data_dir / 'classroom.db'}"
    os.environ["FACE_APP_PROFILE"] = "true"

    import cv2

    from .database import SessionLocal, create_tables
    from .services import ClassroomService
    from .storage import PrivateStorage
    from .stream_processor import StreamProcessor

    create_tables()
    if args.session:
        with SessionLocal() as db:
            if ClassroomService.get_active_session(db) is None:
                ClassroomService.start_session(db, "Benchmark")

    capture = cv2.VideoCapture(args.video if args.video else args.camera)
    if not capture.isOpened():
        raise SystemExit("Không mở được nguồn video")

    processor = StreamProcessor(PrivateStorage())
    stages: dict[str, list[float]] = {}
    payload_bytes: list[int] = []
    upload_bytes: list[int] = []
    started = time.perf_counter()
    processed = 0
    try:
        while processed < args.frames:
            ok, frame = capture.read()
            if not ok:
                if args.video:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                break
            height, width = frame.shape[:2]
            if width > args.width:
                size = (args.width, round(height * args.width / width))
                frame = cv2.resize(frame, size)
            _, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality]
            )
            raw = encoded.tobytes()
            with SessionLocal() as db:
                result = processor.process(raw, db, server_overlay=args.overlay)
            payload = result.to_dict()
            for name, value in (payload.get("timings") or {}).items():
                stages.setdefault(name, []).append(value)
            payload_bytes.append(len(json.dumps(payload)))
            upload_bytes.append(len(raw))
            processed += 1
    finally:
        capture.release()
        elapsed = time.perf_counter() - started
        shutil.rmtree(workdir, ignore_errors=True)

    if not processed:
        raise SystemExit("Không xử lý được khung hình nào")
    report = {
        "frames": processed,
        "wall_fps": round(processed / elapsed, 2),
        "upload_kb_per_frame": round(statistics.mean(upload_bytes) / 1024, 1),
        "download_kb_per_frame": round(statistics.mean(payload_bytes) / 1024, 2),
        "stages_ms": {
            name: {
                "mean": round(statistics.mean(values), 2),
                "p50": round(percentile(values, 0.5), 2),
                "p95": round(percentile(values, 0.95), 2),
            }
            for name, values in stages.items()
        },
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print(f"Khung hình: {report['frames']}  ·  FPS thực tế: {report['wall_fps']}")
    print(
        f"Tải lên: {report['upload_kb_per_frame']} KB/khung  ·  "
        f"Tải xuống: {report['download_kb_per_frame']} KB/khung"
    )
    print(f"{'Bước':<12}{'TB (ms)':>10}{'p50':>10}{'p95':>10}")
    for name, values in report["stages_ms"].items():
        print(f"{name:<12}{values['mean']:>10}{values['p50']:>10}{values['p95']:>10}")


if __name__ == "__main__":
    main()
