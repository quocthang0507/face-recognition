# Nghiệm thu Thủ công bằng Webcam

Các bước này cần webcam và người thật trước camera. Chỉ đánh dấu các mục manual
trong `check-list.md` sau khi đã quan sát kết quả thực tế.

## 1. Chuẩn bị

```bash
source venv/bin/activate
pip install -r requirements-ai.txt
export FACE_APP_TEACHER_PASSWORD='replace-this-password'
export FACE_APP_TOKEN_SECRET='replace-this-random-secret'
uvicorn src.main:app --reload
```

Mở `http://127.0.0.1:8000`, đăng nhập và bật camera.

Nếu chạy công cụ preview trên macOS, cấp quyền Camera cho Terminal hoặc IDE tại
`System Settings > Privacy & Security > Camera`. Dashboard trong trình duyệt
cũng cần được cấp quyền camera khi được hỏi.

## 2. Đăng ký và Điểm danh

1. Đăng ký ba học sinh, mỗi người dùng một ảnh webcam rõ mặt với góc nhìn hơi
   khác nhau.
2. Bắt đầu phiên học.
3. Lần lượt đưa từng học sinh vào camera trong ít nhất 8 giây.
4. Xác nhận đúng tên và trạng thái `Có mặt` cho từng học sinh.

## 3. Gọi Ngẫu nhiên

1. Bấm `Gọi ngẫu nhiên` ba lần và xác nhận không trùng tên.
2. Xác nhận lần gọi thứ tư báo đã hết học sinh chưa gọi.
3. Bấm `Reset lượt gọi`, sau đó xác nhận có thể gọi lại.

## 4. Cảnh báo Hành vi

Chạy công cụ preview để xem trực tiếp chỉ số và `track_id`:

```bash
python -m src.manual_verification
```

Trên Dashboard, bốn nút hành vi được bật mặc định và có thể bật hoặc tắt độc
lập mà không cần bắt đầu phiên điểm danh.

Thực hiện lần lượt:

| Hành vi | Thời gian giữ | Kết quả mong đợi |
| --- | ---: | --- |
| Nhắm mắt và cúi đầu | 3 giây | `Sleeping` |
| Chống tay lên má hoặc cằm | 2 giây | `Hand on face` |
| Quay đầu sang trái hoặc phải | 2 giây | `Looking away` |
| Mở khép miệng khi quay về phía người khác | 4 nhịp trong 4 giây | `Talking` |

Di chuyển nhẹ trong khung hình và xác nhận `track_id` của mỗi khuôn mặt giữ
nguyên. Nhấn `q` để kết thúc; công cụ sẽ in FPS, số khuôn mặt tối đa, danh sách
track ID và tổng cảnh báo đã phát hiện.

Để kiểm tra camera không cần mở cửa sổ preview:

```bash
python -m src.manual_verification --duration 5 --no-preview
```
