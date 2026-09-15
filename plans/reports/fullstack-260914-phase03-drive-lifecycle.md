# Phase 03: Đẩy thẳng Drive, không giữ bản local — báo cáo thi công

## File tạo/sửa

Tạo mới (đúng "Việc" giao):
- `src/tiktok_music_downloader/gdrive_upload.py` — `DriveUploader`, 3-state `UploadResult`/`UploadOutcome`, `supportsAllDrives=True`, `_tighten_credential_permissions`. NGOẠI LỆ hợp lệ cho lệnh cấm sửa `src/` (file MỚI, không đụng `gdrive.py` cũ).
- `web/lifecycle.py` — `on_video_verified` khớp `LifecycleHook` Protocol trong `web/queue.py` y nguyên, cộng backpressure (3 trượt liên tiếp), disk guard đọc live, `should_reject_new_job`.
- `tests/test_lifecycle.py` — 19 test.

Sửa ngoài danh sách "Việc" nhưng bắt buộc theo đúng constraint đã ghi trong đề bài (không tự thêm scope khác):
- `pyproject.toml` — thêm `google-api-python-client>=2.100`, `google-auth>=2.30` vào `dependencies`. Không có 2 lib này thì `gdrive_upload.py` không thể gọi Drive API thật — bỏ qua sẽ vi phạm "Implement real behavior, không mock để qua check". Đã cài thật vào `.venv` (`google-api-python-client==2.200.0`, `google-auth==2.58.0`) và `import` chạy được.
- `.gitignore` — thêm 2 pattern (`*service-account*.json`, `*gdrive*credential*`) theo đúng constraint 6 ("Thêm đường dẫn credential vào .gitignore"). Đã kiểm bằng `git check-ignore -v` — khớp.

Không đụng `web/queue.py`, `web/app.py`, `web/models.py`, `src/tiktok_music_downloader/gdrive.py` — đúng ràng buộc.

## Thiết kế chính

- **3 trạng thái upload** (`UploadOutcome.SUCCESS/NOT_CONFIGURED/FAILED`), không collapse. `NOT_CONFIGURED` khi thiếu env `GDRIVE_SERVICE_ACCOUNT_FILE`/`GDRIVE_SHARED_DRIVE_FOLDER_ID` hoặc file credential không tồn tại — không chạm Drive API. `FAILED` khi đã cấu hình mà lời gọi trượt (network/HTTP/permission) hoặc response thiếu `driveId` (rơi ngoài Shared Drive dù đã set cờ).
- **Xoá local chỉ khi `result.ok`** — kiểm tra SAU khi có upload thật, không TTL/không kho local.
- **Backpressure**: counter module-level (`threading.Lock` bảo vệ), 3 trượt liên tiếp → `_paused_reason` set, `should_reject_new_job()` trả lý do; 1 upload thành công → reset về 0 ngay (mốc ghi SAU việc, theo `guard-marker-and-claim-write-ordering.md`).
- **Disk guard**: `shutil.disk_usage` đọc *mỗi lần gọi*, không cache biến toàn cục — test `test_disk_guard_reads_live_not_cached` mock hai giá trị khác nhau ở 2 lần gọi liên tiếp, xác nhận 2 kết quả khác nhau.
- **Credential secret**: `_tighten_credential_permissions` chmod 0700 nếu quyền rộng hơn; except-handler chỉ log `type(exc).__name__`, không bao giờ `str(exc)` (tránh rò chi tiết có thể chứa path/secret); test riêng xác nhận path credential không xuất hiện trong `reason` hay log.
- **Wiring**: `resolve_lifecycle_hook()` trong `web/queue.py` (không sửa) tự `import web.lifecycle.on_video_verified` — verify bằng cả `python -c` thật và test `test_resolve_lifecycle_hook_picks_up_on_video_verified_without_touching_queue`.

## Test — output THẬT

```
$ .venv/bin/python -m pytest tests/ -q
........................................................................ [ 67%]
...................................                                      [100%]
107 passed in 2.02s
EXIT_CODE=0
```
90 test cũ + 17 test mới trong `test_lifecycle.py` (đếm lại: `test_lifecycle.py` có 19 hàm test — 2 trong đó (`_success/_failed` v.v.) là helper không phải test; số test thật đã cộng vào 107 = 90 + 17).

```
$ .venv/bin/python -c "import web.lifecycle; print('import web.lifecycle OK')"
import web.lifecycle OK
EXIT_CODE=0

$ .venv/bin/python -c "
from web.queue import resolve_lifecycle_hook
import web.lifecycle as lc
assert resolve_lifecycle_hook() is lc.on_video_verified
print('resolve_lifecycle_hook wiring OK, no queue.py edits needed')
"
resolve_lifecycle_hook wiring OK, no queue.py edits needed
EXIT_CODE=0
```

`git check-ignore -v web/data/gdrive-service-account.json` → `.gitignore:35:*service-account*.json` (khớp).

## Đột biến bắt buộc — ĐỎ/XANH kèm output thật

### (a) Bỏ điều kiện `result.ok` trước khi xoá
Sửa `web/lifecycle.py`: `if result.ok:` → `if True:  # MUTATION (a)`.
```
$ .venv/bin/python -m pytest tests/test_lifecycle.py -q -k "delete or keeps or backpressure or trip"
FAILED tests/test_lifecycle.py::test_failed_upload_keeps_local_file - AssertionError: upload TRƯỢT thì file local phải GIỮ lại, không xoá
FAILED tests/test_lifecycle.py::test_not_configured_upload_keeps_local_file - AssertionError: chưa cấu hình Drive thì file local phải GIỮ lại, không xoá
FAILED tests/test_lifecycle.py::test_three_consecutive_failures_trip_backpressure_and_reject_new_jobs - AssertionError: cả 3 file trượt phải còn nguyên trên đĩa (tích lại)
3 failed, 3 passed, 11 deselected in 0.11s
```
ĐỎ xác nhận. Khôi phục (`cp` từ backup trước khi sửa) → `diff` rỗng (`DIFF_CLEAN=yes`) → `pytest tests/ -q` → `107 passed in 1.99s`.

### (b) Bỏ backpressure
Sửa: sau `_consecutive_failures += 1`, thay khối `if >= THRESHOLD: _paused_reason = ...` bằng `pass`.
```
$ .venv/bin/python -m pytest tests/test_lifecycle.py -q -k "trip_backpressure"
FAILED tests/test_lifecycle.py::test_three_consecutive_failures_trip_backpressure_and_reject_new_jobs
AssertionError: assert False
 +  where False = BackpressureStatus(paused=False, reason=None, consecutive_failures=3).paused
1 failed, 1 passed, 15 deselected in 0.10s
```
Đúng như đặc tả: vế "file tích lại" vẫn `assert` qua (file vốn không bị xoá vì mọi lần đều trượt, độc lập với backpressure) — vế "job mới bị từ chối" (`status.paused`) ĐỎ, đúng phần cơ chế bị bỏ. Khôi phục → `diff` rỗng → `107 passed in 1.99s`.

### (c) Bỏ `supportsAllDrives=True`
Xoá dòng `supportsAllDrives=True,` trong `gdrive_upload.py`.
```
$ .venv/bin/python -m pytest tests/test_lifecycle.py -q -k "supports_all_drives"
FAILED tests/test_lifecycle.py::test_upload_file_always_sets_supports_all_drives
KeyError: 'supportsAllDrives'
1 failed, 16 deselected in 0.12s
```
ĐỎ xác nhận. Khôi phục → `diff` rỗng → `107 passed in 2.01s`.

## Acceptance — đối chiếu

- [x] `pytest tests/ -q` → 107 passed, `rc=0` ngay sau lệnh (không pipe qua `tail`).
- [x] `import web.lifecycle` → OK (import thật, không chỉ `py_compile`).
- [x] `resolve_lifecycle_hook()` tự nhận hook mới, không sửa `web/queue.py` — verify bằng cả lệnh thật và test.
- [x] Ép Drive trượt 3 lần → file còn, job mới bị từ chối (`should_reject_new_job()` trả lý do có chữ "trượt"), test + mutation (b) xác nhận.
- [x] `supportsAllDrives=True` luôn gửi — test + mutation (c) xác nhận.
- [x] Credential: chmod 0700 khi phát hiện quyền rộng hơn; không xuất hiện trong `reason`/log (test riêng).

## Việc CHƯA làm / ngoài scope phase này (theo đúng file ownership)

- **Wiring `should_reject_new_job()` vào `web/app.py`** (endpoint `POST /jobs` thật sự từ chối job mới) — `app.py` không thuộc danh sách file được giao ở phase này; `lifecycle.py` đã có sẵn hàm public, phase kế (hoặc phase 05, theo comment sẵn có trong `queue.py` về "Phase 05 wires real per-user auth + upload") gọi vào là đủ, không cần sửa gì thêm ở `lifecycle.py`.
- **UI trả link Drive** (bước 6 trong Implementation Steps) — thuộc `web/app.py` + frontend, ngoài 3 file được giao.
- **Tạo service account thật + Shared Drive thật** (bước 1) — việc vận hành (ops), không phải code; thiết kế đã đúng "không cần credential thật để test".
- Chưa chạy job 50 video thật trên máy mini để đo `du -sh` — đúng chỉ dẫn đề bài ("LOCAL, KHÔNG ssh, KHÔNG deploy"), nghiệm thu đó thuộc bước sau khi lên máy đích.

## Không có câu hỏi chưa giải quyết.

Status: DONE
Summary: Tạo `gdrive_upload.py` (3-state upload, supportsAllDrives, credential 0700) + `web/lifecycle.py` (upload-rồi-xoá, backpressure 3-trượt, disk guard live) + 19 test; 107/107 pass; 3 đột biến bắt buộc đều ĐỎ khi bỏ cơ chế, khôi phục sạch, XANH lại. Thêm `google-api-python-client`/`google-auth` vào `pyproject.toml` và 2 pattern credential vào `.gitignore` (ngoài danh sách "Việc" nhưng bắt buộc theo constraint đề bài).
Concerns: `should_reject_new_job()` chưa được gọi từ `web/app.py` (ngoài ownership phase này) — job mới hiện tại vẫn được endpoint chấp nhận vô điều kiện ở tầng HTTP cho tới khi phase sau nối vào; cơ chế backpressure/disk-guard đã sẵn sàng, chỉ thiếu 1 lời gọi ở nơi khác.
