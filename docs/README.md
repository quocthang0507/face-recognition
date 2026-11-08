# Tài liệu dự án Smart Classroom

Mục lục toàn bộ tài liệu. Hướng dẫn cài đặt và chạy ứng dụng nằm ở
[README của dự án](../README.md).

## Hướng dẫn và nghiệm thu (`guides/`)

| Tài liệu | Nội dung | Dành cho |
|---|---|---|
| [display-modes.md](guides/display-modes.md) | Dùng chế độ Máy tính GV và Chiếu TV, quyền riêng tư khi chiếu | Giáo viên |
| [manual-verification.md](guides/manual-verification.md) | Các bước nghiệm thu với webcam và người thật | Người kiểm thử |

## Kế hoạch và lộ trình (`planning/`)

| Tài liệu | Nội dung | Trạng thái |
|---|---|---|
| [module-roadmap.md](planning/module-roadmap.md) | Lộ trình mở rộng phân hệ, chức năng | Xong mục 3, các mục khác là đề xuất |
| [spec-e2e-alembic.md](planning/spec-e2e-alembic.md) | Đặc tả kiểm thử giao diện và migration CSDL | Đã triển khai |
| [architecture-proposal.md](planning/architecture-proposal.md) | Nâng cấp kiến trúc, tối ưu hiệu năng | Xong giai đoạn 0–1, còn giai đoạn 2–3 |
| [check-list.md](planning/check-list.md) | Danh sách kiểm tra tiến độ và chất lượng | Đang theo dõi |
| [implementation-plan.md](planning/implementation-plan.md) | Kế hoạch triển khai ban đầu | Lưu trữ, một số mô tả giao diện đã cũ |

## Ghi chép theo đợt (`reviews/`)

Mỗi file ghi lại một đợt thay đổi tại thời điểm đó, đặt tên theo `chu-de-YYYY-MM.md`.

| Tài liệu | Nội dung |
|---|---|
| [ui-refresh-2026-11.md](reviews/ui-refresh-2026-11.md) | Nâng cấp giao diện, quy ước thiết kế, phạm vi đã kiểm thử |
| [review-2026-11.md](reviews/review-2026-11.md) | Rà soát nghiệp vụ điểm danh, API mới, quy trình đề xuất |

## Khi thêm tài liệu mới

- Hướng dẫn thao tác đưa vào `guides/`, kế hoạch hoặc đề xuất đưa vào `planning/`,
  ghi chép một đợt thay đổi đưa vào `reviews/`.
- Thêm một dòng vào mục lục này.
- Dùng đường dẫn tương đối khi liên kết giữa các tài liệu.
