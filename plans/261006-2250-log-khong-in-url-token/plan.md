# Plan — log không in URL nguồn / thông điệp lỗi thô / token khung (ĐP-1115 duyệt hướng)

Trạng thái: **v3 — agy KHÉP R3b 23:18 (sau reviewer vòng 1); ĐP-1128 chọn (B); đã code (1627 passed, 7/7 đột biến ĐỎ).** Lane V 9b0abf0b,
worktree `~/Projects/video-download-wt-log-tai`, nhánh `fix/log-khong-in-url-token` từ origin/main `5b21567`.

## 1. Đo (log mini 57 473 dòng, từ 21/09; code 5b21567)
- `src/tiktok_music_downloader/scraper.py:642-649` `log.info("scraping %s (...)", music_url, ...)` (logger `ttmd`): 42 dòng,
  4 là URL hồ sơ `/@handle`, 16 URL nhạc. In ở đầu MỌI lượt quét (web + CLI + GUI).
- `src/tiktok_music_downloader/downloader.py:300,302` `log.warning/error("✗ %s: %s", ref.video_id, exc)`: 18 dòng, 1 có URL
  (thông điệp yt-dlp kèm URL video có thể mang `/@handle`).
- `uvicorn.access` in `GET /jobs/N/giai/khung?token=<…>`: 3 dòng — token khung giải (hiệu lực trong một lượt).
- GIỮ (ĐP-1115 b): id video + driveId ở dòng tải/upload (`lifecycle.py:724` …): driveId 1 giá trị (Shared Drive), cùng dữ liệu
  đã có trong `jobs.db` quyền chặt hơn; vận hành cần grep theo id.
- ⚠ SỬA (agy R1b, đã kiểm `queue.py:472-491`): `note_info["loi"] = str(exc)` KHÔNG vào DB — `_ghi_loi` chỉ cộng `loi`/`loi_tiktok`;
  chuỗi lỗi chỉ sống trong RAM. ⇒ dòng log `✗` là NƠI DUY NHẤT còn thông điệp lỗi; bỏ nó = mất chẩn đoán.
- Còn in `exc`/lý do thô (agy R1b liệt kê): `queue.py:487,489` (`ly_do` khi `da_log=False`), `scraper.py:279-285,296-297,687`,
  `downloader.py:228`, `lifecycle.py:239-243,671-676,721,728-731` (`result.reason`, OSError), `scraper.py:299` (DEBUG, `resp.url`).

## 2. Thiết kế
D1. `scraper.py:642`: thay `music_url` bằng `host` + `loai_nguon(url)` ∈ `profile|video|music|tag|khac`. Hàm `loai_nguon` thuần, đặt
    ở `utils.py` (cạnh `parse_video_url`). Hàm quét không có `job_id` (không truyền xuống) — KHÔNG thêm tham số; dòng log
    `job N` của queue đã có quanh lượt quét. (ĐP-1115 ghi "+ job_id": không làm được mà không đổi chữ ký ⇒ hỏi lại nếu cần.)
D2 (v2). Hàm thuần `che_url(text, toi_da=300)` ở `utils.py`: thay mọi `https?://…` bằng `<url>`, mọi `/@<handle>` bằng `/@<h>`,
    cắt độ dài. GIỮ phần chữ còn lại của thông điệp (chẩn đoán). Áp vào:
    - `downloader.py:300,302`: `"✗ %s: [%s] %s", ref.video_id, phan_loai_loi(exc), che_url(exc)`;
    - `queue.py:487,489`: `che_url(ly_do)`;
    - mọi chỗ in `exc`/`reason` thô ở §1 (cùng một hàm, đổi đối số, không đổi câu chữ/mức log).
    Hàm che áp cho CHUỖI, không cho loại đối tượng ⇒ không sót kiểu exception lạ.
    Regex (agy R2b, KHÉP 22:52): URL `(?i)(?:https?://|https?%3A%2F%2F|www\.)[^\s"']+` → `<url>`; handle
    `(?i)(?:/|%2F)(?:@|%40)[\w.\-]+` → `/@<h>`. Handle BẮT BUỘC có `/` hoặc `%2F` đứng trước (lệch R2b — bỏ `?`) để không
    che email trong log (`a@x.vn`); `@handle` trần trong Call log luôn nằm trong URL nên đã bị regex URL che.
    Kiểm chỗ lệch (ĐP-1121): `test_che_url_khong_che_email` (email `x@y.com` KHÔNG bị che; đột biến trả regex R2b gốc ⇒ ĐỎ) ·
    `test_che_url_che_call_log_playwright_that` + `test_che_url_che_dang_ma_hoa_va_khong_scheme` (Call log thật, `%2F%40` BỊ che).
D3. `web/app.py` (uvicorn 0.53.0 `h11_impl.py:477-484`: args = (client, method, path_with_query, http_version, status);
    tuple ⇒ gán lại cả tuple): `logging.Filter` gắn vào logger `uvicorn.access` (gắn trong `_lifespan`, SAU khi uvicorn dựng log config,
    cạnh `_dong_dau_thoi_gian_vao_uvicorn`) che giá trị query `token=` trong `record.args` (đường dẫn) cho MỌI route —
    đơn giản hơn chỉ `/giai/khung` và không sót route khác mang token. Không đổi dòng nào khác.
D4. Không đổi DB, API, hành vi tải/quét.

## 3. Kiểm (bắt buộc ĐỎ được)
- Test scraper: gọi đường log `scraping` với URL hồ sơ thật dạng `https://www.tiktok.com/@handle.khach?lang=vi` ⇒ caplog
  (mọi logger) KHÔNG có `http`, `/@`, `handle.khach`; CÓ `loai=profile`. `loai_nguon` cho 5 loại.
- Test downloader: ngoại lệ yt-dlp giả có thông điệp
  `ERROR: [TikTok] 7692…: No video formats found … https://www.tiktok.com/@handle.khach/video/7692…` ⇒ log có id + nhãn
  `he_thong|tiktok` + phần chữ chẩn đoán ("No video formats found"), KHÔNG `http`/`/@`/`handle.khach`; `note_info["loi"]` (RAM,
  cầu dao `requested format is not available`) vẫn là thông điệp đầy đủ ⇒ cầu dao không đổi hành vi.
- Test access log: bản ghi `uvicorn.access` giả với path `/jobs/5/giai/khung?token=abc-123&x=1` qua filter ⇒ message không có
  `abc-123`, có `token=<redacted>` và `x=1`.
- 3 đột biến (mỗi cái trả lại dòng cũ) ⇒ ĐỎ. Suite đầy đủ rc=0. Code-reviewer độc lập.

## 4. Câu hỏi mở
0. (v2) Mở rộng D2 sang toàn bộ chỗ in `exc`/`reason` thô ở §1 thay vì chỉ 2 dòng ĐP-1115 nêu — cùng nguyên tắc, cùng một hàm.
1. "+ job_id" ở dòng scraping (D1): bỏ (đề xuất) hay thêm tham số `job_id` xuống `scrape_music_page_multi`?

## 5. v3 — sửa tận gốc (ĐP-1128 chọn (B) sau code-reviewer vòng 1)
Lỗ có từ trước, reviewer bắt (đếm log mini từ 21/09):
- `web/queue.py:702` `log.exception("job %s crashed")`: traceback in `str(exc)`; `page.goto` lần 1 (`scraper.py:529`) timeout/proxy
  ⇒ Call log `navigating to "https://www.tiktok.com/@…"` lên ERROR. Đếm: `crashed` 0, `navigating to` 0 (chưa từng lộ).
- yt-dlp ghi THẲNG stderr (không có `logger` trong `_ydl_opts`; launchd gom vào cùng file). Đếm: 56 dòng `ERROR: [`, 2 có
  `tiktok.com` (chỉ host), 0 có `/@`.
- `exc_info`/`log.exception` khác: `queue.py:654,734,870,877,926,934`, `vao_bo_lap.py:79,89`.
D5. `CheUrlFormatter(logging.Formatter)`: `format()` = `super().format(record)` (đã gồm `exc_text`/traceback) rồi che bằng cùng
    hàm che (KHÔNG cắt độ dài). Gắn cho MỌI handler của root (`_dat_dinh_dang_log`) và của `uvicorn`, `uvicorn.access`,
    `uvicorn.error` (`_dong_dau_thoi_gian_vao_uvicorn`, thay `logging.Formatter` hiện có — cùng chuỗi định dạng). Test đo: sau
    khi gắn, mọi handler của 4 logger đó là `CheUrlFormatter`.
D6. yt-dlp: `_ydl_opts` thêm `"logger": log` (logger `ttmd`, propagate root ⇒ qua D5) ⇒ không ghi stderr thô.
D7. Regex sửa (ĐP-1128): URL có scheme (thường/mã hoá) che tới khoảng trắng/`"'<>(),`; dạng không scheme chỉ che khi `www.<host>/…`
    (có đường dẫn) ⇒ `host='www.tiktok.com'` GIỮ; không ăn `)` `,`. `che_url(text, toi_da=300)` giữ cho từng dòng; Formatter
    dùng bản không cắt.
D8. Không ai đọc dạng dòng `✗` ngoài repo (đo mini CHỈ ĐỌC 06/10 23:1x): crontab 0 dòng lệnh; LaunchAgents 6 plist, chỉ
    `com.astronex.videodl` nhắc `videodl.log` (đường ghi của launchd); `deploy/*.sh`, `scripts/*` không grep `✗`;
    `scripts/do-nghiem-thu-t4.sh:111` chỉ in 20 dòng cuối có dấu thời gian.
Kiểm thêm: (1) `process_job` gặp `PWTimeout` có Call log ⇒ đầu ra qua handler gắn `CheUrlFormatter` (cả traceback) không có
`/@`/`http`; đột biến Formatter trả `super().format` ⇒ ĐỎ. (2) `host='www.tiktok.com'` giữ; `(https://…), next` giữ `)` và
`, next`. (3) `_ydl_opts` có `logger`.
