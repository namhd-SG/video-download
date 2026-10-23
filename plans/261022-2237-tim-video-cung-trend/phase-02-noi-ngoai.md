# Pha 2 — Nối ngoài (agy, nguồn tìm, ảnh bìa)

Mọi I/O sau 1 hàm "đường nối" để test thay bằng giả (mẫu `hashtag_enumerator._fetch`).

## File
| File | Việc |
|---|---|
| `tim_trend/khung.py` | ffprobe thời lượng; trích 3 khung (10%/50%/90%) 360px; kiểm có tiếng; **tách hình/tiếng** (agy chỉ nhận ảnh — chặn lỗi "nghe Hindi rồi bịa chữ" GĐ1) |
| `tim_trend/agy_boc.py` | gọi `agy -p … --model gemini-3.8-flash-low --output-format json` (mẫu `creative-vision`); 1 lượt bóc trường cho lô ≤40 ảnh (khung đầu vào + ảnh bìa); 1 lượt sinh nhãn dạng + truy vấn chủ đề/sản phẩm. Nghiệm thu bằng FILE/JSON đích, không bằng mã thoát (luật agy). Thiếu mục ⇒ ảnh đó hạng `?`, không đoán |
| `tim_trend/nguon_tim.py` | `NguonTim` Protocol: `tim(truy_van) -> list[UngVien{url, video_id, cover_url, caption, tac_gia}]`. Cài: `ChromeTim` (đường thắng pha 0; đọc DOM `a[href*="/video/"]` + `img` như GĐ1) · `HashtagTim` (dùng lại `hashtag_enumerator.enumerate_hashtag`, tikwm `challenge/posts` — chỉ cho truy vấn dạng hashtag). KHÔNG có nguồn tikwm cho từ khoá (0e: `feed/search` 403 Cloudflare theo endpoint, không lách) |
| `tim_trend/anh_bia.py` | tải ảnh bìa (requests, UA trình duyệt, giãn cách); lỗi ⇒ bỏ ứng viên, ghi lý do |
| `tim_trend/nhac.py` *(tuỳ chọn, cờ `--nhan-nhac`)* | shazamio nếu có cài; chỉ ra tên bài làm thông tin, KHÔNG làm nguồn tìm (GĐ1: sound gắn "original sound" ⇒ 0/10) |

## Test
- `agy_boc`: giả `subprocess` trả JSON thật lưu từ GĐ1 (`truong-gop.json`) ⇒ parse đúng 73 mục; JSON thiếu mục ⇒ hạng `?`; agy in ra log thay vì ghi file (sự cố GĐ1) ⇒ vẫn đọc được.
- `nguon_tim`: HTML DOM giả (fixture lưu từ GĐ1) ⇒ trích đúng url/cover/caption; trang rỗng ⇒ trả rỗng + cờ "feed rỗng", không coi là xong.
- `khung`: video ngắn tổng hợp (ffmpeg `testsrc`) ⇒ 3 khung.

## Rủi ro
- agy đổi tên model/flag (đã đổi 3 lần trong 2 tháng) ⇒ model là tham số, mặc định đọc từ biến môi trường, rơi tầng theo `agy-collaboration.md`.
- Chrome cần GUI ⇒ chỉ máy dev; ghi rõ trong `--help`.
