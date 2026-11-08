# Danh sách Kiểm tra Triển khai (Implementation Checklist)

Tài liệu này dùng để theo dõi tiến độ thực hiện và kiểm soát chất lượng (QA/QC) trong suốt quá trình phát triển hệ thống Điểm danh & Giám sát Lớp học Thông minh.

---

## 🗂️ 1. Thiết lập Môi trường & Cấu trúc Dự án
- [x] Khởi tạo môi trường ảo Python (`venv`) và cài đặt thư viện (`requirements.txt`).
- [x] Cấu hình các tệp tin cấu hình dự án ở thư mục gốc: `.gitignore`, `LICENSE`, `README.md`.
- [x] Khởi tạo cấu trúc các thư mục con và file trong thư mục cốt lõi `src/`.
- [x] Kiểm tra liên kết tương đối giữa các file trong cấu trúc mã nguồn.

---

## 🗄️ 2. Cơ sở Dữ liệu & Đăng ký Học sinh
- [x] Cấu hình kết nối SQLite và Session SQLAlchemy trong [database.py](file:///Users/quocthang0507/GitHub/face-recognition/src/database.py).
- [x] Thiết kế và tạo các bảng cơ sở dữ liệu trong [models.py](file:///Users/quocthang0507/GitHub/face-recognition/src/models.py):
    - [x] Bảng `students` (Thông tin học sinh & Embeddings).
    - [x] Bảng `sessions` (Các phiên học).
    - [x] Bảng `session_students` (Trạng thái điểm danh & gọi trả bài).
    - [x] Bảng `behavior_logs` (Nhật ký hành vi vi phạm & đường dẫn ảnh chụp làm bằng chứng).
- [x] Tạo API đăng ký học sinh mới (`/register`):
    - [x] Nhập thông tin (mã số học sinh, họ tên).
    - [x] Nhận hình ảnh, chạy trích xuất đặc trưng khuôn mặt (128-D/512-D vector embeddings).
    - [x] Lưu vector dạng JSON string/BLOB vào DB và ảnh đại diện vào thư mục được phân quyền.

---

## 🧠 3. Logic Xử lý AI & Phân tích Hành vi (`behavior_engine.py`)
- [x] Tích hợp MediaPipe Face Mesh (468 landmarks) và MediaPipe Hands (21 landmarks).
- [x] **Phát hiện Ngủ gục (Sleeping)**:
    - [x] Tính toán chỉ số tỉ lệ mở mắt (Eye Aspect Ratio - EAR) cho cả hai mắt.
    - [x] Xác định ngưỡng nhắm mắt và logic đếm thời gian liên tục ($N$ giây).
    - [x] Ước lượng độ nghiêng đầu gục xuống (Pitch angle).
- [x] **Phát hiện Chống tay (Hand on Face)**:
    - [x] Tính khoảng cách Euclidean giữa các điểm mốc tay (ngón tay, lòng bàn tay) và các điểm biên khuôn mặt.
    - [x] Thiết lập ngưỡng phát hiện chống cằm/má.
- [x] **Phát hiện Quay cóp (Cheating)**:
    - [x] Giải thuật toán PnP (Perspective-n-Point) bằng `cv2.solvePnP` để tìm góc Yaw, Pitch, Roll của đầu.
    - [x] Thiết lập ngưỡng quay đầu sang trái/phải quá $\pm 30^\circ$.
- [x] **Phát hiện Trao đổi bài (Talking)**:
    - [x] Tính tỉ lệ mở miệng (Mouth Aspect Ratio - MAR).
    - [x] Phân tích dao động mở/khép khẩu hình liên tục ở tần số nói chuyện.

---

## 🔍 4. Nhận diện Khuôn mặt & WebSocket Server (`face_engine.py` & `main.py`)
- [x] Xây dựng bộ so khớp khuôn mặt thời gian thực sử dụng DeepFace/face_recognition:
    - [x] Cắt khuôn mặt từ bounding box.
    - [x] So sánh khoảng cách Cosine/Euclidean giữa khuôn mặt hiện tại và các vector đã đăng ký trong Database.
- [x] Thiết lập cơ chế tối ưu hóa tốc độ:
    - [x] Chỉ chạy nhận diện khuôn mặt (nặng) định kỳ mỗi 1.5 giây một lần.
    - [x] Sử dụng tracker hoặc ID Landmark MediaPipe trên các frame ở giữa để duy trì danh tính.
- [x] Xây dựng WebSocket Server nhận dữ liệu frame video từ client, xử lý đồng thời nhận diện và hành vi, sau đó trả về metadata và frame đã vẽ overlay.

---

## 👩‍🏫 5. Giao diện Dashboard Giáo viên & Tối ưu Client
- [x] Thiết kế trang Dashboard sang trọng (Dark mode & Glassmorphism) trong [index.html](file:///Users/quocthang0507/GitHub/face-recognition/src/templates/index.html) và [style.css](file:///Users/quocthang0507/GitHub/face-recognition/src/static/css/style.css).
- [x] Viết JS kết nối WebSocket webcam thời gian thực mượt mà trong [app.js](file:///Users/quocthang0507/GitHub/face-recognition/src/static/js/app.js).
- [x] Xây dựng tính năng gọi ngẫu nhiên học sinh trả bài (Random Student Picker) có hiệu ứng vòng xoay.
- [x] Hiển thị thông báo Alert dạng toast trực quan khi phát hiện học sinh ngủ gục, chống tay, quay cóp.
- [x] **Hộp thoại Cài đặt Tập trung (Settings Modal)**:
    - [x] Thêm modal `#settings-modal` để đưa tất cả các cấu hình điều khiển vào một nơi tập trung.
    - [x] Di chuyển chọn nguồn camera, tần suất gửi ảnh (FPS), âm thanh bíp và TTS tiếng Việt vào modal.
    - [x] Tích hợp thêm tùy chọn chọn giọng đọc TTS phù hợp từ danh sách giọng nói của hệ thống.
    - [x] Thay thế nút đổi giao diện sáng/tối bằng thẻ chọn (Select) trong Modal Cài đặt.
- [x] **Tối ưu hóa Truyền tải & Băng thông (Adaptive Downscaling)**:
    - [x] Tự động thu nhỏ ảnh camera về chiều rộng tối đa 640px trong JS để giảm 80% tải mạng.
    - [x] Giảm chất lượng nén ảnh xuống 70% để luồng stream qua WebSocket chạy mượt hơn.
- [x] **Điều chỉnh tần suất truyền hình ảnh (Dynamic Client Capture FPS)**:
    - [x] Thêm dropdown `#video-fps-select` cho phép cấu hình 15 FPS, 10 FPS, 5 FPS, hoặc 2 FPS trực tiếp trên giao diện.
    - [x] Triển khai hàm `restartCameraTimer()` tự động cấu hình lại `setInterval` của WebSocket client mà không cần ngắt camera.
    - [x] Lưu trữ cấu hình FPS đã chọn vào `localStorage` của trình duyệt.
- [x] **Cảnh báo thông minh bằng Âm thanh & Giọng nói**:
    - [x] Phát tiếng bíp kép cảnh báo vi phạm sử dụng Web Audio API (chạy offline).
    - [x] Đọc to cảnh báo bằng tiếng Việt sử dụng Web Speech API (`SpeechSynthesis`).
    - [x] Thêm các checkboxes điều khiển bật/tắt âm thanh/giọng nói trên Dashboard và đồng bộ hóa qua `localStorage`.
    - [x] Áp dụng cơ chế **Alert Cooldown (10 giây)** để hạn chế ô nhiễm tiếng ồn khi có vi phạm liên tiếp.

---

## 🛡️ 6. Tiêu chuẩn Code sạch & Bảo mật
- [x] Kiểm tra phong cách viết code tuân thủ quy tắc PEP 8 (`black`/`flake8`).
- [x] Đảm bảo mã nguồn được thiết kế đúng nguyên lý SOLID (SRP).
- [x] Đảm bảo an toàn dữ liệu sinh trắc học học sinh (Chỉ lưu vector embeddings số học).
- [x] Ngăn chặn tấn công SQL Injection bằng cách sử dụng SQLAlchemy ORM.
- [x] Bảo mật luồng truyền tải camera bằng HTTPS và WSS.
- [x] Triển khai cơ chế dọn dẹp định kỳ (tự động xóa log vi phạm và ảnh bằng chứng cũ hơn 30 ngày).

---

## 🧪 7. Kiểm thử & Nghiệm thu (Verification)
- [x] Chạy unit test (`pytest`) kiểm tra các hàm xử lý hình học hành vi, token và API.
- [ ] Kiểm thử thủ công (Xem [manual-verification.md](../guides/manual-verification.md)):
    - [ ] Thử nghiệm đăng ký 3 học sinh mẫu với các góc mặt khác nhau.
    - [ ] Kiểm tra nhận dạng khuôn mặt và điểm danh chính xác khi học sinh ngồi trước webcam.
    - [ ] Thử nghiệm gọi học sinh ngẫu nhiên 3-5 lần liên tiếp để đảm bảo không bị trùng lặp và reset hoạt động bình thường.
    - [ ] Mô phỏng các hành vi nhắm mắt ngủ, chống cằm, quay đầu, nói chuyện liên tục để kiểm tra cảnh báo realtime, âm thanh bíp, đọc giọng nói tiếng Việt và cơ chế cooldown 10 giây.
    - [ ] Kiểm tra chế độ `Chiếu TV` và `Máy tính GV` trên màn hình thật của lớp (mục 5 trong tài liệu nghiệm thu).

---

## 🚀 8. Các Cải tiến & Tối ưu đã Hoàn thành
- [x] Việt hóa hoàn toàn giao diện người dùng, nhãn cảnh báo và phản hồi lỗi từ API.
- [x] Thiết lập vẽ chữ tiếng Việt Unicode trên Video sử dụng PIL và font chữ hệ thống `Arial.ttf`.
- [x] Xây dựng cơ chế vẽ dự phòng (Fallback) an toàn về `cv2.putText` nếu PIL gặp sự cố vẽ.
- [x] Tối ưu hiển thị camera tức thì bằng cách thay đổi thuộc tính opacity trong CSS.
- [x] Tải trước các mô hình AI chạy nền (FastAPI lifespan preloading) để triệt tiêu độ trễ của frame đầu tiên.
- [x] Tạo dropdown tùy chọn nguồn video nóng (Camera Selector) hỗ trợ đổi webcam thời gian thực.
- [x] Sửa lỗi RuntimeError ngắt kết nối WebSocket khi reload trang hoặc tắt camera.
- [x] Giải quyết xung đột thư viện và cài đặt các phụ thuộc `tensorflow`, `tf-keras` và `protobuf` tương thích.
- [x] Thêm favicon chất lượng cao đồng bộ với giao diện Dashboard của hệ thống.
- [x] Tự động giảm độ phân giải camera phía Client (thu nhỏ về chiều rộng tối đa 640px) trong `sendFrame()` để tối ưu băng thông.
- [x] Nén JPEG chất lượng 70% ở Client để tối ưu hóa hiệu năng truyền tải.
- [x] Phát âm thanh bíp kép cảnh báo sử dụng Web Audio API (không phụ thuộc file âm thanh tĩnh).
- [x] Đọc to cảnh báo bằng giọng nói tiếng Việt sử dụng Web Speech API (`SpeechSynthesis`).
- [x] Thiết kế checkboxes bật/tắt âm thanh cảnh báo và đọc giọng nói trong settings modal.
- [x] Lưu trữ trạng thái bật/tắt cảnh báo âm thanh/giọng nói vào `localStorage` của trình duyệt.
- [x] Triển khai bộ đệm và cơ chế cooldown 10 giây cho cảnh báo âm thanh và giọng nói theo từng học sinh + loại hành vi để chống ồn.
- [x] Tích hợp dropdown tùy chọn tần suất gửi khung hình (15 FPS / 10 FPS / 5 FPS / 2 FPS) và lưu cấu hình vào `localStorage`.
- [x] Triển khai logic điều chỉnh lại tần suất gửi khung hình camera trực tiếp mà không cần khởi động lại kết nối.
- [x] Xây dựng Hộp thoại Cài đặt Tập trung (Settings Modal) quản lý nguồn camera, FPS, theme sáng/tối và âm thanh/TTS giọng nói tiếng Việt ở một nơi.
- [x] Tích hợp bộ chọn giọng đọc TTS (Voice Selector) tiếng Việt/hệ thống, lưu trữ lựa chọn vào `localStorage` và tự động cập nhật giọng đọc khi giáo viên lựa chọn.
- [x] Tinh chỉnh giao diện cho lớp học: nền đặc, tương phản cao, nút có icon, trạng thái trống có hướng dẫn (Xem [ui-refresh-2026-11.md](../reviews/ui-refresh-2026-11.md)).
- [x] Thêm 2 chế độ hiển thị `Máy tính GV` và `Chiếu TV`, che tên học sinh trong cảnh báo khi chiếu (Xem [display-modes.md](../guides/display-modes.md)).
