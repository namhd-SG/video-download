---
phase: 1
title: "P1 vá quyền GET /jobs/{id}, /events · P2 thư viện lọc theo chủ"
status: pending
priority: P0
effort: "2h"
dependencies: []
---

# Phase 1 — P1 + P2 (Deploy 1, không đổi schema)

## P1 — `GET /jobs/{id}` và `GET /jobs/{id}/events` chỉ cho chủ hoặc admin

**Chạm:** `web/app.py:261-266` (`get_job`), `:269-292` (`job_events`). `nguoi_tao` đã có trong chữ ký, chưa dùng (điều phối đã kiểm).

**Hình dạng:** thêm helper `_job_cua_toi_hoac_404(job_id, nguoi_tao) -> dict` — `get_job` rồi `if job is None or (not is_admin(nguoi_tao) and job["nguoi_tao"] != nguoi_tao): raise 404`. **404, không 403** — 403 là oracle "job này tồn tại và của người khác". Dùng ở cả hai route; trong `_generator` của SSE vòng lặp `get_job` giữ nguyên (đã kiểm ở cửa).

**Nghiệm thu có sức phân định** (`tests/test_web_app.py`, mẫu `test_a_user_sees_only_their_own_jobs:570`):
- A tạo job; B `GET /jobs/{id}` → **404**; A → 200; admin (env `VIDEODL_ADMIN_EMAILS=B`) → 200. Ca dương bắt buộc (A → 200) để 404 không xanh vì route luôn từ chối.
- SSE: B mở `/jobs/{id}/events` → 404 trước khi stream.
- **Đột biến phải ĐỎ:** xoá điều kiện `job["nguoi_tao"] != nguoi_tao` ⇒ test B-404 đỏ. Đây là lớp hỏng-âm-thầm (API vẫn 200, không log).

## P2 — thư viện lọc theo chủ

**Chạm:**
- `web/models.py:413-431` `list_videos(db_path, limit, offset)` → `list_videos(db_path, chi_cua: str | None, limit, offset)`. **Tham số bắt buộc, không mặc định** (luật handoff 16/09 #7: hàm quyết "ai thấy gì" không có mặc định im lặng; thiếu ⇒ `TypeError`). `None` = admin thấy hết. SQL: `LEFT JOIN jobs` giữ, thêm `WHERE (? IS NULL OR j.nguoi_tao = ?)`. Hàng mồ côi (`j.nguoi_tao IS NULL`) rơi khỏi mọi thành viên, admin thấy — ghi trong docstring.
- `web/models.py:433-435` `count_videos(db_path)` → `count_videos(db_path, chi_cua)` cùng `JOIN` cùng `WHERE`. **Bắt buộc hôm nay** vì `app.js:605-614` dùng `tong` làm điều kiện vòng nạp trang; `tong` toàn kho > số trả về ⇒ vòng nạp gọi thêm trang rỗng rồi dừng nhờ `next.videos.length === 0` — không treo, nhưng "N video" in sai.
- `web/models.py:379-393` `sources_for_videos(db_path, video_ids)` → thêm `chi_cua`: `JOIN jobs j ON j.id = s.job_id WHERE ... AND (? IS NULL OR j.nguoi_tao = ?)`. Đây là cột duy nhất trong thư viện cùng hạng với `jobs.url`: `nguon` cho search/profile là **nguyên URL** (`queue.py:95-103`, `utils.py:17`) ⇒ từ khoá người khác gõ. Hashtag của người khác cũng ẩn theo — chấp nhận (ai cần biết "tag này ai quét rồi" thì đó là việc của lọc trùng, không phải của hộp lọc).
- `web/app.py:211-234` `list_videos`: `chi_cua = None if is_admin(nguoi_tao) else nguoi_tao`, truyền vào cả ba hàm.
- `web/static/app.js:57` bỏ dòng `nguoi_tai` khỏi `FILTER_GROUPS` (hoặc `disabled: true, note: "Thư viện đã là của bạn"` theo mẫu `khung`). Xoá `creatorBucket`/`jobCreatorMap` nếu không còn ai dùng (`:66,:146-149,:558`). Docstring `/videos` (`app.py:214-216`) đổi câu "Every member sees the whole team's catalogue" thành lý do mới + ghi "Drive vẫn là MỘT kho chung".
- `tests/test_web_app.py:251` `test_videos_endpoint_returns_the_whole_team_catalogue` → **đổi tên + đổi khẳng định** thành `test_a_member_sees_only_videos_from_jobs_they_created`; đừng xoá — sửa nó là dấu vết quyết định đổi.

**Nghiệm thu:**
- Seed: job A (email a) ghi video V1, job B ghi V2, sighting của job B cho V1 (`nguon` = `https://www.tiktok.com/search?q=bi-mat`). A `GET /videos` → chỉ V1, `tong=1`, `nguon` của V1 **không chứa** `bi-mat`. B → chỉ V2. Admin → cả hai, `tong=2`, V1 có cả hai nguồn.
- Test `ORDER BY` (bàn giao ghi chưa có): 3 video `tao_luc` lệch, khẳng định thứ tự giảm dần — bỏ `ORDER BY` ⇒ đỏ.
- **Đột biến phải ĐỎ:** (i) bỏ `WHERE` trong `list_videos` ⇒ A thấy V2; (ii) bỏ `WHERE` trong `sources_for_videos` ⇒ `bi-mat` lộ; (iii) gọi `list_videos` thiếu `chi_cua` ⇒ `TypeError` (test khẳng định `inspect.signature` không có default — cùng cách `prepare_data_dir` đã làm).
- Trên mini sau deploy (offline, `127.0.0.1:7870`, không bắn TikTok): không có JWT thật để giả A/B qua HTTP ⇒ **gọi thẳng hàm đã deploy trên dữ liệu thật** như điều phối đã làm 10:33: `.venv/bin/python -c "from web import models; print(len(models.list_videos(P,'namduchoang10@gmail.com',500,0)), len(models.list_videos(P,'ai-do@x',500,0)), models.count_videos(P,None))"` → mong `10 0 10`. Số `10 0 10` là phép phân định; `healthz 200` không phải.

**Rủi ro/lui:** không đổi schema ⇒ lui = `deploy/rollback-on-mini.sh <thư-mục-truoc>`. UI cũ với API mới vẫn chạy (bớt một hộp lọc). API cũ với UI mới chạy (hộp lọc thiếu không lỗi).
