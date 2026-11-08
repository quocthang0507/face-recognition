# Hướng dẫn triển khai

Dành cho người cài đặt Smart Classroom trên máy khác hoặc trên hosting.

## Chọn cách triển khai

| Nơi chạy | Cách dùng |
|---|---|
| VPS hoặc máy chủ có tên miền | [Docker kèm HTTPS](#docker-kèm-https) (khuyến nghị) |
| Một máy tính trong lớp, chỉ dùng trên chính máy đó | [Không dùng Docker](#không-dùng-docker) |
| Máy chủ trong trường, truy cập qua mạng nội bộ | Docker kèm HTTPS, xem [Mạng nội bộ](#mạng-nội-bộ) |

**Không dùng được** shared hosting (cPanel) hoặc nền tảng serverless. Ứng dụng cần một
tiến trình chạy liên tục, WebSocket và ổ đĩa lưu lâu dài.

**Trình duyệt chỉ cho phép mở camera qua HTTPS** hoặc khi truy cập bằng `localhost`. Mở
bằng `http://địa-chỉ-IP` thì nút bật camera sẽ không hoạt động.

## Yêu cầu

- Docker kèm Docker Compose, hoặc Python 3.12.
- Ổ đĩa trống từ 10 GB. Image Docker khoảng 5,6 GB.
- RAM nên từ 4 GB và CPU nhiều nhân. Con số này là ước lượng vì TensorFlow khá nặng,
  hãy theo dõi thực tế khi chạy.
- Tên miền trỏ về máy chủ, mở cổng 80 và 443.

## Docker kèm HTTPS

1. Lấy mã nguồn và tạo file cấu hình:

   ```bash
   git clone https://github.com/quocthang0507/face-recognition.git
   cd face-recognition
   cp .env.example .env
   ```

2. Sửa `.env`, đặt `FACE_APP_DOMAIN`, `FACE_APP_TEACHER_PASSWORD` và
   `FACE_APP_TOKEN_SECRET`. Tạo khóa ký bằng:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Server từ chối khởi động nếu vẫn dùng giá trị mặc định.

3. Khởi động. Lần đầu mất khoảng 10–15 phút để build:

   ```bash
   docker compose up -d --build
   ```

4. Mở `https://tên-miền-của-bạn`, đăng nhập bằng `admin` và mật khẩu đã đặt. Sau đó làm
   theo [hướng dẫn tài khoản, lớp học và đồng ý](accounts-classes-consent.md).

Caddy tự xin chứng chỉ HTTPS. Mật khẩu trong `.env` chỉ dùng để tạo `admin` lần đầu;
về sau hãy đổi trong hộp thoại `Quản trị`.

### Mạng nội bộ

Đặt `FACE_APP_DOMAIN` bằng tên hoặc địa chỉ IP nội bộ của máy chủ. Vì không có chứng chỉ
công khai, Caddy dùng chứng chỉ nội bộ và trình duyệt sẽ hiện cảnh báo cho đến khi máy
giáo viên tin cậy chứng chỉ gốc của Caddy.

## Không dùng Docker

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-ai.txt
python -m piper.download_voices vi_VN-vais1000-medium --download-dir models/tts
uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000` trên chính máy đó. Lần đầu tính khuôn mặt, DeepFace tự tải
trọng số Facenet (khoảng 90 MB) nên cần có Internet.

## Chuyển dữ liệu sang máy mới

Chép **toàn bộ** thư mục dữ liệu (`src/data`, hoặc volume `/data` khi dùng Docker), gồm:

- `classroom.db` và các file `classroom.db-wal`, `classroom.db-shm` đi kèm. Hãy tắt server
  trước khi chép.
- `avatars/` và `snapshots/`.
- `.avatar.key`. **Thiếu file này thì không đọc được ảnh đã mã hóa.**

Với Docker, sau khi `docker compose up -d` lần đầu:

```bash
docker compose stop app
docker compose cp ./src/data/. app:/data/
docker compose run --rm --user root --entrypoint chown app -R app /data
docker compose start app
```

Thư mục này chứa dữ liệu sinh trắc của học sinh, nên chỉ chuyển qua kênh được bảo vệ.

## Vận hành

| Việc | Lệnh |
|---|---|
| Xem log | `docker compose logs -f app` |
| Cập nhật phiên bản | `git pull` rồi `docker compose up -d --build` |
| Tắt | `docker compose down` (**không** thêm `-v`, tùy chọn đó xóa dữ liệu) |

- Khi cập nhật, CSDL tự nâng cấp và tạo bản sao `classroom.db.bak-<phiên bản>`. Bản sao
  này tự xóa sau 30 ngày.
- Hãy sao lưu định kỳ thư mục dữ liệu ra nơi khác, vì ứng dụng không tự làm việc này.
- Avatar và ảnh bằng chứng được mã hóa, nhưng vector khuôn mặt trong CSDL thì không. Hãy
  dùng ổ đĩa mã hóa trên máy chủ, và giữ `.avatar.key` tách khỏi nơi lưu bản sao nếu có thể.
- Chỉ chạy **một** tiến trình server (không dùng `--workers` lớn hơn 1), vì CSDL SQLite,
  bộ nhớ đệm và giới hạn đăng nhập nằm trong một tiến trình.

## Đã kiểm tra

Đã chạy thử trên Docker Linux với chứng chỉ nội bộ cho `localhost`: từ chối mật khẩu mặc
định, chạy bằng người dùng không phải root, dữ liệu còn nguyên khi thay container, giọng
đọc tiếng Việt, Facenet, cookie bảo mật và camera giả qua WSS. Cũng đã cài sạch từ
`requirements-ai.txt` trên Windows.

**Chưa kiểm tra:** chứng chỉ công khai trên tên miền thật, hosting thật, macOS, nhận diện
khuôn mặt người thật và tải khi nhiều lớp dùng cùng lúc.
