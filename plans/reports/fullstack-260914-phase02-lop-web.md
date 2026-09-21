# Phase 02 — lớp web + hàng đợi — báo cáo thi công

Plan: `plans/260914-1412-tool-len-mini-va-domain/phase-02-lop-web-va-hang-doi.md`
Status: DONE

## File tạo/sửa

- Tạo `web/__init__.py`
- Tạo `web/models.py` (163 dòng) — SQLite, bảng `jobs` đúng cột spec +
  `bat_dau_luc` (started-at, thêm để đo được bất biến d bằng mốc DB thật)
- Tạo `web/queue.py` (247 dòng) — `verify_video_stream`, `LifecycleHook`
  interface + `resolve_lifecycle_hook` (no-op cho tới khi Phase 03 cài
  `web/lifecycle.py`), `cookies_path_for_user`, `_fetch_refs`, `_JobProgress`,
  `process_job`, `JobWorker`
- Tạo `web/app.py` (105 dòng) — FastAPI: `POST/GET /jobs`, `GET /jobs/{id}`,
  `GET /jobs/{id}/events` (SSE), `GET /healthz`, static mount
- Tạo `web/static/index.html` — 1 file, không build step
- Sửa `pyproject.toml` — thêm extra `[web]`: fastapi, uvicorn[standard],
  sse-starlette (đã `pip install` vào `.venv` để import/run thật được)
- Tạo `tests/test_web_queue.py` (27 test)
- KHÔNG đụng gì trong `src/tiktok_music_downloader/` — chỉ import.

## pytest — toàn bộ suite

```
$ .venv/bin/python -m pytest tests/ -q
........................................................................ [ 80%]
..................                                                       [100%]
90 passed in 2.07s
RC=0
```
63 test cũ + 27 test mới, `rc=$?` lấy ngay sau lệnh (không pipe qua `tail`).

## Import thật

```
$ .venv/bin/python -c "import web.app"; echo "import_rc=$?"
import_rc=0
```

## Uvicorn local thật + curl

```
$ .venv/bin/python -m uvicorn web.app:app --host 127.0.0.1 --port 7870 &
INFO: Application startup complete.
$ curl -sS -o - -w "\nHTTP_STATUS=%{http_code}\n" http://127.0.0.1:7870/healthz
{"status":"ok"}
HTTP_STATUS=200
$ curl -sS -w "\nHTTP_STATUS=%{http_code}\n" http://127.0.0.1:7870/           # index.html qua static mount
HTTP_STATUS=200
$ curl -sS -X POST .../jobs -d '{"url":"https://example.com","so_luong":5}'
{"detail":"url phải là trang TikTok music/tag/search/profile"}   HTTP 400
$ curl -sS -X POST .../jobs -d '{"url":"https://www.tiktok.com/music/test-123","so_luong":1,"nguoi_tao":"namhd"}'
{"id":1,...,"trang_thai":"pending",...}   HTTP 200
$ curl -sS .../jobs/1   # 3s sau
{"id":1,...,"trang_thai":"running","bat_dau_luc":"2026-09-14T08:25:48...",...}
```
Worker thread thật đã claim job và chuyển `pending → running` — hàng đợi hoạt
động end-to-end. Dừng server bằng SIGTERM: process thoát sạch sau ~5s (worker
thread đang launch Playwright unwinding), không Chromium mồ côi (`pgrep -fl
chromium` rỗng sau khi dừng). Đã xoá `web/data/` (artefact của lượt thử tay).

## 4 test đột biến — ĐỎ rồi XANH, output thật

Cách làm: sửa trực tiếp `web/queue.py`/`web/models.py` bỏ cơ chế, chạy pytest
lọc đúng test liên quan, chụp output ĐỎ, `cp` khôi phục từ backup, chạy lại
thấy XANH, `diff` xác nhận khôi phục 100% (không lệch 1 dòng).

**(a) Mốc "xong" chỉ ghi SAU xác minh luồng video** — bỏ `if
verify_video_stream(path):`, cho tăng `xong` vô điều kiện:
```
FAILED test_downloaded_video_without_stream_counts_as_error_not_done
AssertionError: file không có luồng video KHÔNG được tính là xong
assert 1 == 0
```
Khôi phục → `2 passed` (cả hai test liên quan).

**(b) Boot sweep `running`→`interrupted`** — đổi `WHERE trang_thai='running'`
thành `WHERE trang_thai='never_matches'`:
```
FAILED test_boot_sweep_marks_stale_running_jobs_interrupted
assert 0 == 1
FAILED test_worker_start_runs_boot_sweep_before_processing
AssertionError: assert 'running' == 'interrupted'
```
Khôi phục → `3 passed`.

**(c) `profile_dir=None` trong mọi lời gọi scraper** — đổi thành
`profile_dir="/tmp/should-never-be-set"`:
```
FAILED test_scraper_call_always_passes_profile_dir_none
AssertionError: assert '/tmp/should-never-be-set' is None
```
Khôi phục → `1 passed`.

**(d) Hai job chạy tuần tự, đo bằng mốc DB** — đổi `_loop` gọi job trên thread
riêng (song song) thay vì block:
```
FAILED test_two_jobs_submitted_together_run_sequentially
AssertionError: job1 xong_luc='...305241...' > job2 bat_dau_luc='...153179...'
=> hai job chồng lấp thời gian, không tuần tự
```
Khôi phục → `1 passed`.

`diff /tmp/*.bak web/*.py` sau khi khôi phục cả hai file: **rỗng** — xác nhận
không sót mutation nào trong code thật.

## Kiến trúc/quyết định đáng chú ý

- `_JobProgress.note(kind)` bám thứ tự gọi của `download_all` (note() luôn
  gọi đúng 1 lần/ref, trước update()) để suy ra ref nào vừa xong — vì
  `download_all` không truyền path/ref vào callback.
- `tong` ban đầu = `so_luong` người dùng nhập (ceiling), bị `process_job` ghi
  đè bằng số ref thật sau khi enumerate/scrape — vì đó mới là mẫu số tiến độ
  đúng. Ghi rõ trong docstring `create_job`.
- Thêm cột `bat_dau_luc` ngoài schema liệt trong spec — cần để **đo được**
  bất biến (d) bằng dữ liệu DB thật, không chỉ suy luận từ code.
- `verify_video_stream`: dùng `ffmpeg -i` (không ffprobe, đúng chốt phase-01),
  đếm dòng khớp `Stream.*Video:` trong stderr, bỏ qua exit code. Có test
  integration thật với binary `assets/ffmpeg-static/ffmpeg` (không mock) sinh
  1 clip test + 1 audio-only bằng `lavfi`.
- Lifecycle hook: `Protocol` + `resolve_lifecycle_hook()` thử `from
  web.lifecycle import on_video_verified`, `ImportError` → no-op. Phase 03 chỉ
  cần thêm file, không sửa `web/queue.py`.
- `cookies_path_for_user`: tra `<cookies_dir>/<nguoi_tao>.json`, không có file
  → `None` (ẩn danh), không bao giờ trả cookie của người khác.
- SQLite: mỗi lời gọi models.* mở/đóng connection riêng (không giữ RAM),
  `PRAGMA journal_mode=WAL`, `claim_next_pending_job` dùng `BEGIN IMMEDIATE`
  để atomic (an toàn nếu sau này có >1 worker, hiện tại chỉ 1).
- Bind `127.0.0.1` cứng trong `web/app.py`, cổng 7870 (đã đo trống ở phase-02).

## Việc CHƯA làm (ngoài phạm vi phase-02, thuộc phase khác)

- `com.astronex.videodl.plist` trỏ vào uvicorn, `launchctl load` — thuộc bước
  6-7 của phase-02 gốc nhưng là việc **trên mini**, không làm trên máy dev này
  (chỉ thi công local theo đúng chỉ định "KHÔNG ssh, KHÔNG deploy" của task).
- `web/lifecycle.py` thật (upload Drive) — Phase 03, cố ý không đụng.
- Auth/per-user thật — Phase 05; `nguoi_tao` hiện nhận qua field JSON, default
  `"khach"`.

## Unresolved

- Chưa rõ path SSE final có cần khác `/jobs/{id}/events` không (spec chỉ nói
  "SSE đẩy tiến độ", không định danh path) — đã chọn path này, ghi trong
  index.html; đổi tên dễ nếu cần.

Status: DONE
Summary: web/{models,queue,app}.py + static/index.html dựng xong hàng đợi tuần tự SQLite-backed; 90/90 test xanh, cả 4 bất biến a-d đã tự tay bỏ cơ chế chứng minh ĐỎ rồi khôi phục XANH (diff rỗng); uvicorn local thật + curl healthz 200 + tạo job qua HTTP thật chuyển pending→running.
Concerns: chưa nghiệm thu trên mini thật (đúng phạm vi task — chỉ local); SSE endpoint path là quyết định của tôi, chưa được user chốt tên.
