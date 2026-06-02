"""Tests for camera-stream behavior configuration and live alerts."""

from src.behavior_engine import FaceBehavior
from src.stream_processor import StreamProcessor
from src.tracking import BoundingBox


class UnexpectedStorage:
    """Fail if a live alert without a classroom session tries to write evidence."""

    def save_snapshot(self, content: bytes) -> str:
        raise AssertionError("Live alerts outside a session must not persist snapshots")


def test_behavior_alert_is_returned_without_active_classroom_session() -> None:
    processor = StreamProcessor.__new__(StreamProcessor)
    processor.storage = UnexpectedStorage()
    behavior = FaceBehavior(
        box=BoundingBox(0, 0, 10, 10),
        track_id=1,
        track_key="face-1",
        ear=0.1,
        mar=0.02,
        pitch=20,
        yaw=0,
        roll=0,
        alerts=("SLEEPING",),
    )

    alerts = processor._save_alerts(
        frame=None,
        behaviors=[behavior],
        matches=[],
        active_session=None,
        db=None,
    )

    assert alerts == [
        {
            "id": None,
            "behavior_type": "SLEEPING",
            "label": "Ngủ gục",
            "student_id": None,
            "fullname": "Không rõ",
            "snapshot_url": None,
        }
    ]
