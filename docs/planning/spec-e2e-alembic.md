# Spec: Kiểm thử giao diện và migration CSDL

Mục 3 trong [module-roadmap.md](module-roadmap.md). Trạng thái: **đã triển khai**.

## Mục tiêu

Tạo lưới an toàn trước khi làm phân hệ Lớp học và Tài khoản, vốn sẽ đổi nhiều bảng.

- Người phát triển chạy được một lệnh để kiểm tra các luồng chính trên trình duyệt thật.
- Thay đổi lược đồ CSDL được quản lý theo phiên bản, thay cho danh sách cột viết tay.
- File `classroom.db` đang dùng được nâng cấp mà không mất dữ liệu.

## Giả định

1. Mỗi máy chạy một server với một file SQLite, chưa cần hỗ trợ CSDL khác.
2. Máy người dùng cuối không cần cài Playwright, chỉ máy phát triển mới cần.
3. Repo chưa có CI, nên đợt này không thêm.
4. Migration vẫn tự chạy khi server khởi động, để giáo viên không phải gõ lệnh.

## Công nghệ

- Playwright for Python, Chromium, thêm vào `requirements-e2e.txt`.
- Alembic, thêm vào `requirements.txt` vì server cần khi khởi động.

## Lệnh

```bash
# Test nhanh, không mở trình duyệt (giữ nguyên như hiện tại)
pytest src/tests

# Test giao diện
pip install -r requirements-e2e.txt
playwright install chromium
pytest src/tests/e2e -m e2e
E2E_HEADED=1 pytest src/tests/e2e -m e2e   # mở cửa sổ để theo dõi

# Tạo migration mới
alembic revision --autogenerate -m "mo ta thay doi"
alembic upgrade head
```

## Cấu trúc

```text
alembic.ini
pytest.ini                  # Khai báo marker e2e, mặc định bỏ qua nhóm này
requirements-e2e.txt
src/
├── migrate.py              # Nâng cấp CSDL khi khởi động, sao lưu trước khi nâng cấp
├── migrations/
│   ├── env.py              # Lấy địa chỉ CSDL từ settings
│   └── versions/0001_baseline.py
└── tests/
    ├── test_migrations.py
    └── e2e/
        ├── conftest.py     # Server thật, dữ liệu tạm, camera giả
        └── test_*.py       # Theo luồng nghiệp vụ
```

## Thiết kế migration khi khởi động

| Trạng thái CSDL | Xử lý |
|---|---|
| Chưa có bảng | `upgrade head` tạo toàn bộ |
| Có bảng, chưa có `alembic_version` | Chạy bù cột cũ, đánh dấu `0001`, rồi `upgrade head` |
| Đã có `alembic_version` | `upgrade head` |

Khi có migration cần chạy trên CSDL đã có dữ liệu, tạo bản sao
`classroom.db.bak-<revision>` bằng API backup của SQLite, vì CSDL dùng WAL nên chép
file thông thường có thể thiếu dữ liệu. Migration lỗi thì server dừng và báo rõ vị
trí bản sao, không chạy tiếp trên lược đồ dở dang.

## Kiểu code

Test viết theo hành vi người dùng, chọn phần tử bằng `id` đang có:

```python
@pytest.mark.e2e
def test_tv_mode_hides_absence_note(dashboard: Page) -> None:
    dashboard.click("#display-tv")

    assert "có phép" not in dashboard.inner_text("#student-list")
```

Mã Python tuân theo `black` và `flake8` như hiện tại.

## Chiến lược kiểm thử

| Mức | Nội dung |
|---|---|
| Unit (`test_migrations.py`) | CSDL mới; CSDL cũ thiếu cột giữ nguyên dữ liệu; CSDL đã có phiên bản; tạo bản sao; không có khác biệt giữa models và migration |
| E2E | Các luồng đã kiểm tra thủ công: đăng nhập, đăng ký, phiên học, điểm danh, gọi ngẫu nhiên, CSV, cài đặt, camera giả, 2 chế độ hiển thị, bố cục |

Kiểm tra với camera và người thật vẫn nằm ở
[manual-verification.md](../guides/manual-verification.md).

## Ranh giới

- **Luôn làm:** chạy `pytest src/tests` trước khi kết thúc mỗi việc; E2E và test
  migration chỉ dùng thư mục tạm.
- **Hỏi trước:** migration xóa hoặc đổi kiểu cột; thêm thư viện ngoài danh sách trên.
- **Không làm:** chạy thử trên `src/data` thật; sửa migration đã phát hành; đổi hành
  vi nghiệp vụ trong đợt này.

## Tiêu chí hoàn thành

- [x] `pytest src/tests` vẫn pass, không cần Playwright và không mở trình duyệt.
- [x] `pytest src/tests/e2e -m e2e` pass ở chế độ headless và không để lại server chạy.
- [x] CSDL được tạo trước phiên bản có `title`, `checked_in_at` được nâng cấp đủ cột
      và giữ nguyên dữ liệu.
- [x] `alembic check` báo không có khác biệt so với models.
- [x] Có bản sao trước khi nâng cấp CSDL có dữ liệu, và mở được bản sao đó.
- [x] `src/database.py` không còn `_ADDED_COLUMNS` và `create_all` khi khởi động.

## Kế hoạch và danh sách việc

Làm theo thứ tự, vì E2E cần ổn định trước khi đổi đường khởi động CSDL.

- [x] **1. Hạ tầng E2E**: `pytest.ini`, `requirements-e2e.txt`, `conftest.py`.
  - Kiểm tra: một test đăng nhập pass, không còn tiến trình server sau khi chạy.
- [x] **2. Chuyển kịch bản E2E vào repo**, tách theo luồng.
  - Kiểm tra: toàn bộ E2E pass ở chế độ headless.
- [x] **3. Khung Alembic và bản `0001`**.
  - Kiểm tra: `alembic check` không có khác biệt.
- [x] **4. `src/migrate.py` và sao lưu**, viết test trước theo bảng trạng thái.
  - Kiểm tra: `pytest src/tests/test_migrations.py`.
- [x] **5. Thay đường khởi động** trong `src/database.py`.
  - Kiểm tra: `pytest src/tests` và E2E đều pass.
- [x] **6. Cập nhật tài liệu** `README.md`, `docs/README.md`, đánh dấu lộ trình.

## Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| CSDL thật có lược đồ khác dự kiến | Bản sao trước khi nâng cấp; test với CSDL dựng theo lược đồ cũ |
| SQLite hạn chế `ALTER TABLE` | Bật `render_as_batch` trong `env.py` |
| E2E chậm hoặc chập chờn | Tách khỏi lệnh test mặc định; chờ theo trạng thái, không chờ theo thời gian cố định |

## Câu hỏi mở

Không còn câu hỏi chặn việc. Các lựa chọn cần xác nhận nằm trong phần Giả định.
