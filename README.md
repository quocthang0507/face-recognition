# Smart Classroom - Hệ thống Điểm danh & Giám sát Lớp học Thông minh

Hệ thống ứng dụng Trí tuệ Nhân tạo (AI) và Thị giác Máy tính (Computer Vision) để hỗ trợ giáo viên quản lý lớp học trực quan, điểm danh tự động, gọi học sinh ngẫu nhiên trả bài và phát hiện các hành vi bất thường của học sinh trong thời gian thực.

---

## 🌟 Tính năng Nổi bật

*   **Nhận diện đa khuôn mặt thời gian thực**: Tự động phát hiện và nhận diện danh tính của nhiều học sinh trong khung hình từ nguồn camera/webcam.
*   **Việt hóa Giao diện 100%**: Toàn bộ giao diện người dùng, nhãn cảnh báo (eyebrow), nhật ký hành vi và các phản hồi lỗi từ API/WebSocket được dịch thuật chuẩn xác sang tiếng Việt.
*   **Quy trình điểm danh đầy đủ (v1.3)**:
    *   Ghi nhận giờ vào lớp, tự đánh dấu **đi muộn** sau `FACE_APP_LATE_AFTER_MINUTES` phút (mặc định 15).
    *   Giáo viên **điểm danh thủ công** / đánh dấu vắng kèm lý do; camera không ghi đè quyết định thủ công.
    *   Đặt tên buổi học, xem **tổng kết khi kết thúc phiên**, **lịch sử phiên** và **xuất bảng điểm danh CSV** (mở được bằng Excel).
    *   Cập nhật ảnh khuôn mặt, xóa học sinh, chặn đăng ký trùng khuôn mặt, cảnh báo học sinh chưa có ảnh.
    *   Chi tiết rà soát và quy trình: [docs/review-2026-11.md](docs/review-2026-11.md).
*   **Quản lý phiên gọi ngẫu nhiên (Random Student Picker)**:
    *   Hỗ trợ giáo viên chọn ngẫu nhiên một học sinh trong danh sách những người có mặt để trả bài (không gọi học sinh vắng).
    *   Tự động lưu trạng thái đã gọi/chưa gọi trong phiên học hiện tại để tránh trùng lặp.
*   **Phát hiện hành vi bất thường**:
    *   Có thể bật hoặc tắt từng loại kiểm tra trực tiếp trên Dashboard mà không cần bắt đầu phiên điểm danh.
    *   **Ngủ gục (Sleeping)**: Phân tích chỉ số EAR (Eye Aspect Ratio) kết hợp độ nghiêng của đầu (Pitch).
    *   **Chống tay (Hand on Face)**: Phân tích khoảng cách giữa các điểm mốc bàn tay và khuôn mặt để phát hiện học sinh đang chống tay lên cằm/má.
    *   **Quay cóp (Cheating)**: Hướng nhìn đầu (Head Pose Estimation - Yaw/Pitch/Roll) để phát hiện hành vi quay trái/phải hoặc nhìn bài.
    *   **Trao đổi (Talking)**: Phân tích chỉ số mở miệng (Mouth Aspect Ratio) biến động ở tần số nói chuyện.
*   **Cảnh báo âm thanh & Giọng nói (Audio & TTS Warnings)**:
    *   Phát tiếng bíp kép cảnh báo sử dụng Web Audio API (chạy offline hoàn toàn).
    *   Đọc to cảnh báo bằng tiếng Việt (Web Speech TTS) như *"Cảnh báo ngủ gục: Nguyễn Văn A"*.
    *   Cơ chế **Alert Cooldown (10 giây)** thông minh cho mỗi học sinh + loại hành vi để ngăn chặn ồn ào và chồng chéo giọng nói.
    *   Có các checkbox điều khiển bật/tắt trực quan và lưu trạng thái vào trình duyệt.
*   **Tối ưu hóa hiệu năng & Chạy mượt (Downscaling, Preloading & FPS Control)**:
    *   Client tự động nén và thu nhỏ ảnh về chiều rộng tối đa 640px (JPEG 70%) trước khi truyền đi, tiết kiệm ~80% dung lượng mạng và 50% CPU server.
    - Hỗ trợ dropdown tùy chọn tần suất gửi khung hình (**10 FPS / 5 FPS / 2 FPS**) giúp giáo viên chủ động điều chỉnh hiệu năng và tiết kiệm băng thông khi cần thiết.
    - FastAPI tự động nạp trước (preload) các mô hình DeepFace và MediaPipe khi khởi chạy máy chủ (lifespan), giúp bật camera lên là có hình ảnh phân tích ngay lập tức.
*   **Hộp thoại Cài đặt Tập trung (Settings Modal)**: Tích hợp cấu hình chọn nguồn camera (Hot-swapping), tần suất gửi khung hình (FPS), bật/tắt âm thanh/giọng nói cảnh báo, **tùy chọn bộ lọc giọng đọc TTS hệ thống** và chuyển đổi giao diện sáng/tối vào một cửa sổ popup duy nhất để làm gọn Dashboard.
*   **Giao diện Dashboard hiện đại**:
    *   Thiết kế cao cấp theo xu hướng **Glassmorphism** và **Dark Mode** tự động ghi nhớ tùy chọn trên trình duyệt.
    *   Có nút xóa audit trail kèm snapshot bằng chứng sau bước xác nhận.
    *   Hiển thị live stream video vẽ kèm bounding box, landmarks và các cảnh báo thời gian thực.
    *   Sidebar thống kê nhanh và quản lý danh sách học sinh.

---

## 🛠️ Công nghệ Sử dụng

*   **Ngôn ngữ**: Python 3.10+
*   **Thư viện xử lý AI & Thị giác**:
    *   **MediaPipe** (Face Mesh, Hand Landmarker) cho ước lượng tư thế đầu và phát hiện hành vi.
    *   **DeepFace** cho việc trích xuất vector đặc trưng khuôn mặt (face embeddings).
    *   **OpenCV** cho các thuật toán xử lý hình học và xử lý frame hình ảnh.
    *   **Pillow** hỗ trợ vẽ Tiếng Việt Unicode trực tiếp trên hình ảnh camera.
*   **Framework Backend**: **FastAPI** hỗ trợ WebSockets streaming và API xử lý bất đồng bộ (async).
*   **Cơ sở Dữ liệu**: **SQLite** tích hợp cùng ORM **SQLAlchemy**.
*   **Frontend**: HTML5, Vanilla CSS (Glassmorphism), Vanilla JS (WebSockets Client, Web Audio API, Web Speech API).

---

## 📁 Cấu trúc Thư mục Dự án

Toàn bộ mã nguồn cốt lõi của ứng dụng được tổ chức tập trung hoàn toàn bên trong thư mục `src`:

```text
├── src/
│   ├── database.py       # Cấu hình kết nối SQLite & SQLAlchemy Engine
│   ├── models.py         # Định nghĩa cấu trúc bảng (Students, Sessions, Logs)
│   ├── face_engine.py    # Module xử lý nhận diện khuôn mặt
│   ├── behavior_engine.py# Module phân tích hành vi học sinh bằng MediaPipe
│   ├── main.py           # API FastAPI & WebSocket Server xử lý frame video
│   ├── static/           # Tài nguyên tĩnh phục vụ cho Frontend
│   │   ├── css/
│   │   │   └── style.css # CSS Giao diện Dashboard tối giản, hiện đại
│   │   └── js/
│   │       └── app.js    # Logic kết nối WebSockets client, downscaling & audio/TTS alerts
│   └── templates/
│       └── index.html    # Trang giao diện chính của Giáo viên
├── docs/
│   ├── implementation-plan.md # Tài liệu kế hoạch triển khai chi tiết
│   └── check-list.md          # Tài liệu danh sách kiểm tra tiến độ dự án
├── .gitignore            # Cấu hình bỏ qua các file thừa khi dùng Git
├── LICENSE               # Giấy phép phần mềm (MIT License)
└── requirements.txt      # Danh sách các thư viện phụ thuộc
```

---

## 🚀 Hướng dẫn Cài đặt & Chạy ứng dụng

### 1. Yêu cầu Hệ thống
*   Hệ điều hành: macOS, Windows, Linux.
*   Python 3.10 trở lên.
*   Webcam hoặc thiết bị đầu vào video tương tự kết nối với máy tính.

### 2. Cài đặt Môi trường
1.  **Clone mã nguồn**:
    ```bash
    git clone https://github.com/quocthang0507/face-recognition.git
    cd face-recognition
    ```
2.  **Khởi tạo môi trường ảo Python**:
    ```bash
    python -m venv venv
    source venv/bin/activate  # Đối với macOS/Linux
    # venv\Scripts\activate   # Đối với Windows
    ```
3.  **Cài đặt các gói thư viện**:
    ```bash
    pip install -r requirements.txt
    ```
    Cài thêm DeepFace để bật đăng ký và so khớp danh tính:
    ```bash
    pip install -r requirements-ai.txt
    ```

4.  **Cấu hình thông tin đăng nhập**:
    Mật khẩu giáo viên mặc định khi chạy development là `change-me`. Có thể thay đổi mật khẩu và khóa ký token bằng biến môi trường:
    ```bash
    export FACE_APP_TEACHER_PASSWORD='replace-this-password'
    export FACE_APP_TOKEN_SECRET='replace-this-random-secret'
    ```

### 3. Khởi chạy Ứng dụng
Khởi chạy server FastAPI bằng lệnh:
```bash
uvicorn src.main:app --reload
```
Sau đó, mở trình duyệt web và truy cập địa chỉ: [http://127.0.0.1:8000](http://127.0.0.1:8000).

Khi chạy local mà không cấu hình biến môi trường, đăng nhập Dashboard bằng:
```text
Mật khẩu: change-me
```

Nếu dùng VS Code, chọn cấu hình `Smart Classroom: Web App` trong `Run and Debug`, sau đó nhấn `F5`. Server sẽ khởi động và tự mở Dashboard trên trình duyệt mặc định. Cấu hình local này cũng sử dụng mật khẩu `change-me`.

### 4. Kiểm thử tự động
```bash
pytest src/tests
black --check src
flake8 src
```

### 5. Triển khai production
Đặt ứng dụng sau reverse proxy HTTPS, sau đó bật cookie bảo mật và bắt buộc HTTPS/WSS:
```bash
export FACE_APP_SECURE_COOKIE=true
export FACE_APP_SECURE_TRANSPORT_ONLY=true
export FACE_APP_ALLOWED_ORIGINS='https://classroom.example.com'
```

Avatar được mã hóa lưu trữ trên đĩa. Snapshot cảnh báo chỉ được truy cập qua API đã xác thực và tự động được xóa cùng log cũ sau 30 ngày khi ứng dụng khởi động, sau đó tiếp tục được dọn định kỳ mỗi 24 giờ.

### 6. Nghiệm thu webcam
Quy trình nghiệm thu với người thật và công cụ preview chỉ số hành vi được mô tả trong [docs/manual-verification.md](docs/manual-verification.md):
```bash
python -m src.manual_verification
```

### 7. Log MediaPipe trên Terminal
Khi bật camera, MediaPipe có thể ghi các dòng khởi tạo native như:
```text
WARNING: All log messages before absl::InitializeLog() is called are written to STDERR
INFO: Created TensorFlow Lite XNNPACK delegate for CPU.
W... inference_feedback_manager.cc...
W... landmark_projection_calculator.cc...
```

Đây là log từ MediaPipe/TFLite, không phải lỗi của WebSocket hoặc FastAPI. Ứng dụng vẫn hoạt động bình thường nếu Dashboard tiếp tục nhận frame và terminal có dòng `connection open`. Chỉ cần điều tra thêm khi xuất hiện traceback Python, dòng native bắt đầu bằng `E`/`F`, WebSocket tự đóng hoặc Dashboard không còn cập nhật ảnh.

---

## 📄 Bản quyền (License)

Dự án này được phát hành dưới giấy phép **MIT License**. Chi tiết xem tại file [LICENSE](file:///Users/quocthang0507/GitHub/face-recognition/LICENSE).
