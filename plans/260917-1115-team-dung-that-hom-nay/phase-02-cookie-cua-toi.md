---
phase: 2
title: "P3 trang 'Cookie của tôi' — B1, thứ duy nhất chặn mở team"
status: pending
priority: P0
effort: "2h30-3h"
dependencies: []
---

# Phase 2 — P3 Cookie của tôi (Deploy 1, không đổi schema)

## Hình dạng

**Backend (`web/app.py`, route mới; logic mới đặt ở `web/cookies.py` cho gần `cookies_path_for_user`):**

| route | làm gì | trả |
|---|---|---|
| `GET /me` | danh tính đang đăng nhập + `la_admin` | `{"email": ..., "la_admin": bool}` — UI cần để biết mình là ai (không có chỗ nào khác) |
| `GET /me/cookie` | có jar không; nếu có: `ly_do_jar_khong_dung_duoc(path)` → `trang_thai` ∈ {`dung_duoc`} ∪ `MA_LOI_COOKIE`; `het_han` = min `expires` > 0 của cookie đăng nhập (ISO); `cap_nhat_luc` = mtime | **không một byte nào của jar** trong response — chỉ mã + thời điểm |
| `PUT /me/cookie` | body `{"json": "<chuỗi Cookie-Editor>"}`; ghi vào tệp tạm `COOKIE_TMP_DIR/<COOKIE_TMP_PREFIX>me-<sha>.json` mode 0600 → chạy `ly_do_jar_khong_dung_duoc(tmp)` → hỏng ⇒ xoá tmp, **400 kèm MÃ** (không kèm chữ nào của tệp) → dùng được ⇒ `os.replace(tmp, cookies_dir/<sha256(email)>.json)` (nguyên tử; job đang chạy đã giữ đường dẫn cũ và đã đổi sang Netscape tạm lúc bắt đầu `download_all`, không đọc dở) | như `GET` |
| `DELETE /me/cookie` | `unlink(missing_ok=True)` | 204 |

- Tên tệp tạm dùng đúng `downloader.COOKIE_TMP_PREFIX` (`downloader.py:36`) để `quet_jar_tam` (`app.py:100-118`) dọn nếu chết giữa chừng.
- Giới hạn body 256 KB (jar thật 10 196 B trên mini). `Content-Type` JSON; **không** nhận qua query/path — access log `videodl.log` là `-rw-r--r--` trên máy có user `autotest`.
- Không `log.info` gì có body; log chỉ `mã` + email? — **không cả email**: log hiện không có timestamp và bị đọc được liên user; ghi `"me/cookie: <mã>"` là đủ.
- `cookies_path_for_user` (`cookies.py:25-55`) giữ nguyên; thêm `cookie_jar_path(cookies_dir, nguoi_tao) -> Path` trả đường dẫn kể cả khi chưa có tệp (đích của `os.replace`) — cùng cấu tạo sha256 chống traversal.

**UI (`web/static/index.html`, `app.js`):** một khối "Cookie TikTok của tôi" trong `control-strip` (dưới form, `index.html:30-58`): trạng thái (chip xanh/đỏ theo `STOP_REASON_TEXT` đã có cho 4 mã), hạn, `textarea` dán, nút Lưu / Xoá, link hướng dẫn Cookie-Editor (README đã có). **Banner ẩn danh**: khi `GET /me/cookie` trả không có jar ⇒ dòng cảnh báo cạnh form tạo job: *"Chưa có cookie — lượt tải chạy ẩn danh và chia chung hạn mức 20 lượt/ngày với mọi người chưa dán. Dán cookie để có hạn mức riêng."* Không chặn nút Tạo.

## Onboarding — khuyến nghị dứt khoát: CHO chạy ẩn danh, KHÔNG chặn

Bằng chứng:
- Hashtag **không dùng cookie theo cấu tạo**: `queue.py:161-169` gọi `enumerate_hashtag(tag, max_videos, proxy, ...)` — không có `cookies_path`; `download_all` có nhận `cookies_path=None` và chạy (`downloader.py:214-221`).
- Music page: **10 video có hay không cookie** (handoff-260916 §6, đo 16/09). `/search` **0/5 kể cả có cookie** (cùng chỗ). ⇒ Hôm nay cookie không đổi kết quả ở nguồn nào đo được; chặn theo cookie là chặn bằng một biến không phân định.
- Chặn = thêm một nhánh 4xx + test + câu chữ trong ngày đã căng.
Giá phải khai với user: pool `khong-cookie` (`cookies.py:22`) **chia chung 20 job/800 trang/1000 video mỗi ngày** cho mọi người chưa dán; và video tải ẩn danh vẫn thuộc **người nhấn tải** (quyết định 1) — không liên quan cookie. Banner nói đúng số là đủ.

## Nghiệm thu (`tests/test_web_app.py` + `tests/test_web_queue.py`)

- `PUT` jar hợp lệ (fixture có `sessionid`, `expires` tương lai) ⇒ 200, tệp tồn tại ở `<cookies_dir>/<sha256(email)>.json`, `stat mode & 0o077 == 0`, và **`cookies_path_for_user(cookies_dir, email)` trả đúng tệp đó** — đây là phép nối với đường job (`queue.py:284`), không phải "tệp có trên đĩa".
- `PUT` RTF / JSON hỏng / thiếu `sessionid` / hết hạn ⇒ 400 với `detail` ∈ `MA_LOI_COOKIE`; **`cookies_dir` không có tệp mới**; `COOKIE_TMP_DIR` rỗng sau lời gọi (không sót tạm).
- Rò: `PUT` jar chứa chuỗi `SECRET-TOKEN-XYZ` ⇒ response body và `caplog` **không chứa** chuỗi đó, và ca dương của cùng phép grep: chuỗi có mặt trong tệp jar trên đĩa (control cùng điều kiện).
- `GET /me/cookie` với jar của A không đọc được bằng B: B ⇒ `co_jar=false` dù A có tệp (đường dẫn theo `sha256(email)` — test này khoá cấu tạo "không rơi sang jar người khác").
- `DELETE` ⇒ tệp mất; job A tạo sau đó chạy ẩn danh (mẫu `test_a_user_with_no_jar_downloads_anonymous_never_someone_elses`).
- **Đột biến phải ĐỎ:** (i) bỏ `os.replace` dùng ghi thẳng ⇒ test "PUT hỏng không để lại tệp" đỏ; (ii) đổi đích ghi sang tên cố định `team.json` ⇒ test B-không-thấy-jar-A đỏ; (iii) bỏ `chmod 0600` ⇒ test mode đỏ (`umask` test cố định 022).
- Trên mini (offline): sau deploy, user dán lại cookie của mình qua UI ⇒ `ls -la web/data/cookies` vẫn **đúng 1 tệp** cùng tên sha, mode `-rw-------`, mtime mới; `web/data/tmp` rỗng. Người thứ hai dán ⇒ 2 tệp. Không đọc nội dung.

## Rủi ro
- Người dán khi job của chính họ đang chạy: an toàn (đường dẫn đã giải quyết, jar Netscape tạm đã sinh). Ghi trong docstring `PUT`.
- `ly_do_jar_khong_dung_duoc` import `_load_cookies` từ `scraper` (`cookies.py:121`) — nặng (playwright import?) — kiểm một lần bằng `python -c "import web.cookies"`; nếu chậm thì đã có sẵn trên đường job, không mới.
