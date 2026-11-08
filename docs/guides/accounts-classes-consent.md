# Hướng dẫn tài khoản, lớp học và đồng ý

Dành cho Quản trị và giáo viên sử dụng Dashboard.

## Lần đầu sau khi nâng cấp

1. Đăng nhập bằng tên `admin` và mật khẩu giáo viên đang dùng trước đây.
2. Bấm `Quản trị`, đặt lại mật khẩu cho `admin` nếu đó vẫn là mật khẩu mặc định.
3. Tạo tài khoản cho từng giáo viên.
4. Tạo các lớp và đánh dấu giáo viên phụ trách từng lớp.

Học sinh và phiên học cũ nằm trong `Lớp mặc định`. Mọi người cần đăng nhập lại sau khi
nâng cấp. Trước khi nâng cấp, hệ thống tự tạo bản sao `classroom.db.bak-<phiên bản>`
trong thư mục dữ liệu và tự xóa bản sao này sau thời gian lưu trữ (30 ngày).

## Vai trò

| Việc | Quản trị | Giáo viên |
|---|---|---|
| Tạo tài khoản, lớp, phân công giáo viên | Có | Không |
| Thêm học sinh có sẵn vào lớp khác | Có | Không |
| Mở phiên, điểm danh, gọi trả bài | Mọi lớp | Lớp được phân công |
| Đăng ký học sinh, ghi nhận đồng ý | Mọi lớp | Lớp được phân công |
| Xem nhật ký xem ảnh | Có | Không |

## Chọn lớp

Chọn lớp ở thanh đầu trang trước khi bắt đầu tiết học. Danh sách, phiên học, cảnh báo
và nhận diện khuôn mặt đều theo lớp đang chọn. Ở chế độ Chiếu TV, bộ chọn lớp được ẩn,
nên hãy chọn lớp trước khi chuyển chế độ.

Một học sinh có thể học nhiều lớp theo môn. Mã học sinh là duy nhất, nên học sinh đã có
mã phải được Quản trị thêm vào lớp mới bằng `Thêm vào lớp`. Khi gỡ học sinh khỏi một lớp,
học sinh vẫn còn ở các lớp khác và chỉ bị xóa hẳn khi đó là lớp cuối cùng.

## Ghi nhận đồng ý của phụ huynh

Chỉ ghi nhận sau khi nhà trường đã nhận được văn bản đồng ý.

| Trạng thái | Khuôn mặt | Camera nhận diện | Điểm danh thủ công |
|---|---|---|---|
| Chờ xác nhận | Không được lưu | Không | Có |
| Đã đồng ý | Được lưu | Có | Có |
| Từ chối | Bị xóa | Không | Có |
| Đã rút | Bị xóa | Không | Có |

- Đánh dấu ô `Đã có văn bản đồng ý của phụ huynh` khi đăng ký, hoặc đổi trạng thái ở cột
  `Đồng ý` trong Danh sách lớp.
- **Từ chối hoặc Đã rút sẽ xóa ngay** vector khuôn mặt, ảnh đại diện và ảnh bằng chứng,
  không khôi phục được. Lịch sử điểm danh vẫn được giữ.
- Nếu một ảnh bằng chứng có cả học sinh khác, ảnh đó và các cảnh báo gắn với nó cũng bị xóa.
- Sau khi ghi nhận lại `Đã đồng ý`, cần chụp lại ảnh khuôn mặt.

**Học sinh đã có khuôn mặt trước khi nâng cấp được hệ thống coi là đã đồng ý.** Nhà trường
cần bảo đảm thực sự có văn bản đồng ý cho các học sinh này, nếu không thì đổi sang
`Từ chối`.
