# Sửa chuỗi lỗ đã thẩm định — video-download, feat/tiktok-tag-page-support

Code local, không ssh, không deploy. Mỗi bước: sửa code + test, chạy suite, mutation test cho bước có yêu cầu, rồi sang bước kế.

## Baseline

`.venv/bin/python -m pytest tests/ -q` → `107 passed`, `rc=0`.

## Bước 1 — dọn rác che mắt

- Xoá test ma `test_resolve_lifecycle_hook_is_noop_when_lifecycle_module_absent` (`tests/test_web_queue.py`).
- Đổi tên `test_resolve_lifecycle_hook_picks_up_on_video_verified_without_touching_queue` →
  `test_queue_wires_on_video_verified_as_the_default_lifecycle_hook` (`tests/test_lifecycle.py`) —
  thân bài test được cập nhật lại lần 2 ở Bước 3 khi `resolve_lifecycle_hook` bị xoá hẳn.
- `0o700` → `0o600` cho FILE credential: sửa cả assertion (`tests/test_lifecycle.py`) và code
  (`_tighten_credential_permissions` trong `src/tiktok_music_downloader/gdrive_upload.py`).

Output: `106 passed` (107 − 1 test ma).

## Bước 2 — bịt traversal

- `web/app.py`: xoá field `nguoi_tao` khỏi `CreateJobRequest`; `create_job()` tự gán `"khach"`.
  Đã grep `web/static/index.html` → 0 lần nhắc `nguoi_tao`, không vỡ UI.
- `web/queue.py::cookies_path_for_user`: tên file = `sha256(nguoi_tao).hexdigest() + ".json"`
  (chặn bằng cấu tạo, hex digest không có `/`/`.`), cộng lưới thứ hai (`resolve()` phải nằm trong
  `cookies_dir`).
- Cập nhật 3 test cookie cũ theo tên file đã hash; thêm test traversal
  (`test_cookies_path_for_user_blocks_path_traversal`,
  `test_cookies_path_for_user_traversal_never_resolves_outside_cookies_dir`); test dương
  (`test_cookies_path_for_user_resolves_existing_file`) làm control chứng minh phép kiểm phân định được.

Output: `108 passed`.

**Mutation** (`web/queue.py`, đổi `digest = hashlib.sha256(...)` → `digest = nguoi_tao`, giữ lưới
thứ hai): `test_cookies_path_for_user_resolves_existing_file` → **ĐỎ** (`AssertionError: assert
None == '.../23e36ab3...json'` — mất khớp file thật vì không còn hash); 3 test khác (đã có lưới
thứ hai độc lập chặn) vẫn xanh — cho thấy lưới thứ hai tự đứng được, và test dương phát hiện đúng
hồi quy đúng cách. Khôi phục: `diff` sạch (`diff_rc=0`), suite lại `108 passed`.

Xác nhận trực tiếp (không mutation):
```
traversal ../../../x -> None
namhd (no file) -> None
namhd (with file) -> /.../23e36ab3ceda0137ed174cfde5d746a3dff34ffb4255d1976f79f95903a08023.json
```

## Bước 3 — mốc ghi SAU việc

- `web/queue.py`: `LifecycleHook.__call__` trả `UploadResult` (không còn `None`), thêm kwarg
  `db_path: Path | None = None`. Xoá `_noop_lifecycle_hook` + `resolve_lifecycle_hook`; import thẳng
  `from web.lifecycle import on_video_verified`.
- `_JobProgress.note()`: gọi hook TRƯỚC, `increment_job_counts(xong)` chỉ khi `result.ok`, else
  `loi`.
- `process_job()`: mốc kết thúc đọc lại `models.get_job` sau `download_all` — `tong > 0 and xong ==
  0` → `"failed"`, còn lại `"done"` (trước đây `"done"` vô điều kiện).
- `web/lifecycle.py::on_video_verified`: trả `result` ở cả hai nhánh (trước đây trả `None` luôn).
- Test mới: `test_downloaded_video_with_stream_but_lifecycle_hook_fails_counts_as_error`,
  `test_process_job_marks_failed_when_every_ref_errors_without_raising`,
  `test_finish_job_is_not_called_before_download_all_completes` (đọc DB giữa `download_all` để
  đảm bảo `trang_thai` chưa phải `done`/`failed`).

Output: `111 passed`.

**Mutation 1** (hook trả về ok=True không điều kiện — dùng `_hook` trả `_UPLOAD_OK` không dựa
`result.ok`, thực chất kiểm bằng cách gọi hook trả `_UPLOAD_FAILED` cho
`test_downloaded_video_with_stream_but_lifecycle_hook_fails_counts_as_error`) — test này tự thân
đã đóng vai mutation-guard, không cần đổi code riêng.

**Mutation 2** (dời `models.finish_job(db_path, job_id, "done")` lên TRƯỚC `download_all(...)`,
xoá nhánh `tong>0 and xong==0`):
```
2 failed, 1 passed, 28 deselected
FAILED test_process_job_marks_failed_when_every_ref_errors_without_raising
  assert 'done' == 'failed'
FAILED test_finish_job_is_not_called_before_download_all_completes
  AssertionError: finish_job đã ghi mốc kết thúc TRƯỚC khi download_all xong — mốc ghi trước việc nó khẳng định
  assert 'done' not in ('done', 'failed')
```
Khôi phục: `diff_rc=0`, suite lại `111 passed`.

## Bước 4 — nối cổng chặn vào API

- `web/app.py::create_job`: gọi `should_reject_new_job(downloads_dir=DOWNLOADS_DIR)` TRƯỚC cả
  validate URL; trượt → `HTTPException(503, detail=<lý do>)`.
- File mới `tests/test_web_app.py` (venv không có `httpx`/`httpx2` nên không dùng
  `fastapi.testclient.TestClient` — gọi route function `create_job()` trực tiếp, vốn là hàm Python
  thường dưới decorator): 4 test — 503 khi gate trip, job KHÔNG được tạo khi bị chặn, thành công khi
  gate sạch, gate nhận đúng `downloads_dir=DOWNLOADS_DIR`.

Output: `115 passed`.

**Mutation** (xoá đoạn gọi gate trong `create_job`):
```
3 failed, 1 passed
FAILED test_create_job_rejects_with_503_when_gate_trips — DID NOT RAISE HTTPException
FAILED test_create_job_rejects_before_creating_a_job_row — DID NOT RAISE HTTPException
FAILED test_create_job_passes_downloads_dir_to_the_gate — captured == {}
```
Khôi phục: `diff_rc=0`, suite lại `115 passed`.

## Bước 5 — tách "chưa cấu hình" khỏi "đã cấu hình mà trượt"

- `web/lifecycle.py::_note_upload_outcome`: thêm nhánh early-return cho
  `UploadOutcome.NOT_CONFIGURED` — không tăng `_consecutive_failures`.
- `should_reject_new_job`: kiểm `_get_uploader().is_configured()` TRƯỚC hai gate cũ, trả lý do
  "chưa cấu hình" riêng.
- `tests/test_lifecycle.py`: `FakeUploader` thêm `is_configured()` (mặc định `True`) và tham số
  `configured=`. Sửa `test_should_reject_new_job_reports_disk_guard_reason` (trước dùng
  `DriveUploader()` thật không cấu hình — sẽ bị gate mới chặn sớm; đổi sang `FakeUploader([])` đã
  cấu hình để test đúng thứ nó đang kiểm: disk guard). Thêm 3 test: never-trip-backpressure,
  reason-riêng-biệt, và ca dương "đã cấu hình + trượt thật vẫn báo đúng lý do trượt, không lẫn với
  chưa cấu hình".

Output: `118 passed`.

**Mutation** (xoá nhánh `NOT_CONFIGURED` trong `_note_upload_outcome`):
```
1 failed, 5 passed
FAILED test_not_configured_outcomes_never_trip_backpressure
  BackpressureStatus(paused=True, reason='Drive trượt 5 lần liên tiếp (gần nhất: not_configured — chưa cấu hình); tạm dừng nhận job mới', consecutive_failures=5)
```
Đúng lỗi thật đã đo ("3 video đầu là pause vĩnh viễn"). Khôi phục: `diff_rc=0`, suite lại `118 passed`.

## Bước 6 — "nhận link"

- `web/models.py`: cột `drive_folder_link TEXT` trong `_SCHEMA`; `init_db()` thêm
  `ALTER TABLE jobs ADD COLUMN drive_folder_link TEXT` (bọc `except sqlite3.OperationalError`) để
  backfill DB cũ đã tồn tại trước cột này. Hàm mới `set_job_drive_folder_link(db_path, job_id,
  link)`.
- `src/tiktok_music_downloader/gdrive_upload.py`: `upload_file(path, parent_folder_id=None)` —
  override thư mục đích; `create_job_folder(job_id)` — tạo folder con trong Shared Drive gốc, tái
  dùng `UploadResult` (3 trạng thái). Rút phần dùng chung (`files().create` + kiểm `driveId`) vào
  `_create_drive_object()` để không lặp code giữa file và folder (DRY).
- `web/lifecycle.py`: cache `_job_folders: dict[job_id, folder_file_id]` (module-level, có lock),
  `_ensure_job_folder()` tạo folder MỘT LẦN cho job, lưu link vào DB qua
  `models.set_job_drive_folder_link` (chỉ khi có `db_path` VÀ tạo folder thành công), trả folder id
  cho `upload_file`. Tạo folder trượt → fallback `parent_folder_id=None` (upload thẳng root), KHÔNG
  chặn upload video. `on_video_verified` gọi `_ensure_job_folder` trước `upload_file`.
- `GET /jobs/{id}` không cần sửa — `models.get_job` trả `dict(row)` nguyên cột, `drive_folder_link`
  tự có mặt.
- Test mới: tạo folder đúng 1 lần/nhiều video cùng job, link được lưu DB, link chỉ ghi 1 lần (không
  ghi lại ở video thứ 2), fallback khi tạo folder trượt, không crash khi thiếu `db_path`. Cộng 2
  test cho `models.py` (roundtrip + backfill ALTER TABLE trên DB giả lập cũ).

Output: `125 passed`.

**Mutation** (bỏ gọi `_ensure_job_folder`, `upload_file(path)` không tham số folder):
```
3 failed, 2 passed
FAILED test_on_video_verified_creates_one_job_folder_and_reuses_it — assert [] == [42]
FAILED test_on_video_verified_persists_drive_folder_link_to_db — assert None == 'https://drive/folder-1'
FAILED test_on_video_verified_persists_folder_link_only_once_across_videos — assert [] == [1]
```
Khôi phục: `diff_rc=0`, suite lại `125 passed`.

## Bước 7 — service Drive mới mỗi call

- `src/tiktok_music_downloader/gdrive_upload.py`: `self._service` (cache service) → `self._credentials`
  (cache CHỈ credentials). `_build_service()` không còn early-return theo cache — luôn
  `build("drive", "v3", credentials=self._get_credentials(), ...)` mới. `_get_credentials()` (hàm
  mới, tách riêng) mới là chỗ cache.
- Test mới: `test_build_service_creates_a_fresh_service_object_every_call` (2 lần gọi `_build_service`
  phải trả 2 object khác nhau, cùng credentials), `test_get_credentials_is_loaded_once_and_cached_across_calls`
  (load file credential đúng 1 lần).

Output: `127 passed`.

**Mutation** (thêm lại cache `self._cached_service` trong `_build_service`):
```
1 failed, 0 passed (chạy riêng test fresh_service)
FAILED test_build_service_creates_a_fresh_service_object_every_call
  assert <object ...0x104c2a530> is not <object ...0x104c2a530>
```
Khôi phục: `diff_rc=0`, suite lại `127 passed`.

## Kết quả cuối

```
.venv/bin/python -m pytest tests/ -q
........................................................................ [ 56%]
.......................................................                  [100%]
127 passed
rc=0

.venv/bin/python -c "import web.app, web.queue, web.lifecycle; print('import OK')"
import OK
rc=0
```

Tiến trình số lượng test qua từng bước: 107 (baseline) → 106 (B1, −1 ghost) → 108 (B2, +2) →
111 (B3, +3) → 115 (B4, +4) → 118 (B5, +3) → 125 (B6, +7) → 127 (B7, +2).

## File đã sửa

- `web/app.py` — xoá `nguoi_tao` khỏi request, gọi `should_reject_new_job` trước validate.
- `web/queue.py` — hash cookie path, `LifecycleHook` trả `UploadResult`, import thẳng
  `on_video_verified`, mốc kết thúc job có điều kiện.
- `web/lifecycle.py` — `_note_upload_outcome` tách NOT_CONFIGURED, `should_reject_new_job` thêm
  gate `is_configured()`, `_ensure_job_folder` + cache folder theo job, `on_video_verified` trả
  `UploadResult` thật và dùng folder riêng.
- `web/models.py` — cột `drive_folder_link`, `set_job_drive_folder_link`, ALTER TABLE backfill.
- `src/tiktok_music_downloader/gdrive_upload.py` — `0600` cho file credential, `create_job_folder`,
  `_create_drive_object` chung, `upload_file(parent_folder_id=...)`, cache credentials thay vì
  service.
- `tests/test_web_queue.py`, `tests/test_lifecycle.py` — cập nhật/thêm test theo từng bước.
- `tests/test_web_app.py` — file mới, test wiring gate ở `POST /jobs`.

Không sửa file nào khác trong `src/tiktok_music_downloader/` ngoài `gdrive_upload.py`. Không
`git add`, không commit — để review.

## Việc chưa làm / giới hạn đã biết

- `tests/test_web_app.py` gọi `create_job()` như hàm Python thường, KHÔNG qua HTTP layer thật —
  venv này thiếu `httpx`/`httpx2` (dependency của `starlette.testclient`) nên không dùng được
  `TestClient`; không cài thêm package theo ràng buộc "code local, không tự ý thêm phụ thuộc".
  Nếu cần test qua tầng HTTP thật (middleware, JSON serialize lỗi FastAPI, status code
  Pydantic validation), cần bổ sung `httpx` vào venv trước.
- `web/lifecycle.py::_job_folders` chỉ cache trong RAM tiến trình — worker restart giữa job đang
  chạy sẽ tạo folder Drive mới cho job đó (đã ghi rõ trong docstring `_job_folders`), không phải
  bug nhưng là trade-off đã biết, chưa có cơ chế phục hồi từ `drive_folder_link` đã lưu trong DB.
- Bảng per-video (link riêng từng file) — theo đúng chỉ định "để sau, không làm bây giờ", chưa làm.
- Chưa chạy thật với credential Google Drive thật (không có trong scope "code local, không
  deploy") — mọi test Drive dùng `FakeUploader`/mock `_build_service`, đúng theo constraint
  "Không cần credential thật để test" đã có sẵn trong test suite trước khi tôi vào.

Status: DONE
Summary: Thực hiện đủ 7 bước theo đúng thứ tự, mỗi bước chạy suite + mutation test (bỏ cơ chế → ĐỎ → khôi phục → XANH, diff sạch) cho các bước có yêu cầu rõ (2,3,4) và tự nguyện mở rộng mutation cho 5,6,7 để chắc test có sức bắt lỗi thật. Suite cuối 127 passed, import OK, traversal có ca âm+dương.
Concerns: test_web_app.py gọi route function trực tiếp thay vì qua TestClient thật do thiếu httpx trong venv — xem mục "Việc chưa làm".
