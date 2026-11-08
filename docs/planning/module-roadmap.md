# Lộ trình mở rộng phân hệ

Tài liệu dành cho người phát triển và người quyết định phạm vi dự án. Đây là
**đề xuất, chưa triển khai** (lập ngày 08/11/2026). Mỗi phân hệ cần có đặc tả riêng
trước khi bắt đầu.

Độ lớn là ước lượng tương đối: S (nhỏ), M (vừa), L (lớn).

## Quy trình cho mỗi phân hệ

Repo tích hợp sẵn 4 kỹ năng, dùng theo thứ tự:

| Bước | Kỹ năng | Đầu ra |
|---|---|---|
| 1 | `spec-driven-development` | Đặc tả phạm vi và tiêu chí nghiệm thu |
| 2 | `test-driven-development` | Logic nghiệp vụ kèm test |
| 3 | `impeccable` | Màn hình và trải nghiệm người dùng |
| 4 | `code-review-and-quality` | Rà soát trước khi merge |

## Đợt 1: Nền tảng

| # | Phân hệ | Giải quyết việc gì | Kỹ năng trọng tâm | Độ lớn |
|---|---|---|---|---|
| 1 | Lớp học và tài khoản | Hiện mọi học sinh chung một danh sách và dùng chung một mật khẩu. Thêm lớp, phiên gắn với lớp, tài khoản giáo viên và phân quyền. | Spec, TDD | L |
| 2 | Đồng ý và dữ liệu sinh trắc | Ghi nhận đồng ý của phụ huynh, cho rút đồng ý và xóa khuôn mặt, học sinh không đồng ý thì điểm danh tay, lưu vết ai đã xem ảnh bằng chứng. | Spec, Review | M |
| 3 | Kiểm thử giao diện và migration | Đưa kịch bản Playwright vào repo vì `pytest` chưa kiểm tra UI. Chuyển sang Alembic trước khi đổi CSDL ở mục 1. | TDD | S |

## Đợt 2: Nâng chất lượng nghiệp vụ

| # | Phân hệ | Giải quyết việc gì | Kỹ năng trọng tâm | Độ lớn |
|---|---|---|---|---|
| 4 | Duyệt cảnh báo | API đã lưu ảnh bằng chứng nhưng Dashboard chưa hiển thị. Thêm xem ảnh, xác nhận hoặc bác bỏ, rồi dùng tỷ lệ báo sai để chỉnh ngưỡng. | Impeccable, TDD | M |
| 5 | Điểm danh tin cậy hơn | Nhiều ảnh mẫu cho mỗi học sinh, chống giả mạo bằng ảnh in, hàng chờ "cần xác nhận" khi độ tin cậy thấp. | Spec, TDD | L |
| 6 | Báo cáo chuyên cần | Thống kê theo học sinh, lớp, tháng; biểu đồ; cảnh báo nghỉ nhiều; xuất Excel. | Impeccable, TDD | M |
| 7 | Thời khóa biểu | Tự gợi ý mở phiên theo tiết, ngưỡng đi muộn theo từng tiết. | Spec | M |

## Đợt 3: Mở rộng trải nghiệm

| # | Phân hệ | Giải quyết việc gì | Kỹ năng trọng tâm | Độ lớn |
|---|---|---|---|---|
| 8 | Màn hình TV riêng | Trang chỉ xem cho TV, đồng bộ với máy giáo viên, thay cho hạn chế không dùng được 2 cửa sổ khác chế độ. | Impeccable, Review | M |
| 9 | Công cụ tương tác | Ghi điểm miệng ngay khi gọi, chia nhóm ngẫu nhiên, đồng hồ đếm ngược trên TV. | Impeccable | S–M |
| 10 | Thông báo phụ huynh | Báo vắng qua email hoặc Zalo. Phụ thuộc vào mục 2. | Spec | M |
| 11 | Nhiều camera và xử lý tại chỗ | Tiếp tục giai đoạn 2–3 trong [architecture-proposal.md](architecture-proposal.md): thay bộ nhận diện, edge mode. | Spec, TDD | L |

## Thứ tự khuyến nghị

Bắt đầu từ **mục 3**, sau đó làm **mục 1 và 2 cùng nhau**. Lớp và tài khoản là nền
cho hầu hết phân hệ còn lại. Đồng ý nên có từ đầu vì thêm sau sẽ phải rà lại dữ liệu
đã thu.

Nếu cần thấy giá trị sớm cho giáo viên, **mục 4** là lựa chọn tốt nhất vì khá độc
lập với các mục khác.

## Nguyên tắc cần giữ

- **Dữ liệu trẻ em:** khuôn mặt học sinh là dữ liệu sinh trắc của trẻ vị thành niên.
  Mục 2 cần được đối chiếu với quy định bảo vệ dữ liệu cá nhân hiện hành của Việt
  Nam, tốt nhất có người phụ trách pháp lý của trường cùng xem.
- **Cảnh báo hành vi chỉ là gợi ý:** phát hiện "quay cóp" hay "ngủ gục" dựa trên góc
  đầu và mắt nên sẽ có báo sai. Không nối cảnh báo vào điểm số hay kỷ luật, và không
  gửi cho phụ huynh khi chưa có giáo viên xác nhận ở mục 4.
