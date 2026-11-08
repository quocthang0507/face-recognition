"""FastAPI application for smart classroom monitoring."""

from __future__ import annotations

import asyncio
import base64
import binascii
import csv
import io
import json
import logging
import threading
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    AuthenticationError,
    LoginThrottle,
    issue_user_token,
    verify_user_token,
)
from .config import BASE_DIR, settings
from .database import SessionLocal, create_tables, get_db
from .face_engine import (
    FaceEngineUnavailable,
    FaceRecognitionEngine,
    find_similar_student,
)
from .models import (
    BehaviorLog,
    ClassroomSession,
    SchoolClass,
    SessionStudent,
    Student,
    User,
    as_utc,
    iso_utc,
)
from .services import (
    BehaviorLogService,
    ClassService,
    ClassroomService,
    DomainError,
    NotFoundError,
    ROLE_ADMIN,
    ROLE_TEACHER,
    StudentService,
    UserService,
    has_face_embedding,
    is_late,
)
from .reembed import reembed_outdated
from .storage import PrivateStorage
from .stream_processor import BEHAVIOR_LABELS, StreamProcessor, decode_jpeg

logger = logging.getLogger("smart_classroom")
storage = PrivateStorage()
login_throttle = LoginThrottle()
_shared_engine: FaceRecognitionEngine | None = None
_shared_engine_lock = threading.Lock()
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class LoginRequest(BaseModel):
    """Account login payload."""

    username: str
    password: str


class NewUserRequest(BaseModel):
    """A new dashboard account."""

    username: str
    password: str
    fullname: str
    role: str = ROLE_TEACHER


class UpdateUserRequest(BaseModel):
    """Fields an administrator can change on an account."""

    fullname: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class StartSessionRequest(BaseModel):
    """Optional lesson metadata entered by the teacher."""

    class_id: int
    title: str | None = Field(default=None, max_length=120)


class NewClassRequest(BaseModel):
    """A new class."""

    name: str
    school_year: str | None = None


class UpdateClassRequest(BaseModel):
    """Fields an administrator can change on a class."""

    name: str | None = None
    school_year: str | None = None
    is_archived: bool | None = None


class AddStudentRequest(BaseModel):
    """An existing student to add to another class."""

    student_code: str


class AttendanceUpdate(BaseModel):
    """Manual attendance correction by the teacher."""

    present: bool
    note: str | None = Field(default=None, max_length=200)


def _cleanup_expired_logs() -> None:
    with SessionLocal() as db:
        BehaviorLogService.cleanup_old(db, storage, settings.retention_days)


def shared_face_engine() -> FaceRecognitionEngine:
    """One face engine for registration and health checks (not per request)."""

    global _shared_engine
    with _shared_engine_lock:
        if _shared_engine is None:
            _shared_engine = FaceRecognitionEngine()
        return _shared_engine


def _registration_embedding(frame) -> list[float]:
    # MediaPipe graphs are not thread-safe; serialise access to the shared one.
    engine = shared_face_engine()
    with _shared_engine_lock:
        return engine.registration_embedding(frame)


def _preload_models() -> None:
    try:
        engine = shared_face_engine()
        if not engine.detection_available:
            return
        engine._embedding_provider()
        with SessionLocal() as db:
            updated, failed = reembed_outdated(
                db,
                storage,
                lambda content: _registration_embedding(decode_jpeg(content)),
            )
        if updated or failed:
            logger.info(
                "Đã tính lại khuôn mặt cho %s học sinh (lỗi %s)", updated, failed
            )
    except Exception as exc:  # noqa: BLE001 - preload must never stop startup
        logger.warning("Lỗi tải trước mô hình AI: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize tables and retention cleanup at application startup."""

    create_tables()
    with SessionLocal() as db:
        UserService.ensure_admin(db, settings.teacher_password)
        ClassService.ensure_default(db)
    if settings.uses_default_credentials:
        logger.warning(
            "Đang dùng mật khẩu/khóa ký mặc định. Hãy đặt FACE_APP_TEACHER_PASSWORD "
            "và FACE_APP_TOKEN_SECRET trước khi triển khai cho người dùng thật."
        )
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


def _active_user(db: Session, user_id: int) -> User | None:
    user = db.get(User, user_id)
    return user if user is not None and user.is_active else None


def require_teacher(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=settings.cookie_name)] = None,
) -> User:
    """Return the signed-in account or reject the request."""

    _require_secure_request(request)
    try:
        user = _active_user(db, verify_user_token(token))
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Tài khoản không còn hiệu lực")
    return user


CurrentUser = Annotated[User, Depends(require_teacher)]


def require_admin(user: CurrentUser) -> User:
    """Allow administrators only."""

    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Chỉ Quản trị mới có quyền này")
    return user


def _can_access_class(db: Session, user: User, class_id: int) -> bool:
    return user.role == ROLE_ADMIN or ClassService.is_assigned(db, class_id, user.id)


def _require_class_access(db: Session, user: User, class_id: int) -> None:
    try:
        ClassService.get(db, class_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    if not _can_access_class(db, user, class_id):
        raise HTTPException(status_code=403, detail="Bạn không phụ trách lớp này")


def _scope_class(db: Session, user: User, class_id: int | None) -> int | None:
    """Return the class a request is limited to; only admins may omit it."""

    if class_id is not None:
        _require_class_access(db, user, class_id)
        return class_id
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=400, detail="Vui lòng chọn lớp")
    return None


def _require_session_access(
    db: Session, user: User, session_id: int
) -> ClassroomSession:
    try:
        classroom_session = ClassroomService.get_session(db, session_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    allowed = user.role == ROLE_ADMIN or (
        classroom_session.class_id is not None
        and ClassService.is_assigned(db, classroom_session.class_id, user.id)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="Bạn không phụ trách lớp này")
    return classroom_session


def _student_accessible(db: Session, user: User, student_id: int) -> bool:
    return user.role == ROLE_ADMIN or ClassService.teacher_has_student(
        db, user.id, student_id
    )


def _require_student_access(db: Session, user: User, student_id: int) -> None:
    try:
        StudentService.get(db, student_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    if not _student_accessible(db, user, student_id):
        raise HTTPException(status_code=403, detail="Bạn không phụ trách học sinh này")


def _require_secure_request(request: Request) -> None:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if settings.secure_transport_only and request.url.scheme != "https":
        if forwarded_proto != "https":
            raise HTTPException(status_code=400, detail="Yêu cầu kết nối bảo mật HTTPS")


def _domain_error(exc: DomainError) -> HTTPException:
    status = 404 if isinstance(exc, NotFoundError) else 409
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """Serve the teacher dashboard."""

    return (BASE_DIR / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Serve the favicon image."""

    return FileResponse(BASE_DIR / "static" / "favicon.png")


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Authenticate an account and set an HttpOnly cookie."""

    client = request.client.host if request.client else "unknown"
    retry_after = login_throttle.retry_after(client)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail=f"Nhập sai quá nhiều lần. Thử lại sau {retry_after} giây",
            headers={"Retry-After": str(retry_after)},
        )
    user = UserService.authenticate(db, payload.username, payload.password)
    if user is None:
        login_throttle.record_failure(client)
        raise HTTPException(
            status_code=401, detail="Tên đăng nhập hoặc mật khẩu không chính xác"
        )
    login_throttle.record_success(client)
    response.set_cookie(
        key=settings.cookie_name,
        value=issue_user_token(user.id),
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


@app.get("/api/auth/status")
def auth_status(user: CurrentUser) -> dict[str, object]:
    """Confirm that the current cookie is valid and say who it belongs to."""

    return {"status": "authenticated", "user": _user_payload(user)}


@app.get("/api/users", dependencies=[Depends(require_admin)])
def list_users(db: Annotated[Session, Depends(get_db)]) -> list[dict[str, object]]:
    """Return every dashboard account."""

    return [_user_payload(user) for user in UserService.list_all(db)]


@app.post("/api/users", dependencies=[Depends(require_admin)])
def create_user(
    payload: NewUserRequest, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    """Create a dashboard account."""

    try:
        user = UserService.create(
            db, payload.username, payload.password, payload.fullname, payload.role
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _user_payload(user)


@app.patch("/api/users/{user_id}", dependencies=[Depends(require_admin)])
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Change, disable or reset the password of an account."""

    try:
        user = UserService.update(
            db, user_id, **payload.model_dump(exclude_unset=True)
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _user_payload(user)


@app.get("/api/health")
def health() -> dict[str, object]:
    """Expose runtime readiness without leaking student data."""

    return {
        "status": "ok",
        "face_detection": shared_face_engine().detection_available,
        "secure_transport_only": settings.secure_transport_only,
    }


@app.get("/api/classes")
def list_classes(
    user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> list[dict[str, object]]:
    """Return the classes the signed-in account can open."""

    classes = (
        ClassService.list_all(db)
        if user.role == ROLE_ADMIN
        else ClassService.list_for_teacher(db, user.id)
    )
    return [_class_payload(school_class) for school_class in classes]


@app.post("/api/classes", dependencies=[Depends(require_admin)])
def create_class(
    payload: NewClassRequest, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    """Create a class."""

    try:
        school_class = ClassService.create(db, payload.name, payload.school_year)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _class_payload(school_class)


@app.patch("/api/classes/{class_id}", dependencies=[Depends(require_admin)])
def update_class(
    class_id: int,
    payload: UpdateClassRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Rename or archive a class."""

    try:
        school_class = ClassService.update(
            db, class_id, **payload.model_dump(exclude_unset=True)
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _class_payload(school_class)


@app.put(
    "/api/classes/{class_id}/teachers/{user_id}",
    dependencies=[Depends(require_admin)],
)
def assign_teacher(
    class_id: int, user_id: int, db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    """Give a teacher access to a class."""

    try:
        ClassService.assign_teacher(db, class_id, user_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return {"status": "assigned"}


@app.delete(
    "/api/classes/{class_id}/teachers/{user_id}",
    dependencies=[Depends(require_admin)],
)
def unassign_teacher(
    class_id: int, user_id: int, db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    """Remove a teacher's access to a class."""

    try:
        ClassService.unassign_teacher(db, class_id, user_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return {"status": "unassigned"}


@app.post("/api/classes/{class_id}/students", dependencies=[Depends(require_admin)])
def add_existing_student(
    class_id: int,
    payload: AddStudentRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Add an already registered student to another class."""

    try:
        student = StudentService.find_by_code(db, payload.student_code)
        ClassService.add_student(db, class_id, student.id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _student_payload(student)


@app.get("/api/students")
def list_students(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    class_id: int | None = None,
) -> list[dict[str, object]]:
    """Return the students of one class; administrators may list everyone."""

    scope = _scope_class(db, user, class_id)
    return [_student_payload(student) for student in StudentService.list_all(db, scope)]


async def _read_face_image(
    image: UploadFile,
    db: Session,
    user: User,
    exclude_student_id: int | None = None,
) -> tuple[list[float], bytes]:
    """Validate an uploaded image, extract one embedding and reject duplicates."""

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415, detail="Yêu cầu định dạng ảnh JPEG, PNG hoặc WebP"
        )
    content = await image.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail="Dung lượng ảnh phải nằm trong khoảng từ 1B đến 5MB"
        )
    try:
        frame = await asyncio.to_thread(decode_jpeg, content)
        embedding = await asyncio.to_thread(_registration_embedding, frame)
    except FaceEngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    duplicate, confidence = find_similar_student(
        embedding,
        StudentService.list_all(db),
        settings.duplicate_face_confidence,
        exclude_student_id=exclude_student_id,
    )
    if duplicate is not None:
        detail = "Khuôn mặt này trùng với một học sinh đã đăng ký ở lớp khác"
        if _student_accessible(db, user, duplicate.id):
            detail = (
                "Khuôn mặt này trùng với học sinh đã đăng ký "
                f"{duplicate.fullname} ({duplicate.student_code}, {confidence:.0f}%)"
            )
        raise HTTPException(status_code=409, detail=detail)
    return embedding, content


@app.post("/register", include_in_schema=False)
@app.post("/api/students/register")
async def register_student(
    student_code: Annotated[str, Form()],
    fullname: Annotated[str, Form()],
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    class_id: Annotated[int | None, Form()] = None,
    image: UploadFile | None = None,
) -> dict[str, object]:
    """Register a student into a class from a webcam JPEG or uploaded image."""

    scope = _scope_class(db, user, class_id)
    if db.scalar(select(Student).where(Student.student_code == student_code.strip())):
        raise HTTPException(status_code=409, detail="Mã học sinh đã tồn tại")

    embedding = None
    avatar_path = None
    if image is not None and image.filename:
        embedding, content = await _read_face_image(image, db, user)
        avatar_path = storage.save_avatar(content)

    try:
        student = StudentService.register(
            db,
            student_code,
            fullname,
            embedding,
            avatar_path,
            class_ids=[scope] if scope is not None else [],
        )
    except DomainError as exc:
        if avatar_path:
            storage.delete_avatar(avatar_path)
        raise _domain_error(exc) from exc
    return _student_payload(student)


@app.post("/api/students/{student_id}/face")
async def update_student_face(
    student_id: int,
    image: UploadFile,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Replace the face sample of a student (re-enrollment)."""

    _require_student_access(db, user, student_id)
    embedding, content = await _read_face_image(
        image, db, user, exclude_student_id=student_id
    )
    avatar_path = storage.save_avatar(content)
    student, previous = StudentService.update_face(
        db, student_id, embedding, avatar_path
    )
    if previous:
        storage.delete_avatar(previous)
    return _student_payload(student)


@app.delete("/api/students/{student_id}")
def delete_student(
    student_id: int,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    class_id: int | None = None,
) -> dict[str, str]:
    """Remove a student from a class, or everywhere when no class is given."""

    scope = _scope_class(db, user, class_id)
    try:
        if scope is None:
            StudentService.delete(db, student_id, storage)
        else:
            ClassService.remove_student(db, scope, student_id, storage)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return {"status": "deleted"}


@app.get("/api/avatars/{name}")
def get_avatar(
    name: str, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> Response:
    """Decrypt and return one protected avatar image."""

    student = db.scalar(select(Student).where(Student.avatar_path == name))
    if student is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh đại diện")
    _require_student_access(db, user, student.id)
    try:
        return Response(storage.read_avatar(name), media_type="image/jpeg")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh đại diện") from exc


@app.post("/api/sessions")
def start_session(
    payload: StartSessionRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Start a lesson for one class."""

    _require_class_access(db, user, payload.class_id)
    try:
        classroom_session = ClassroomService.start_session(
            db, payload.title, class_id=payload.class_id, teacher_id=user.id
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _session_payload(db, classroom_session)


@app.get("/api/sessions/active")
def active_session(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    class_id: int | None = None,
) -> dict[str, object] | None:
    """Return the active lesson of a class and its attendance."""

    scope = _scope_class(db, user, class_id)
    classroom_session = ClassroomService.get_active_session(db, scope)
    return _session_payload(db, classroom_session) if classroom_session else None


@app.get("/api/sessions")
def session_history(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 20,
    class_id: int | None = None,
) -> list[dict[str, object]]:
    """Return recent lessons of a class with attendance summaries."""

    scope = _scope_class(db, user, class_id)
    return [
        {
            **_session_header(classroom_session),
            "summary": ClassroomService.summary(db, classroom_session).to_dict(),
        }
        for classroom_session in ClassroomService.list_sessions(
            db, max(1, min(limit, 100)), scope
        )
    ]


@app.get("/api/sessions/{session_id}")
def session_detail(
    session_id: int, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    """Return one lesson (active or finished) with full attendance."""

    return _session_payload(db, _require_session_access(db, user, session_id))


@app.post("/api/sessions/{session_id}/finish")
def finish_session(
    session_id: int, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    """Finish the requested classroom session and return its summary."""

    _require_session_access(db, user, session_id)
    try:
        classroom_session = ClassroomService.finish_session(db, session_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return {
        **_session_header(classroom_session),
        "summary": ClassroomService.summary(db, classroom_session).to_dict(),
    }


@app.put("/api/sessions/{session_id}/attendance/{student_id}")
def update_attendance(
    session_id: int,
    student_id: int,
    payload: AttendanceUpdate,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    """Manually confirm or correct one student's attendance."""

    classroom_session = _require_session_access(db, user, session_id)
    if classroom_session.class_id is not None and not ClassService.has_student(
        db, classroom_session.class_id, student_id
    ):
        raise HTTPException(status_code=404, detail="Học sinh không thuộc lớp này")
    try:
        state = ClassroomService.set_attendance(
            db, session_id, student_id, payload.present, payload.note
        )
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _attendance_payload(state, classroom_session)


@app.get("/api/sessions/{session_id}/export.csv")
def export_session_csv(
    session_id: int, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> Response:
    """Download the attendance sheet of one lesson as an Excel-friendly CSV."""

    classroom_session = _require_session_access(db, user, session_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "STT",
            "Mã học sinh",
            "Họ và tên",
            "Trạng thái",
            "Giờ vào lớp",
            "Hình thức",
            "Gọi trả bài lúc",
            "Ghi chú",
        ]
    )
    for index, state in enumerate(
        ClassroomService.attendance(db, session_id), start=1
    ):
        writer.writerow(
            [
                index,
                state.student.student_code,
                state.student.fullname,
                _attendance_label(state, classroom_session),
                _local_time(state.checked_in_at),
                {"AUTO": "Camera", "MANUAL": "Giáo viên"}.get(
                    state.attendance_source or "", ""
                ),
                _local_time(state.called_at) if state.called_at else "",
                state.note or "",
            ]
        )
    filename = f"diem-danh-phien-{session_id}.csv"
    # UTF-8 BOM so Excel on Windows shows Vietnamese characters correctly.
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/sessions/{session_id}/pick")
def pick_student(
    session_id: int, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict[str, object]:
    """Pick one uncalled present student."""

    _require_session_access(db, user, session_id)
    try:
        selected = ClassroomService.pick_random(db, session_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return _student_payload(selected.student)


@app.post("/api/sessions/{session_id}/reset-called")
def reset_called(
    session_id: int, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    """Reset the random-call round."""

    _require_session_access(db, user, session_id)
    try:
        ClassroomService.reset_called(db, session_id)
    except DomainError as exc:
        raise _domain_error(exc) from exc
    return {"status": "reset"}


@app.get("/api/behaviors")
def recent_behaviors(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 30,
    session_id: int | None = None,
    class_id: int | None = None,
) -> list[dict[str, object]]:
    """Return recent behavior audit logs for a lesson or class."""

    if session_id is not None:
        _require_session_access(db, user, session_id)
        scope = None
    else:
        scope = _scope_class(db, user, class_id)
    safe_limit = max(1, min(limit, 100))
    return [
        {
            "id": log.id,
            "behavior_type": log.behavior_type,
            "label": BEHAVIOR_LABELS.get(log.behavior_type, log.behavior_type),
            "session_id": log.session_id,
            "student_id": log.student_id,
            "fullname": log.student.fullname if log.student else "Không rõ",
            "timestamp": iso_utc(log.timestamp),
            "snapshot_url": f"/api/snapshots/{log.snapshot_path}",
        }
        for log in BehaviorLogService.list_recent(db, safe_limit, session_id, scope)
    ]


@app.delete("/api/behaviors")
def clear_behaviors(
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    class_id: int | None = None,
) -> dict[str, int]:
    """Delete the behavior audit trail and evidence snapshots of a class."""

    scope = _scope_class(db, user, class_id)
    return {"deleted": BehaviorLogService.clear_all(db, storage, scope)}


@app.get("/api/snapshots/{name}")
def get_snapshot(
    name: str, user: CurrentUser, db: Annotated[Session, Depends(get_db)]
) -> Response:
    """Return one protected behavior evidence image."""

    log = db.scalar(select(BehaviorLog).where(BehaviorLog.snapshot_path == name).limit(1))
    if log is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh chụp bằng chứng")
    _require_session_access(db, user, log.session_id)
    try:
        return Response(storage.read_snapshot(name), media_type="image/jpeg")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh chụp bằng chứng") from exc


@app.websocket("/ws")
async def video_stream(websocket: WebSocket) -> None:
    """Receive webcam JPEG frames and return annotated frame metadata."""

    try:
        class_id = _verify_websocket(websocket)
    except AuthenticationError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    # ``?overlay=server`` keeps the old annotated-JPEG mode for debugging.
    server_overlay = websocket.query_params.get("overlay") == "server"
    processor = StreamProcessor(storage, class_id=class_id)
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
                result = await asyncio.to_thread(
                    processor.process, raw_jpeg, db, server_overlay
                )
            await websocket.send_json(result.to_dict())
    except WebSocketDisconnect:
        return
    except (RuntimeError, ValueError) as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)


def _verify_websocket(websocket: WebSocket) -> int:
    """Check the connection and return the class this camera stream serves."""

    origin = websocket.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise AuthenticationError("Nguồn kết nối WebSocket không được cho phép")
    forwarded_proto = websocket.headers.get("x-forwarded-proto")
    if settings.secure_transport_only and websocket.url.scheme != "wss":
        if forwarded_proto not in {"https", "wss"}:
            raise AuthenticationError("Yêu cầu kết nối bảo mật WSS")
    user_id = verify_user_token(websocket.cookies.get(settings.cookie_name))
    try:
        class_id = int(websocket.query_params.get("class_id", ""))
    except ValueError as exc:
        raise AuthenticationError("Thiếu lớp cho luồng camera") from exc
    with SessionLocal() as db:
        user = _active_user(db, user_id)
        if user is None:
            raise AuthenticationError("Tài khoản không còn hiệu lực")
        if db.get(SchoolClass, class_id) is None or not _can_access_class(
            db, user, class_id
        ):
            raise AuthenticationError("Bạn không phụ trách lớp này")
    return class_id


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


def _class_payload(school_class: SchoolClass) -> dict[str, object]:
    return {
        "id": school_class.id,
        "name": school_class.name,
        "school_year": school_class.school_year,
        "is_archived": school_class.is_archived,
        "student_count": len(school_class.students),
        "teacher_ids": [teacher.id for teacher in school_class.teachers],
    }


def _user_payload(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "fullname": user.fullname,
        "role": user.role,
        "is_active": user.is_active,
    }


def _student_payload(student: Student) -> dict[str, object]:
    return {
        "id": student.id,
        "student_code": student.student_code,
        "fullname": student.fullname,
        "has_face": has_face_embedding(student),
        "avatar_url": (
            f"/api/avatars/{student.avatar_path}" if student.avatar_path else None
        ),
    }


def _session_header(classroom_session: ClassroomSession) -> dict[str, object]:
    return {
        "id": classroom_session.id,
        "title": classroom_session.title,
        "class_id": classroom_session.class_id,
        "status": classroom_session.status,
        "created_at": iso_utc(classroom_session.created_at),
        "finished_at": iso_utc(classroom_session.finished_at),
        "late_after_minutes": settings.late_after_minutes,
    }


def _attendance_payload(
    state: SessionStudent, classroom_session: ClassroomSession
) -> dict[str, object]:
    return {
        **_student_payload(state.student),
        "is_present": state.is_present,
        "is_late": is_late(state, classroom_session),
        "checked_in_at": iso_utc(state.checked_in_at),
        "attendance_source": state.attendance_source,
        "note": state.note,
        "is_called": state.is_called,
        "called_at": iso_utc(state.called_at),
    }


def _session_payload(
    db: Session, classroom_session: ClassroomSession
) -> dict[str, object]:
    attendance = ClassroomService.attendance(db, classroom_session.id)
    return {
        **_session_header(classroom_session),
        "summary": ClassroomService.summary(db, classroom_session).to_dict(),
        "students": [
            _attendance_payload(state, classroom_session) for state in attendance
        ],
    }


def _attendance_label(
    state: SessionStudent, classroom_session: ClassroomSession
) -> str:
    if not state.is_present:
        return "Vắng"
    return "Đi muộn" if is_late(state, classroom_session) else "Có mặt"


def _local_time(value) -> str:
    """Format a UTC timestamp in the server's local time zone for reports."""

    normalized = as_utc(value)
    return normalized.astimezone().strftime("%H:%M:%S %d/%m/%Y") if normalized else ""
