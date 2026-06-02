# Danh sách Kiểm tra Triển khai (Implementation Checklist)

Tài liệu này dùng để theo dõi tiến độ thực hiện và kiểm soát chất lượng (QA/QC) trong suốt quá trình phát triển hệ thống Điểm danh & Giám sát Lớp học Thông minh.

---

## 🗂️ 1. Thiết lập Môi trường & Cấu trúc Dự án
- [ ] Khởi tạo môi trường ảo Python (`venv`) và cài đặt thư viện (`requirements.txt`).
- [ ] Cấu hình các tệp tin cấu hình dự án ở thư mục gốc: `.gitignore`, `LICENSE`, `README.md`.
- [ ] Khởi tạo cấu trúc các thư mục con và file trong thư mục cốt lõi `src/`.
- [ ] Kiểm tra liên kết tương đối giữa các file trong cấu trúc mã nguồn.

---

## 🗄️ 2. Cơ sở Dữ liệu & Đăng ký Học sinh
- [ ] Cấu hình kết nối SQLite và Session SQLAlchemy trong [database.py](file:///Users/quocthang0507/GitHub/face-recognition/src/database.py).
- [ ] Thiết kế và tạo các bảng cơ sở dữ liệu trong [models.py](file:///Users/quocthang0507/GitHub/face-recognition/src/models.py):
    - [ ] Bảng `students` (Thông tin học sinh & Embeddings).
    - [ ] Bảng `sessions` (Các phiên học).
    - [ ] Bảng `session_students` (Trạng thái điểm danh & gọi trả bài).
    - [ ] Bảng `behavior_logs` (Nhật ký hành vi vi phạm & đường dẫn ảnh chụp làm bằng chứng).
- [ ] Tạo API đăng ký học sinh mới (`/register`):
    - [ ] Nhập thông tin (mã số học sinh, họ tên).
    - [ ] Nhận hình ảnh, chạy trích xuất đặc trưng khuôn mặt (128-D/512-D vector embeddings).
    - [ ] Lưu vector dạng JSON string/BLOB vào DB và ảnh đại diện vào thư mục được phân quyền.

---

## 🧠 3. Logic Xử lý AI & Phân tích Hành vi (`behavior_engine.py`)
- [ ] Tích hợp MediaPipe Face Mesh (468 landmarks) và MediaPipe Hands (21 landmarks).
- [ ] **Phát hiện Ngủ gục (Sleeping)**:
    - [ ] Tính toán chỉ số tỉ lệ mở mắt (Eye Aspect Ratio - EAR) cho cả hai mắt.
    - [ ] Xác định ngưỡng nhắm mắt và logic đếm thời gian liên tục ($N$ giây).
    - [ ] Ước lượng độ nghiêng đầu gục xuống (Pitch angle).
- [ ] **Phát hiện Chống tay (Hand on Face)**:
    - [ ] Tính khoảng cách Euclidean giữa các điểm mốc tay (ngón tay, lòng bàn tay) và các điểm biên khuôn mặt.
    - [ ] Thiết lập ngưỡng phát hiện chống cằm/má.
- [ ] **Phát hiện Quay cóp (Cheating)**:
    - [ ] Giải thuật toán PnP (Perspective-n-Point) bằng `cv2.solvePnP` để tìm góc Yaw, Pitch, Roll của đầu.
    - [ ] Thiết lập ngưỡng quay đầu sang trái/phải quá $\pm 30^\circ$.
- [ ] **Phát hiện Trao đổi bài (Talking)**:
    - [ ] Tính tỉ lệ mở miệng (Mouth Aspect Ratio - MAR).
    - [ ] Phân tích dao động mở/khép khẩu hình liên tục ở tần số nói chuyện.

---

## 🔍 4. Nhận diện Khuôn mặt & WebSocket Server (`face_engine.py` & `main.py`)
- [ ] Xây dựng bộ so khớp khuôn mặt thời gian thực sử dụng DeepFace/face_recognition:
    - [ ] Cắt khuôn mặt từ bounding box.
    - [ ] So sánh khoảng cách Cosine/Euclidean giữa khuôn mặt hiện tại và các vector đã đăng ký trong Database.
- [ ] Thiết lập cơ chế tối ưu hóa tốc độ:
    - [ ] Chỉ chạy nhận diện khuôn mặt (nặng) định kỳ mỗi 1.5 giây một lần.
    - [ ] Sử dụng tracker hoặc ID Landmark MediaPipe trên các frame ở giữa để duy trì danh tính.
- [ ] Xây dựng WebSocket Server nhận dữ liệu frame video từ client, xử lý đồng thời nhận diện và hành vi, sau đó trả về metadata và frame đã vẽ overlay.

---

## 👩‍🏫 5. Giao diện Dashboard Giáo viên (Frontend)
- [ ] Thiết kế trang Dashboard sang trọng (Dark mode & Glassmorphism) trong [index.html](file:///Users/quocthang0507/GitHub/face-recognition/src/templates/index.html) và [style.css](file:///Users/quocthang0507/GitHub/face-recognition/src/static/css/style.css).
- [ ] Viết JS kết nối WebSocket webcam thời gian thực mượt mà trong [app.js](file:///Users/quocthang0507/GitHub/face-recognition/src/static/js/app.js).
- [ ] Xây dựng tính năng gọi ngẫu nhiên học sinh trả bài (Random Student Picker):
    - [ ] Nút bấm gọi ngẫu nhiên gửi request lên API.
    - [ ] Hiệu ứng vòng xoay chọn học sinh sinh động.
    - [ ] Cập nhật trạng thái `is_called = True` và thời gian gọi.
    - [ ] Nút Reset phiên gọi để làm mới trạng thái cho toàn bộ học sinh có mặt.
- [ ] Hiển thị thông báo Alert dạng toast hoặc pop-up trực quan khi phát hiện học sinh ngủ gục, chống tay, quay cóp.

---

## 🛡️ 6. Tiêu chuẩn Code sạch & Bảo mật
- [ ] Kiểm tra phong cách viết code tuân thủ quy tắc PEP 8 (`black`/`flake8`).
- [ ] Đảm bảo mã nguồn được thiết kế đúng nguyên lý SOLID (đặc biệt là tính phân tách độc lập SRP của các module).
- [ ] Đảm bảo an toàn dữ liệu sinh trắc học học sinh (Không lưu ảnh gốc, chỉ lưu vector embeddings số học).
- [ ] Ngăn chặn tấn công SQL Injection bằng cách sử dụng tham số hóa (SQLAlchemy ORM).
- [ ] Bảo mật luồng truyền tải camera bằng HTTPS và WSS.
- [ ] Triển khai cơ chế dọn dẹp định kỳ (tự động xóa log vi phạm và ảnh bằng chứng cũ hơn 30 ngày).

---

## 🧪 7. Kiểm thử & Nghiệm thu (Verification)
- [ ] Chạy unit test (`pytest`) kiểm tra các hàm xử lý hình học hành vi.
- [ ] Kiểm thử thủ công (Manual Test):
    - [ ] Thử nghiệm đăng ký 3 học sinh mẫu với các góc mặt khác nhau.
    - [ ] Kiểm tra nhận dạng khuôn mặt và điểm danh chính xác khi học sinh ngồi trước webcam.
    - [ ] Thử nghiệm gọi học sinh ngẫu nhiên 3-5 lần liên tiếp để đảm bảo không bị trùng lặp và reset hoạt động bình thường.
    - [ ] Mô phỏng các hành vi nhắm mắt ngủ, chống cằm, quay đầu nhìn bài bạn, nói chuyện liên tục để kiểm tra cảnh báo realtime.
