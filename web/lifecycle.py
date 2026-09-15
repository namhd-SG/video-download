"""Per-video lifecycle after `verify_video_stream` passes: upload to the
Shared Drive, delete the local copy ONLY on a confirmed successful upload,
and trip a backpressure pause when Drive keeps failing.

Why (see plans/260914-1412-tool-len-mini-va-domain/phase-03-vong-doi-file.md,
"USER CHỐT 14/09 lần 2"): the target mini's free disk swings by gigabytes in
minutes because of OTHER processes' swap, not this tool's own usage. The fix
is to never hold more than ~1 video on local disk — upload it, confirm,
delete it, immediately, per video, never batched to end-of-job.

Wired into `web/queue.py` via a direct module-level import
(`from web.lifecycle import on_video_verified`) — see
`tests/test_lifecycle.py::test_queue_wires_on_video_verified_as_the_default_lifecycle_hook`.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tiktok_music_downloader.gdrive_upload import DriveUploader, UploadOutcome, UploadResult
from tiktok_music_downloader.utils import VideoRef
from tiktok_music_downloader.watermark import find_ffmpeg
from web import models

log = logging.getLogger("videodl.web.lifecycle")

# 3 trượt liên tiếp -> tạm dừng nhận job mới. "Backpressure là phần không
# được bỏ" (phase-03 spec): không giữ local + Drive trượt = file tích lại
# im lặng cho tới khi đầy đĩa máy người khác (Promax chạy cùng máy).
FAILURE_THRESHOLD = 3

# Video trung vị đo được 0,83 MB, lớn nhất đo được 22 MB (phase-03 spec) ->
# 300MB chừa biên rất rộng cho "đỉnh đĩa ≈ một video" trong khi vẫn cảnh báo
# sớm trước khi máy khác (Promax) hết đĩa.
DEFAULT_MIN_FREE_BYTES = 300 * 1024 * 1024


class UploaderLike(Protocol):
    def upload_file(self, path: Path, parent_folder_id: str | None = None) -> UploadResult: ...
    def is_configured(self) -> bool: ...
    def create_job_folder(self, job_id: int) -> UploadResult: ...


@dataclass(frozen=True)
class BackpressureStatus:
    paused: bool
    reason: str | None
    consecutive_failures: int


@dataclass(frozen=True)
class DiskGuardStatus:
    ok: bool
    free_bytes: int
    reason: str | None = None


_state_lock = threading.Lock()
_consecutive_failures = 0
_paused_reason: str | None = None
_uploader: UploaderLike | None = None

_folder_lock = threading.Lock()
# job_id -> Drive folder file_id, created lazily on the first video verified
# for that job. In-process cache only — a worker restart re-creates a new
# folder for a job still in flight, which is an acceptable one-time cost
# next to a `files().create` per video.
_job_folders: dict[int, str] = {}


def set_uploader(uploader: UploaderLike | None) -> None:
    """Inject a custom uploader — tests use this to run the whole lifecycle
    without real Drive credentials (phase-03 constraint: "Không cần
    credential thật để test"). `None` resets to the default, which lazily
    builds a `DriveUploader` from `GDRIVE_*` env vars on next use."""
    global _uploader
    _uploader = uploader


def _get_uploader() -> UploaderLike:
    global _uploader
    if _uploader is None:
        _uploader = DriveUploader()
    return _uploader


def get_backpressure_status() -> BackpressureStatus:
    with _state_lock:
        return BackpressureStatus(
            paused=_paused_reason is not None,
            reason=_paused_reason,
            consecutive_failures=_consecutive_failures,
        )


def reset_backpressure_state() -> None:
    """Test-only reset of the module-level counters. Production code never
    calls this — the counters only move forward from real upload outcomes."""
    global _consecutive_failures, _paused_reason
    with _state_lock:
        _consecutive_failures = 0
        _paused_reason = None


def reset_job_folder_cache() -> None:
    """Test-only reset of the per-job Drive-folder cache — mirrors
    `reset_backpressure_state`. Production code never calls this."""
    with _folder_lock:
        _job_folders.clear()


def _ensure_job_folder(job_id: int, uploader: UploaderLike,
                        db_path: Path | None) -> str | None:
    """Lazily create ONE Drive folder per job, on the first video verified
    for that job, and persist its link to the DB exactly once (Bước 6: the
    user must get a link, not just a log line). Cached in memory so every
    later video for the same job reuses the folder id without another
    `files().create` round-trip.

    Returns the folder's Drive file id — pass it straight into
    `upload_file(path, parent_folder_id=...)`. Returns `None` when the
    folder could not be created (not configured, or a real API failure);
    callers must treat that as "fall back to the top-level Shared Drive
    folder", never as a reason to skip the video's own upload.
    """
    with _folder_lock:
        cached = _job_folders.get(job_id)
    if cached is not None:
        return cached

    result = uploader.create_job_folder(job_id)
    if not result.ok:
        log.warning(
            "job %s: không tạo được thư mục Drive riêng (%s: %s) — upload thẳng "
            "vào thư mục Shared Drive gốc",
            job_id, result.outcome.value, result.reason,
        )
        return None

    with _folder_lock:
        _job_folders[job_id] = result.file_id
    if db_path is not None and result.web_view_link:
        models.set_job_drive_folder_link(db_path, job_id, result.web_view_link)
    return result.file_id


def _note_upload_outcome(result: UploadResult) -> None:
    global _consecutive_failures, _paused_reason
    with _state_lock:
        if result.ok:
            # Mốc ghi SAU khi đã có một upload thành công thật — không
            # trước (guard-marker-and-claim-write-ordering.md vế 1).
            _consecutive_failures = 0
            _paused_reason = None
            return
        if result.outcome is UploadOutcome.NOT_CONFIGURED:
            # "Chưa cấu hình" KHÁC "đã cấu hình mà trượt" (guard-marker vế
            # 2: đừng gộp hai trạng thái này). Trên máy chưa cấu hình Drive,
            # MỌI upload đều NOT_CONFIGURED — đếm nó vào bộ đếm trượt sẽ
            # trip backpressure sau đúng 3 video đầu và PAUSE VĨNH VIỄN
            # (không upload nào bao giờ thành công để reset bộ đếm). Ca
            # "chưa cấu hình" có gate riêng ở `should_reject_new_job` qua
            # `is_configured()`, được đọc live mỗi lần gọi — không cần đếm.
            return
        _consecutive_failures += 1
        if _consecutive_failures >= FAILURE_THRESHOLD:
            _paused_reason = (
                f"Drive trượt {_consecutive_failures} lần liên tiếp "
                f"(gần nhất: {result.outcome.value} — {result.reason}); "
                "tạm dừng nhận job mới"
            )


def check_disk_guard(path: Path, min_free_bytes: int = DEFAULT_MIN_FREE_BYTES) -> DiskGuardStatus:
    """Read *live* free space on the volume holding `path` — never cached.

    The mini's free disk is driven by another user's swap, not by this
    tool, and has been measured to drop ~6GB in 40 minutes (phase-03 spec).
    Any cached value would already be stale within the same job.
    """
    probe = path if path.exists() else path.parent
    usage = shutil.disk_usage(probe)
    if usage.free < min_free_bytes:
        return DiskGuardStatus(
            ok=False,
            free_bytes=usage.free,
            reason=(
                f"đĩa còn {usage.free / 1_048_576:.0f} MB, dưới ngưỡng an toàn "
                f"{min_free_bytes / 1_048_576:.0f} MB"
            ),
        )
    return DiskGuardStatus(ok=True, free_bytes=usage.free)


def should_reject_new_job(*, downloads_dir: Path | None = None,
                           min_free_bytes: int = DEFAULT_MIN_FREE_BYTES) -> str | None:
    """`None` -> accept. Otherwise a human-readable reason to surface on the
    UI/API before a new job is queued.

    Three independent gates, all re-checked on every call, none cached/latched:
      0. Drive configured at all? Checked live via `is_configured()` — a
         distinct, persistent reason from gate 1's counted failures (see
         `_note_upload_outcome`'s NOT_CONFIGURED branch for why the two must
         never share one counter).
      1. Drive backpressure — tripped by 3 consecutive REAL upload failures.
      2. Live disk guard — tripped by low free space regardless of cause.
    """
    if not _get_uploader().is_configured():
        return (
            "Google Drive chưa được cấu hình trên máy này "
            "(GDRIVE_SERVICE_ACCOUNT_FILE/GDRIVE_SHARED_DRIVE_FOLDER_ID thiếu "
            "hoặc file credential không tồn tại) — job sẽ không có nơi lưu file"
        )
    status = get_backpressure_status()
    if status.paused:
        return status.reason
    if downloads_dir is not None:
        disk = check_disk_guard(downloads_dir, min_free_bytes=min_free_bytes)
        if not disk.ok:
            return disk.reason
    return None


# Grid thumbnail: one frame, one second in, 200px wide. Measured 2026-09-15 on
# a real download — 0.08s and 2 KB of webp, against 26 KB and a network round
# trip for the index's own cover image, which additionally expires in 24 hours
# (`x-expires`) and only exists for the hashtag source. Cutting locally covers
# every source and never expires.
THUMB_WIDTH = 200
THUMB_SEEK_SECONDS = 1
# Same ceiling as `verify_video_stream`'s probe: ffmpeg must never be able to
# wedge the single worker thread, and this call runs on every video.
THUMB_TIMEOUT_SECONDS = 20.0


def thumbs_dir_for(db_path: Path) -> Path:
    """`web/data/thumbs/`, derived from where the DB lives so the two always
    travel together."""
    return db_path.parent / "thumbs"


def thumb_path_for(db_path: Path, video_id: str) -> Path:
    """The thumbnail's address is computed, never stored.

    There is no `thumb_path` column on purpose: the file being on disk IS the
    fact. A column would be a second copy of that fact written in a separate
    step, and a crash in between would strand a file that no DB-driven sweep
    could ever find.
    """
    return thumbs_dir_for(db_path) / f"{video_id}.webp"


def _cut_thumbnail_quietly(path: Path, db_path: Path, video_id: str) -> bool:
    """Cut one frame out of the downloaded video. Never raises.

    "Never raises" is load-bearing, not politeness: the caller runs
    `path.unlink()` after this, and an exception escaping here would strand a
    multi-megabyte mp4 on a disk this tool does not own, with no DB row to
    find it by.

    Swallowing is acceptable here — and NOT the silent-default failure this
    repo has been bitten by — because the only consequence is a card without a
    picture, which is visible in the grid itself. Contrast `downloader.py`'s
    swallowed cookie error, which left no trace anywhere.
    """
    try:
        ffmpeg_bin = find_ffmpeg()
        if not ffmpeg_bin:
            log.warning("thumbnail %s: không tìm thấy ffmpeg — bỏ qua", video_id)
            return False
        out = thumb_path_for(db_path, video_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [ffmpeg_bin, "-y", "-loglevel", "error",
             "-ss", str(THUMB_SEEK_SECONDS), "-i", str(path),
             "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", str(out)],
            capture_output=True, text=True, timeout=THUMB_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        # Could not run the tool at all: disk full, no write permission, binary
        # killed. Says nothing about the video itself.
        log.warning("thumbnail %s: ffmpeg không chạy được (%s) — lỗi môi trường",
                    video_id, type(exc).__name__)
        return False
    except Exception as exc:  # noqa: BLE001 — see docstring; unlink must be reached
        # EVERYTHING is inside the try, including `find_ffmpeg()` and the
        # mkdir: the "never raises" contract has to hold by construction, not
        # by each call happening to sit in the right place. A test that made
        # `find_ffmpeg` throw caught exactly that gap.
        log.warning("thumbnail %s: lỗi ngoài dự kiến (%s)", video_id, type(exc).__name__)
        return False
    if result.returncode != 0:
        # ffmpeg ran and refused. `verify_video_stream` only read this file's
        # header, never decoded it, so the payload may genuinely be damaged —
        # but a non-zero code can equally mean low memory or an argument this
        # build dislikes, so this reports the symptom and does not name a cause.
        log.warning("thumbnail %s: ffmpeg rc=%s — chưa kết luận nguyên nhân",
                    video_id, result.returncode)
        return False
    return out.exists()


def _record_video_quietly(db_path: Path, job_id: int, ref: VideoRef) -> bool:
    """Index the video for the library grid. Never raises, same reason as above.

    Losing this row costs the INDEX, not the data: the video is already on
    Drive, which is the store of record, so a row can be rebuilt. Letting a DB
    error escape would instead cost the local disk, which cannot.
    """
    try:
        models.record_video(
            db_path, job_id=job_id, video_id=ref.video_id, url=ref.url,
            title=ref.title, author=ref.author, region=ref.region,
            duration=ref.duration, play_count=ref.play_count,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("job %s: không ghi được hàng videos cho %s (%s) — video VẪN ở "
                  "trên Drive, chỉ mất chỉ mục", job_id, ref.video_id, type(exc).__name__)
        return False


def on_video_verified(*, job_id: int, ref: VideoRef, path: Path,
                       db_path: Path | None = None) -> UploadResult:
    """`web/queue.py`'s `LifecycleHook` implementation.

    Called once per video, right after `verify_video_stream` passes. Upload
    to Drive; delete the local copy ONLY when that upload reports SUCCESS —
    the deletion condition is checked AFTER the fact it depends on, never
    before (phase-03 constraint 3). Any other outcome keeps the file and
    feeds the backpressure counter (constraint 4).

    Returns the `UploadResult` — the caller (`web/queue.py`'s
    `_JobProgress.note`) uses `.ok` to decide whether this video counts as
    "xong" (done). Silently returning `None` here would let the queue mark
    every verified download as done regardless of whether it ever reached
    Drive.
    """
    uploader = _get_uploader()
    parent_folder_id = _ensure_job_folder(job_id, uploader, db_path)
    result = uploader.upload_file(path, parent_folder_id=parent_folder_id)
    _note_upload_outcome(result)

    if result.ok:
        # Both calls below swallow their own failures by contract. Nothing may
        # raise between here and `path.unlink()`: this is the only window where
        # the file both exists and is known to be on Drive, and an escape would
        # leave the mp4 behind with no row to find it by.
        if db_path is not None:
            _cut_thumbnail_quietly(path, db_path, ref.video_id)
            _record_video_quietly(db_path, job_id, ref)

        try:
            path.unlink()
        except OSError as exc:
            log.error("job %s: upload %s xong nhưng xoá local trượt: %s",
                      job_id, ref.video_id, exc)
        else:
            log.info("job %s: %s lên Drive xong (driveId=%s), đã xoá local",
                      job_id, ref.video_id, result.drive_id)
        return result

    log.warning(
        "job %s: %s CHƯA lên Drive (%s: %s) — GIỮ file local",
        job_id, ref.video_id, result.outcome.value, result.reason,
    )
    return result
