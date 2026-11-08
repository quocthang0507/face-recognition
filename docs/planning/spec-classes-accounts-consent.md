# Spec: Lớp học, Tài khoản và Đồng ý dữ liệu sinh trắc

Mục 1 và 2 trong [module-roadmap.md](module-roadmap.md). Trạng thái: **đã duyệt, đang triển khai**.

## Mục tiêu

- Mỗi giáo viên đăng nhập bằng tài khoản riêng và chỉ thao tác trên lớp được phân công.
- Học sinh, phiên học và nhận diện khuôn mặt được giới hạn theo lớp.
- Chỉ học sinh đã có đồng ý mới được lưu và nhận diện khuôn mặt, và đồng ý có thể rút lại.
- Có dấu vết ai đã xem ảnh bằng chứng và ai đã đổi trạng thái đồng ý.

## Hiện trạng

| Vấn đề | Vị trí |
|---|---|
| Một mật khẩu chung, token chỉ ghi `role: teacher`, không biết là ai | `src/auth.py` |
| Mọi học sinh chung một danh sách | `Student` trong `src/models.py` |
| Nhận diện so khớp với toàn bộ học sinh | `Gallery.build(StudentService.list_all(db))` trong `src/stream_processor.py` |
| Không có khái niệm đồng ý; ảnh và vector được lưu ngay khi đăng ký | `POST /api/students/register` |
| Xem ảnh bằng chứng không để lại dấu vết | `GET /api/snapshots/{name}` |

## Giả định

1. Một server phục vụ một trường, không cần tách dữ liệu nhiều trường.
2. Có 2 vai trò: **Quản trị** và **Giáo viên**. Học sinh và phụ huynh không đăng nhập.
3. Đồng ý do giáo viên hoặc quản trị ghi nhận sau khi nhận văn bản từ phụ huynh;
   hệ thống không thu đồng ý trực tuyến.
4. Mã hóa mật khẩu bằng `hashlib.scrypt` của Python, không thêm thư viện.
5. Tài khoản Quản trị đầu tiên lấy từ `FACE_APP_TEACHER_PASSWORD`, tên đăng nhập `admin`.
6. Sau khi nâng cấp, mọi người phải đăng nhập lại vì token cũ không có định danh.

## Mô hình dữ liệu

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `users` (mới) | `username` duy nhất, `password_hash`, `fullname`, `role`, `is_active` | Vô hiệu hóa thay vì xóa, để giữ lịch sử |
| `classes` (mới) | `name` duy nhất, `school_year`, `is_archived` | |
| `class_teachers` (mới) | `class_id`, `user_id` | Phân công giáo viên |
| `class_students` (mới) | `class_id`, `student_id` | Một học sinh có thể ở nhiều lớp theo môn; dữ liệu cũ vào "Lớp mặc định" |
| `students` (đổi) | thêm `consent_status` | Đồng ý gắn với học sinh, không theo lớp |
| `sessions` (đổi) | thêm `class_id`, `teacher_id` | Mỗi lớp có tối đa một phiên đang diễn ra |
| `consent_events` (mới) | `student_id`, `status`, `recorded_by`, `recorded_at`, `note` | Chỉ thêm, không sửa |
| `access_logs` (mới) | `user_id`, `action`, `target`, `created_at` | Dấu vết xem ảnh bằng chứng và avatar |

`consent_status` nhận `PENDING`, `GRANTED`, `REFUSED`, `WITHDRAWN`.

## Quyền hạn

| Hành động | Quản trị | Giáo viên |
|---|---|---|
| Quản lý tài khoản, lớp, phân công | Có | Không |
| Xem, điểm danh, mở phiên, gọi trả bài | Mọi lớp | Lớp được phân công |
| Đăng ký, sửa học sinh; ghi nhận đồng ý | Mọi lớp | Lớp được phân công |
| Gỡ học sinh khỏi lớp | Mọi lớp | Lớp được phân công; chỉ xóa hẳn khi đó là lớp cuối cùng |
| Thêm học sinh có sẵn vào lớp khác | Có | Không |
| Xem ảnh bằng chứng | Mọi lớp, có ghi vết | Lớp được phân công, có ghi vết |
| Xem nhật ký truy cập | Có | Không |

Quyền được kiểm tra ở server. Truy cập lớp không được phân công trả về 403.

## Quy tắc đồng ý

| Trạng thái | Lưu khuôn mặt | Camera nhận diện | Điểm danh thủ công |
|---|---|---|---|
| `GRANTED` | Có | Có | Có |
| `PENDING`, `REFUSED` | Không | Không | Có |
| `WITHDRAWN` | Không, xóa ngay | Không | Có |

- Rút đồng ý xóa vector, ảnh đại diện và ảnh bằng chứng của học sinh đó, giữ lịch sử
  điểm danh. Nếu một ảnh bằng chứng có cả học sinh khác, ảnh và các cảnh báo gắn với
  ảnh đó cũng bị xóa.
- Học sinh đã có khuôn mặt trước khi nâng cấp được chuyển thành `GRANTED`, ghi một
  `consent_events` nêu rõ nguồn gốc (quyết định của chủ dự án). Học sinh chưa có khuôn
  mặt là `PENDING`.
- Server từ chối ảnh khuôn mặt nếu học sinh chưa ở trạng thái `GRANTED`.
- File `classroom.db.bak-*` có chứa vector khuôn mặt, nên được xóa sau `retention_days`.

## Giao diện

- Trang đăng nhập có tên đăng nhập và mật khẩu.
- Bộ chọn lớp trên thanh đầu trang, ẩn ở chế độ Chiếu TV khi đang có phiên.
- Trang Quản trị cho tài khoản, lớp và phân công, chỉ hiện với Quản trị.
- Cột Đồng ý trong Danh sách lớp, chỉ hiện ở chế độ Máy tính GV.

## Lệnh

```bash
pytest src/tests
pytest src/tests/e2e -m e2e
alembic revision --autogenerate -m "mo ta"
alembic check
```

## Cấu trúc

```text
src/
├── auth.py               # Token mang user_id, kiểm tra quyền
├── models.py             # Bảng mới
├── services.py           # UserService, ClassService, ConsentService
├── migrations/versions/  # 0002 tài khoản, 0003 lớp học, 0004 đồng ý
└── tests/                # test_accounts, test_classes, test_consent, e2e
```

## Kiểu code

```python
def require_class_access(class_id: int, user: CurrentUser, db: DbSession) -> None:
    if user.role != "ADMIN" and not ClassService.is_assigned(db, class_id, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bạn không phụ trách lớp này")
```

## Chiến lược kiểm thử

- Unit: phân quyền cho từng hành động, chuyển trạng thái đồng ý, xóa dữ liệu khi rút.
- Migration: CSDL có dữ liệu ở bản `0001` nâng lên mới nhất vẫn giữ đủ dữ liệu.
- E2E: giáo viên A không thấy lớp của giáo viên B; học sinh chưa đồng ý không được tải
  ảnh khuôn mặt; rút đồng ý làm mất ảnh.

## Ranh giới

- **Luôn làm:** kiểm tra quyền ở server; viết test trước; chỉ thử trên dữ liệu tạm hoặc
  bản sao.
- **Hỏi trước:** thêm thư viện; gửi dữ liệu ra ngoài server; thêm vai trò mới.
- **Không làm:** lưu mật khẩu dạng rõ; lưu khuôn mặt khi chưa có đồng ý; để cảnh báo hành
  vi tác động đến điểm số.

## Tiêu chí hoàn thành

- [ ] Giáo viên không đọc hay sửa được dữ liệu lớp không được phân công qua API và WebSocket.
- [ ] Camera chỉ nhận diện học sinh của lớp đang mở phiên và ở trạng thái `GRANTED`.
- [ ] Rút đồng ý xóa vector, ảnh đại diện, ảnh bằng chứng, và ghi một `consent_events`.
- [ ] Mỗi lần xem ảnh bằng chứng tạo một dòng `access_logs`.
- [ ] Nâng cấp bản sao CSDL thật giữ đủ học sinh, phiên và điểm danh.
- [ ] `pytest src/tests`, E2E và `alembic check` đều đạt.

## Kế hoạch và danh sách việc

Chia thành 3 đợt, mỗi đợt một nhánh và vẫn chạy được độc lập.

**Đợt A: Tài khoản**

- [ ] Bảng `users`, migration `0002`, mã hóa mật khẩu, tạo `admin` đầu tiên khi khởi động.
- [ ] Token mang `user_id`; đổi đăng nhập; cập nhật fixture E2E.
- [ ] Trang quản lý tài khoản.

**Đợt B: Lớp học**

- [ ] Migration `0003`: `classes`, `class_teachers`, `class_students`, `class_id` cho phiên; chuyển dữ liệu cũ.
- [ ] Kiểm tra quyền theo lớp ở API và WebSocket.
- [ ] Giới hạn `Gallery` theo lớp, gồm cả khóa bộ nhớ đệm.
- [ ] Bộ chọn lớp và trang phân công.

**Đợt C: Đồng ý và dấu vết**

- [ ] `consent_status`, `consent_events`, `access_logs`, migration `0004`.
- [ ] Chặn lưu khuôn mặt và loại khỏi `Gallery` theo trạng thái.
- [ ] Xóa dữ liệu khi rút đồng ý; dọn file `.bak` quá hạn.
- [ ] `access_logs` và màn hình xem nhật ký.

## Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| Đổi xác thực làm khóa người dùng | Tạo `admin` khi khởi động từ biến môi trường; thử trên bản sao |
| Lộ dữ liệu giữa các lớp do sót điểm kiểm tra | Test quyền cho từng endpoint, gồm WebSocket và ảnh |
| Nhận diện dừng đột ngột với học sinh cũ | Hiện rõ số học sinh chờ đồng ý trên Dashboard |

## Quyết định đã chốt

1. Một học sinh có thể thuộc nhiều lớp theo môn.
2. Học sinh đã có khuôn mặt trước khi nâng cấp được coi là đã đồng ý. Trách nhiệm có
   văn bản đồng ý thực tế thuộc về nhà trường.
