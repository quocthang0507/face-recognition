"""FastAPI application for smart classroom monitoring."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    AuthenticationError,
    issue_teacher_token,
    password_matches,
    verify_teacher_token,
)
from .config import BASE_DIR, settings
from .database import SessionLocal, create_tables, get_db
from .face_engine import FaceEngineUnavailable, FaceRecognitionEngine
from .models import Student
from .services import (
    BehaviorLogService,
    ClassroomService,
    DomainError,
    StudentService,
)
from .storage import PrivateStorage
from .stream_processor import BEHAVIOR_LABELS, StreamProcessor, decode_jpeg

storage = PrivateStorage()


class LoginRequest(BaseModel):
    """Teacher login payload."""

    password: str


def _cleanup_expired_logs() -> None:
    with SessionLocal() as db:
        BehaviorLogService.cleanup_old(db, storage, settings.retention_days)


def _preload_models() -> None:
    try:
        from .face_engine import FaceRecognitionEngine
        engine = FaceRecognitionEngine()
        if engine.detection_available:
            engine._embedding_provider()
    except Exception as exc:
        print(f"Lỗi tải trước mô hình AI: {exc}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize tables and retention cleanup at application startup."""

    create_tables()
    await asyncio.to_thread(_cleanup_expired_logs)
    asyncio.create_task(asyncio.to_thread(_preload_models))
    cleanup_task = asyncio.create_task(_retention_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()


async def _retention_cleanup_loop() -> None:
    """Prune expired audit snapshots once a day while the server is running."""

    while True:
        await asyncio.sleep(24 * 60 * 60)
        await asyncio.to_thread(_cleanup_expired_logs)


app = FastAPI(title="Smart Classroom", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def require_teacher(
    request: Request,
    token: Annotated[str | None, Cookie(alias=settings.cookie_name)] = None,
) -> None:
    """Reject API calls without a valid teacher cookie."""

    _require_secure_request(request)
    try:
        verify_teacher_token(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _require_secure_request(request: Request) -> None:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if settings.secure_transport_only and request.url.scheme != "https":
        if forwarded_proto != "https":
            raise HTTPException(status_code=400, detail="Yêu cầu kết nối bảo mật HTTPS")


def _domain_error(exc: DomainError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """Serve the teacher dashboard."""

    return (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Serve the favicon image."""

    return FileResponse(BASE_DIR / "static" / "favicon.png")


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response) -> dict[str, str]:
    """Authenticate the teacher and set an HttpOnly cookie."""

    if not password_matches(payload.password):
        raise HTTPException(status_code=401, detail="Mật khẩu giáo viên không chính xác")
    response.set_cookie(
        key=settings.cookie_name,
        value=issue_teacher_token(),
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        max_age=settings.token_ttl_seconds,
    )
    return {"status": "authenticated"}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, str]:
    """Delete the teacher session cookie."""

    response.delete_cookie(settings.cookie_name)
    return {"status": "logged_out"}


@app.get("/api/auth/status", dependencies=[Depends(require_teacher)])
def auth_status() -> dict[str, str]:
    """Confirm that the current cookie is valid."""

    return {"status": "authenticated"}


@app.get("/api/health")
def health() -> dict[str, object]:
    """Expose runtime readiness without leaking student data."""

    face_engine = FaceRecognitionEngine()
    return {
        "status": "ok",
        "face_detection": face_engine.detection_available,
        "secure_transport_only": settings.secure_transport_only,
    }


@app.get("/api/students", dependencies=[Depends(require_teacher)])
def list_students(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, object]]:
    """Return registered students."""

    return [_student_payload(student) for student in StudentService.list_all(db)]


@app.post("/register", include_in_schema=False, dependencies=[Depends(require_teacher)])
@app.post("/api/students/register", dependencies=[Depends(require_teacher)])
async def register_student(
    student_code: Annotated[str, Form()],
    fullname: Annotated[str, Form()],
    db: Annotated[Session, Depends(get_db)],
    image: UploadFile | None = None,
) -> dict[str, object]:
    """Register a student from one webcam JPEG or uploaded image (optional)."""

    if db.scalar(select(Student).where(Student.student_code == student_code.strip())):
        raise HTTPException(status_code=409, detail="Mã học sinh đã tồn tại")

    embedding = None
    avatar_path = None

    if image is not None and image.filename:
        content = await image.read()
        if content:
            if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise HTTPException(status_code=415, detail="Yêu cầu định dạng ảnh JPEG, PNG hoặc WebP")
            if len(content) > 5 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Dung lượng ảnh phải nằm trong khoảng từ 1B đến 5MB")
            try:
                frame = await asyncio.to_thread(decode_jpeg, content)
                embedding = await asyncio.to_thread(
                    FaceRecognitionEngine().registration_embedding, frame
                )
                avatar_path = storage.save_avatar(content)
            except FaceEngineUnavailable as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        student = StudentService.register(
            db, student_code, fullname, embedding, avatar_path
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _student_payload(student)


@app.get("/api/avatars/{name}", dependencies=[Depends(require_teacher)])
def get_avatar(name: str) -> Response:
    """Decrypt and return one protected avatar image."""

    try:
        return Response(storage.read_avatar(name), media_type="image/jpeg")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh đại diện") from exc


@app.post("/api/sessions", dependencies=[Depends(require_teacher)])
def start_session(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    """Start a classroom session."""

    try:
        classroom_session = ClassroomService.start_session(db)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _session_payload(db, classroom_session.id)


@app.get("/api/sessions/active", dependencies=[Depends(require_teacher)])
def active_session(db: Annotated[Session, Depends(get_db)]) -> dict[str, object] | None:
    """Return the active classroom session and attendance."""

    classroom_session = ClassroomService.get_active_session(db)
    return _session_payload(db, classroom_session.id) if classroom_session else None


@app.post("/api/sessions/{session_id}/finish", dependencies=[Depends(require_teacher)])
def finish_session(
    session_id: int, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    """Finish the requested classroom session."""

    try:
        classroom_session = ClassroomService.finish_session(db, session_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return {"id": classroom_session.id, "status": classroom_session.status}


@app.post("/api/sessions/{session_id}/pick", dependencies=[Depends(require_teacher)])
def pick_student(
    session_id: int, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    """Pick one uncalled present student."""

    try:
        selected = ClassroomService.pick_random(db, session_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _student_payload(selected.student)


@app.post(
    "/api/sessions/{session_id}/reset-called",
    dependencies=[Depends(require_teacher)],
)
def reset_called(
    session_id: int, db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    """Reset the random-call round."""

    try:
        ClassroomService.reset_called(db, session_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return {"status": "reset"}


@app.get("/api/behaviors", dependencies=[Depends(require_teacher)])
def recent_behaviors(
    db: Annotated[Session, Depends(get_db)], limit: int = 30
) -> list[dict[str, object]]:
    """Return recent behavior audit logs."""

    safe_limit = max(1, min(limit, 100))
    return [
        {
            "id": log.id,
            "behavior_type": log.behavior_type,
            "label": BEHAVIOR_LABELS.get(log.behavior_type, log.behavior_type),
            "fullname": log.student.fullname if log.student else "Không rõ",
            "timestamp": log.timestamp.isoformat(),
            "snapshot_url": f"/api/snapshots/{log.snapshot_path}",
        }
        for log in BehaviorLogService.list_recent(db, safe_limit)
    ]


@app.delete("/api/behaviors", dependencies=[Depends(require_teacher)])
def clear_behaviors(db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    """Delete the complete behavior audit trail and evidence snapshots."""

    return {"deleted": BehaviorLogService.clear_all(db, storage)}


@app.get("/api/snapshots/{name}", dependencies=[Depends(require_teacher)])
def get_snapshot(name: str) -> Response:
    """Return one protected behavior evidence image."""

    try:
        return Response(storage.read_snapshot(name), media_type="image/jpeg")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh chụp bằng chứng") from exc


@app.websocket("/ws")
async def video_stream(websocket: WebSocket) -> None:
    """Receive webcam JPEG frames and return annotated frame metadata."""

    try:
        _verify_websocket(websocket)
    except AuthenticationError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    processor = StreamProcessor(storage)
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(code=message.get("code", 1000))
            behavior_config = _websocket_behavior_config(message)
            if behavior_config is not None:
                processor.set_enabled_behaviors(behavior_config)
                await websocket.send_json(
                    {
                        "type": "behavior_config",
                        "enabled_behaviors": sorted(processor.enabled_behaviors),
                    }
                )
                continue
            raw_jpeg = _websocket_frame_bytes(message)
            with SessionLocal() as db:
                result = await asyncio.to_thread(processor.process, raw_jpeg, db)
            await websocket.send_json(result.to_dict())
    except WebSocketDisconnect:
        return
    except (RuntimeError, ValueError) as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)


def _verify_websocket(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise AuthenticationError("Nguồn kết nối WebSocket không được cho phép")
    forwarded_proto = websocket.headers.get("x-forwarded-proto")
    if settings.secure_transport_only and websocket.url.scheme != "wss":
        if forwarded_proto not in {"https", "wss"}:
            raise AuthenticationError("Yêu cầu kết nối bảo mật WSS")
    verify_teacher_token(websocket.cookies.get(settings.cookie_name))


def _websocket_frame_bytes(message: dict[str, object]) -> bytes:
    raw_bytes = message.get("bytes")
    if isinstance(raw_bytes, bytes):
        return raw_bytes
    text = message.get("text")
    if isinstance(text, str):
        encoded = text.split(",", maxsplit=1)[-1]
        try:
            return base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValueError("Khung hình webcam base64 không hợp lệ") from exc
    raise ValueError("Khung hình WebSocket phải chứa định dạng JPEG")


def _websocket_behavior_config(message: dict[str, object]) -> list[str] | None:
    """Load an optional behavior-toggle command from a WebSocket text message."""

    text = message.get("text")
    if not isinstance(text, str) or not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Lệnh JSON WebSocket không hợp lệ") from exc
    if not isinstance(payload, dict) or payload.get("type") != "behavior_config":
        raise ValueError("Lệnh WebSocket không được hỗ trợ")
    enabled_behaviors = payload.get("enabled_behaviors")
    if not isinstance(enabled_behaviors, list) or not all(
        isinstance(item, str) for item in enabled_behaviors
    ):
        raise ValueError("enabled_behaviors phải là một danh sách chuỗi")
    return enabled_behaviors


def _student_payload(student: Student) -> dict[str, object]:
    return {
        "id": student.id,
        "student_code": student.student_code,
        "fullname": student.fullname,
        "avatar_url": (
            f"/api/avatars/{student.avatar_path}" if student.avatar_path else None
        ),
    }


def _session_payload(db: Session, session_id: int) -> dict[str, object]:
    attendance = ClassroomService.attendance(db, session_id)
    return {
        "id": session_id,
        "status": "ACTIVE",
        "students": [
            {
                **_student_payload(state.student),
                "is_present": state.is_present,
                "is_called": state.is_called,
                "called_at": state.called_at.isoformat() if state.called_at else None,
            }
            for state in attendance
        ],
    }
