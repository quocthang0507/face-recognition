"""Tests for lightweight face-box tracking between recognition passes."""

from src.tracking import BoundingBox, CentroidBoxTracker


def test_tracker_keeps_id_when_face_moves_between_frames() -> None:
    tracker = CentroidBoxTracker()

    first = tracker.update([BoundingBox(10, 10, 40, 40)])
    second = tracker.update([BoundingBox(18, 13, 40, 40)])

    assert second[0].track_id == first[0].track_id
    assert second[0].box == BoundingBox(18, 13, 40, 40)


def test_tracker_keeps_ids_when_detection_order_changes() -> None:
    tracker = CentroidBoxTracker()

    first = tracker.update([BoundingBox(10, 10, 40, 40), BoundingBox(200, 10, 40, 40)])
    second = tracker.update([BoundingBox(205, 12, 40, 40), BoundingBox(15, 12, 40, 40)])

    assert second[0].track_id == first[1].track_id
    assert second[1].track_id == first[0].track_id


def test_tracker_expires_face_after_configured_missed_frames() -> None:
    tracker = CentroidBoxTracker(max_missed_frames=1)

    first = tracker.update([BoundingBox(10, 10, 40, 40)])
    tracker.update([])
    tracker.update([])
    replacement = tracker.update([BoundingBox(10, 10, 40, 40)])

    assert replacement[0].track_id != first[0].track_id
