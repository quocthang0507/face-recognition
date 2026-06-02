# Smart Classroom - Hệ thống Điểm danh & Giám sát Lớp học Thông minh

Hệ thống ứng dụng Trí tuệ Nhân tạo (AI) và Thị giác Máy tính (Computer Vision) để hỗ trợ giáo viên quản lý lớp học trực quan, điểm danh tự động, gọi học sinh ngẫu nhiên trả bài và phát hiện các hành vi bất thường của học sinh trong thời gian thực.

---

## 🌟 Tính năng Nổi bật

*   **Nhận diện đa khuôn mặt thời gian thực**: Tự động phát hiện và nhận diện danh tính của nhiều học sinh trong khung hình từ nguồn camera/webcam.
*   **Quản lý phiên gọi ngẫu nhiên (Random Student Picker)**:
    *   Hỗ trợ giáo viên chọn ngẫu nhiên một học sinh trong danh sách những người có mặt để trả bài.
    *   Tự động lưu trạng thái đã gọi/chưa gọi trong phiên học hiện tại để tránh trùng lặp.
*   **Phát hiện hành vi bất thường**:
    *   **Ngủ gục (Sleeping)**: Phân tích chỉ số EAR (Eye Aspect Ratio) kết hợp độ nghiêng của đầu (Pitch).
    *   **Chống tay (Hand on Face)**: Phân tích khoảng cách giữa các điểm mốc bàn tay và khuôn mặt để phát hiện học sinh đang chống tay lên cằm/má.
    *   **Quay cóp (Cheating)**: Ước lượng hướng nhìn đầu (Head Pose Estimation - Yaw/Pitch/Roll) để phát hiện hành vi quay trái/phải hoặc cúi đầu nhìn bài.
    *   **Trao đổi (Talking)**: Phân tích chỉ số mở khẩu hình miệng (Mouth Aspect Ratio) biến động ở tần số nói chuyện.
*   **Giao diện Dashboard hiện đại**:
    *   Thiết kế cao cấp theo xu hướng **Glassmorphism** và **Dark Mode**.
    *   Hiển thị live stream video vẽ kèm bounding box, landmarks và các cảnh báo thời gian thực.
    *   Sidebar thống kê nhanh và quản lý danh sách học sinh.

---

## 🛠️ Công nghệ Sử dụng

*   **Ngôn ngữ**: Python 3.10+
*   **Thư viện xử lý AI & Thị giác**:
    *   **MediaPipe** (Face Mesh, Hand Landmarker) cho ước lượng tư thế đầu và phát hiện hành vi.
    *   **DeepFace** hoặc **face_recognition** cho việc trích xuất vector đặc trưng khuôn mặt (face embeddings).
    *   **OpenCV** cho các thuật toán xử lý hình học và xử lý frame hình ảnh.
*   **Framework Backend**: **FastAPI** hỗ trợ WebSockets streaming và API xử lý bất đồng bộ (async).
*   **Cơ sở Dữ liệu**: **SQLite** tích hợp cùng ORM **SQLAlchemy**.
*   **Frontend**: HTML5, Vanilla CSS (Glassmorphism), Vanilla JS (WebSockets Client).

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
│   │       └── app.js    # Logic kết nối WebSockets client và hiển thị video
│   └── templates/
│       └── index.html    # Trang giao diện chính của Giáo viên
├── docs/
│   └── implementation-plan.md # Tài liệu kế hoạch triển khai chi tiết
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

### 4. Kiểm thử tự động
```bash
pytest src/tests
black --check src
flake8 src
```

### 5. Triển khai production
Đặt ứng dụng sau reverse proxy HTTPS, sau đó bật cookie bảo mật và bắt buộc
HTTPS/WSS:
```bash
export FACE_APP_SECURE_COOKIE=true
export FACE_APP_SECURE_TRANSPORT_ONLY=true
export FACE_APP_ALLOWED_ORIGINS='https://classroom.example.com'
```

Avatar được mã hóa trên đĩa. Snapshot cảnh báo chỉ được truy cập qua API đã
xác thực và tự động được xóa cùng log cũ sau 30 ngày khi ứng dụng khởi động.

---

## 📄 Bản quyền (License)

Dự án này được phát hành dưới giấy phép **MIT License**. Chi tiết xem tại file [LICENSE](file:///Users/quocthang0507/GitHub/face-recognition/LICENSE).
