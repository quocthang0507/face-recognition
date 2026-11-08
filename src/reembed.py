"""Recompute stored face embeddings after the embedding pipeline changes.

Run manually with ``python -m src.reembed``; the server also runs it in the
background at startup. Students are re-enrolled from their encrypted avatar,
so nobody needs to stand in front of the camera again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from .config import settings
from .services import StudentService
from .storage import PrivateStorage

logger = logging.getLogger("smart_classroom")


def reembed_outdated(
    db: Session,
    storage: PrivateStorage,
    embed: Callable[[bytes], list[float]],
) -> tuple[int, int]:
    """Re-embed students whose vector came from another pipeline.

    Returns ``(updated, failed)``. A failure keeps the previous embedding.
    """

    updated = failed = 0
    for student in StudentService.list_all(db):
        if not student.avatar_path:
            continue
        if student.embedding_model == settings.embedding_model_id:
            continue
        try:
            embedding = embed(storage.read_avatar(student.avatar_path))
        except Exception as exc:  # noqa: BLE001 - one bad avatar must not stop the rest
            logger.warning(
                "Không tính lại được khuôn mặt của %s: %s", student.student_code, exc
            )
            failed += 1
            continue
        StudentService.replace_embedding(db, student, embedding)
        updated += 1
    return updated, failed


def main() -> None:
    """Command-line entry point."""

    from .database import SessionLocal, create_tables
    from .face_engine import FaceRecognitionEngine
    from .stream_processor import decode_jpeg

    logging.basicConfig(level=logging.INFO)
    create_tables()
    engine = FaceRecognitionEngine()
    with SessionLocal() as db:
        updated, failed = reembed_outdated(
            db,
            PrivateStorage(),
            lambda content: engine.registration_embedding(decode_jpeg(content)),
        )
    print(f"Đã cập nhật {updated} học sinh, lỗi {failed}.")


if __name__ == "__main__":
    main()
