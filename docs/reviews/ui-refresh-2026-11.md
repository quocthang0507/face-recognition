# Nâng cấp giao diện Dashboard (11/2026)

Tài liệu dành cho người phát triển: những gì đã đổi trên giao diện, quy ước cần
giữ khi sửa tiếp, và phạm vi đã kiểm thử. Hướng dẫn cho giáo viên nằm ở
[display-modes.md](../guides/display-modes.md).

Phạm vi là tinh chỉnh giao diện hiện có. API, WebSocket và cơ sở dữ liệu không
đổi. Thay đổi nằm trong `src/templates/index.html`, `src/static/css/style.css` và
`src/static/js/app.js`.

## 1. Lỗi đã sửa

| # | Vấn đề | Ảnh hưởng | Cách sửa |
|---|--------|-----------|----------|
| 1 | `initials()` đưa thẳng vào `innerHTML` trong `renderSession()` | Tên có `<` làm hỏng HTML của dòng, tên học sinh bị dồn vào vòng tròn avatar | Bọc bằng `escapeHtml()` |
| 2 | `#picked-initials` bị ẩn sau một lượt gọi trúng học sinh có ảnh và không được hiện lại | Vòng avatar trống trong lúc xáo tên ở lượt sau | Đặt lại `display` khi bắt đầu `pickStudent()` |

## 2. Hai chế độ hiển thị

Chế độ được đặt ở `document.documentElement.dataset.display`, nhận giá trị `desk`
(mặc định) hoặc `tv`, và lưu trong `localStorage` với khóa
`smart-classroom-display`. Script trong `<head>` áp dụng giá trị này trước khi
trang được vẽ. `applyDisplay()` trong `app.js` xử lý việc chuyển chế độ.

| Biến CSS | `desk` | `tv` | Ý nghĩa |
|---|---:|---:|---|
| `font-size` của `:root` | 87.5% | 112.5% | Co giãn mọi kích thước dùng `rem` |
| `--control` | 42px | 54px | Chiều cao nút, ô nhập, select |
| `--control-sm` | 36px | 46px | Nút trong bảng, badge bấm được |
| `--pick` | 56px | 84px | Chiều cao nút `Gọi ngẫu nhiên` |
| `--side` | 340px | 460px | Độ rộng cột bên |

### Quy ước khi thêm giao diện mới

- Dùng `rem` cho cỡ chữ để phần tử tự co giãn theo chế độ, và dùng `--control`
  cho chiều cao điều khiển.
- Thêm class `desk-only` cho công cụ quản trị hoặc nội dung cả lớp không nên thấy.
  Với bảng, đặt class trên cả `<th>` và `<td>`.
- Mọi nội dung hiển thị tên học sinh gắn với cảnh báo phải đi qua `alertName()`
  hoặc kiểm tra `namesHidden()`. Hàm này luôn trả `true` ở chế độ `tv`.
- Nhãn tên trên khung nhận diện dùng `isTvDisplay()`, nên tùy chọn ẩn tên trong
  cảnh báo ở chế độ `desk` không ảnh hưởng đến nhãn này.
- Không dùng `desk-only` như một cơ chế phân quyền. Class này chỉ ẩn phần tử bằng
  CSS, còn API vẫn mở cho phiên đăng nhập của giáo viên ở cả hai chế độ.

## 3. Quy ước hình ảnh

- **Bề mặt:** dùng `.surface` với nền đặc. Đã bỏ hiệu ứng kính mờ và các đốm màu
  nền vì làm giảm độ tương phản khi chiếu.
- **Màu:** chỉ dùng token trong `:root` (`--text`, `--muted`, `--blue`, `--green`,
  `--amber`, `--red`, `--on-accent`). Nền nhạt tạo bằng `color-mix()` từ token để
  đúng ở cả giao diện sáng và tối. Giao diện sáng là mặc định; lựa chọn đã lưu của
  người dùng được giữ nguyên.
- **Icon:** bộ SVG `<symbol>` ở đầu `<body>`, gọi bằng
  `<svg class="icon"><use href="#i-..."/></svg>`. Thẻ `<svg>` chứa bộ icon phải
  dùng `display: none`, vì thuộc tính `hidden` không có tác dụng với SVG và sẽ tạo
  khoảng trống 150px đầu trang.
- **Nút có icon và chữ thay đổi:** đặt chữ trong `<span class="label">` rồi cập nhật
  span đó. Gán `textContent` cho cả nút sẽ làm mất icon (xem `#start-camera-button`).
- **Điểm nhấn duy nhất** là tên học sinh được gọi trong `#picker-modal`. Các phần
  còn lại ưu tiên sự rõ ràng, chuyển động chỉ dùng để báo đổi trạng thái.
- Các breakpoint vẫn ở 1180px và 680px. Tôn trọng `prefers-reduced-motion`.

## 4. Thay đổi hành vi nhỏ

- Tùy chọn mới `Ẩn tên học sinh trong cảnh báo`, tắt mặc định ở chế độ `desk`,
  lưu với khóa `smart-classroom-hide-alert-names`.
- Nhóm `Khi Chiếu TV` trong Cài đặt có 2 tùy chọn bật sẵn, chỉ tác dụng ở chế độ
  `tv`: khóa `smart-classroom-tv-hide-checkin` cho thông báo điểm danh và
  `smart-classroom-tv-hide-missing-face` cho dòng thiếu ảnh.
- Phím Esc đóng popup cài đặt, gọi tên và báo cáo. Popup đăng nhập không đóng bằng Esc.
- Footer không còn cố định ở đáy màn hình, để dành chỗ cho camera.
- Các chữ nhỏ phía trên tiêu đề đã được bỏ.
- `Cảnh báo mới nhất` và `Danh sách lớp` có trạng thái trống hướng dẫn thao tác.

## 5. Phạm vi đã kiểm thử

Đã chạy kịch bản Playwright với Chromium, camera giả và dữ liệu test riêng, qua các luồng: đăng nhập, đăng ký, phiên học, điểm danh thủ công, gọi ngẫu
nhiên, xuất CSV, cài đặt, camera và WebSocket, xóa học sinh, tổng kết, lịch sử,
đăng xuất, bố cục ở 1440, 768, 375px, cùng hai chế độ hiển thị. Kịch bản này nay
nằm ở `src/tests/e2e`, chạy bằng `pytest src/tests/e2e -m e2e`.

Lệnh mặc định `pytest src/tests` bỏ qua nhóm này. Các mục cần người và camera thật nằm
ở [mục 5 của manual-verification.md](../guides/manual-verification.md#5-chế-độ-hiển-thị).

**Chưa kiểm thử:** nhận diện khuôn mặt thật, hiển thị thực tế trên TV hoặc máy
chiếu, âm thanh và giọng đọc.

## 6. Tồn đọng

- Âm thanh của hiệu ứng gọi tên tạo `AudioContext` mới cho mỗi tiếng tích mà không
  đóng lại. Nên dùng chung một context.
- Footer ghi cố định "Hệ thống đang hoạt động ổn định", không phản ánh trạng thái thật.
- Chế độ gỡ lỗi `?overlay=server` do máy chủ vẽ tên lên ảnh, nên không chịu tác
  dụng của chế độ `tv`. Không dùng khi chiếu cho cả lớp.
- Nhãn phiên bản trong footer vẫn là 1.4.0; tham số cache của CSS và JS đã tăng lên
  `?v=1.5.0`. Khi sửa CSS hoặc JS cần tăng tham số này.
