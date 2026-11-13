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


def test_stream_processor_skips_persisting_alerts_when_session_already_finished(
    session_factory,
) -> None:
    from src.services import BehaviorLogService, ClassService, ClassroomService

    class RecordingStorage:
        def __init__(self) -> None:
            self.saved = 0

        def save_snapshot(self, content: bytes) -> str:
            self.saved += 1
            return f"shot-{self.saved}.enc"

    with session_factory() as db:
        school_class = ClassService.create(db, "7A")
        classroom_session = ClassroomService.start_session(db, class_id=school_class.id)
        ClassroomService.finish_session(db, classroom_session.id)

        processor = StreamProcessor.__new__(StreamProcessor)
        processor.storage = RecordingStorage()
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
            active_session=classroom_session,
            db=db,
        )

        assert processor.storage.saved == 0
        assert BehaviorLogService.list_recent(db, session_id=classroom_session.id) == []
        assert alerts[0]["id"] is None
        assert alerts[0]["snapshot_url"] is None
