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
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from tiktok_music_downloader.gdrive_upload import DriveUploader, UploadOutcome, UploadResult
from tiktok_music_downloader.utils import VideoRef
from tiktok_music_downloader.watermark import find_ffmpeg
from web import models
from web.cookies import cookie_identity

log = logging.getLogger("videodl.web.lifecycle")

# 3 trượt liên tiếp -> tạm dừng nhận job mới. "Backpressure là phần không
# được bỏ" (phase-03 spec): không giữ local + Drive trượt = file tích lại
# im lặng cho tới khi đầy đĩa máy người khác (Promax chạy cùng máy).
FAILURE_THRESHOLD = 3

# Video trung vị đo được 0,83 MB, lớn nhất đo được 22 MB (phase-03 spec) ->
# 300MB chừa biên rất rộng cho "đỉnh đĩa ≈ một video" trong khi vẫn cảnh báo
# sớm trước khi máy khác (Promax) hết đĩa.
DEFAULT_MIN_FREE_BYTES = 300 * 1024 * 1024

# Jobs one cookie may start in a day. User's call 15/09: 20, counted per
# cookie, on the Vietnamese day. Not a bandwidth budget — putting the tool on
# the mini sends every member's traffic out of ONE IP, and one account running
# steadily from one IP is the shape TikTok reads as a bot farm. The thing at
# risk is the whole group of accounts behind that IP, flagged in one sweep.
#
# There is no measured usage rate behind the number: the dev jobs.db held 0
# jobs when it was chosen, so treat 20 as a starting position to revisit once
# the mini's own jobs.db has a few weeks in it, not as a tuned threshold.
MAX_JOBS_PER_COOKIE_PER_DAY = 20

# Videos one cookie may pull in a day. The job cap alone does not bound the
# traffic it exists to bound: one job may ask for up to MAX_SO_LUONG (2000),
# so 20 jobs is 40 000 videos — the exact shape the cap was meant to prevent.
#
# 1000 is 20 jobs at 50 videos each, so it does not bite a normal day's work;
# it bites the unusually large job. For scale: the downloader jitters ~2s per
# video and rests 60s every 50, so 1000 videos is roughly 70 minutes of
# continuous fetching from one account.
#
# Same caveat as the number above — chosen from the pacing constants, not from
# measured usage. Revisit once the mini's jobs.db has real weeks in it.
MAX_VIDEOS_PER_COOKIE_PER_DAY = 1000

# Trang index một cookie được đọc trong ngày. NEO vào mức hôm nay, không phải
# một con số chọn cho đẹp: trần job là 20 lượt, mỗi lượt đọc tối đa
# `max_pages=40` (hashtag_enumerator) ⇒ 20 × 40 = 800. Nên trần này KHÔNG siết
# chặt hơn hiện trạng; nó chỉ giữ nguyên hiện trạng khi ca "nguồn đã cạn" thôi
# không trừ vào trần job nữa (user chốt 16/09).
#
# Vì sao cần: một lượt quét hashtag team đã tải hết vẫn tiêu ~40 lượt gọi index
# mà `tong = 0`, tức KHÔNG tốn gì của trần video. Bỏ trần job cho ca đó mà
# không thay bằng gì thì không còn thứ nào bó lưu lượng index — và `plan.md` R6
# ghi rate-limit đánh theo IP egress, tức đánh CẢ VĂN PHÒNG chứ không riêng
# tool này.
MAX_INDEX_PAGES_PER_COOKIE_PER_DAY = 800

# The cap's day is the working day in Vietnam, not the UTC one. `tao_luc` is
# stored in UTC, so the cheap implementation — slicing its first 10 chars —
# would reset the cap at 07:00 local, cutting the working morning in half.
VN_TIMEZONE = ZoneInfo("Asia/Saigon")


def vn_day_start_utc(now: datetime | None = None) -> str:
    """Midnight in Vietnam, written the way `tao_luc` is stored.

    Returned as a UTC ISO-8601 string so it compares against `tao_luc` as
    plain TEXT, with no conversion on the SQL side.
    """
    now = now or datetime.now(timezone.utc)
    local_midnight = now.astimezone(VN_TIMEZONE).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(timezone.utc).isoformat(timespec="microseconds")


def jobs_today_for_cookie(db_path: Path, cookies_dir: Path, nguoi_tao: str,
                          now: datetime | None = None) -> int:
    """Jobs started today (Vietnam) by everyone sharing this job's cookie jar.

    Summed across creators rather than read off one row: one jar can serve
    several people once Phase 05 wires real identities, and the cap is about
    what the *account* did, not what a person did.
    """
    identity = cookie_identity(cookies_dir, nguoi_tao)
    per_creator = models.count_jobs_since_by_creator(db_path, vn_day_start_utc(now))
    return sum(count for creator, count in per_creator.items()
               if cookie_identity(cookies_dir, creator) == identity)


def pages_today_for_cookie(db_path: Path, cookies_dir: Path, nguoi_tao: str,
                           now: datetime | None = None) -> int:
    """Trang index đã đọc hôm nay (giờ VN) bởi mọi job chung jar này."""
    identity = cookie_identity(cookies_dir, nguoi_tao)
    per_creator = models.sum_pages_since_by_creator(db_path, vn_day_start_utc(now))
    return sum(count for creator, count in per_creator.items()
               if cookie_identity(cookies_dir, creator) == identity)


def videos_today_for_cookie(db_path: Path, cookies_dir: Path, nguoi_tao: str,
                            now: datetime | None = None) -> int:
    """Videos today (Vietnam) across every job sharing this job's cookie jar."""
    identity = cookie_identity(cookies_dir, nguoi_tao)
    per_creator = models.sum_videos_since_by_creator(db_path, vn_day_start_utc(now))
    return sum(count for creator, count in per_creator.items()
               if cookie_identity(cookies_dir, creator) == identity)


class UploaderLike(Protocol):
    def upload_file(self, path: Path, parent_folder_id: str | None = None) -> UploadResult: ...
    def is_configured(self) -> bool: ...
    def create_job_folder(self, job_id: int) -> UploadResult: ...
    def trash_file(self, file_id: str) -> UploadResult: ...


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


def trash_drive_file(file_id: str) -> UploadResult:
    """Đưa một tệp Drive vào thùng rác, qua đúng uploader mà đường tải đang dùng.

    Đi vòng qua `_get_uploader()` chứ không dựng `DriveUploader()` mới, để giữ
    nguyên chỗ tiêm của test (`set_uploader`): một instance thứ hai sẽ lặng lẽ
    bỏ qua uploader giả, và test hoặc đi gọi Drive thật, hoặc xanh vì lý do sai.
    """
    return _get_uploader().trash_file(file_id)


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


def daily_cap_rejection(*, db_path: Path, cookies_dir: Path, nguoi_tao: str,
                        so_luong: int,
                        max_jobs_per_day: int = MAX_JOBS_PER_COOKIE_PER_DAY,
                        max_videos_per_day: int = MAX_VIDEOS_PER_COOKIE_PER_DAY,
                        max_index_pages_per_day: int = MAX_INDEX_PAGES_PER_COOKIE_PER_DAY,
                        now: datetime | None = None) -> str | None:
    """`None` -> accept. Otherwise why this cookie is done for today.

    Deliberately NOT a gate inside `should_reject_new_job`: every gate there
    means "this machine cannot take the job right now" and answers 503. This
    one means "you may not ask for more today", which is a 429 and has a
    different remedy — wait, or use another account. Sharing the status code
    would tell the user to retry in a minute for something that clears at
    midnight.

    HAI cổng, đếm HAI thứ khác nhau — nói riêng vì một câu phủ cả hai đã sai
    một lần rồi (câu cũ ở đây: *"đếm mọi hàng job, kể cả job hỏng"*):

      * trần JOB dùng `COUNT(*)` ⇒ job liệt kê ra RỖNG **vẫn tính**. Đo
        16/09: 2 job ra rỗng = đã tiêu 2 lượt.
      * trần VIDEO dùng `SUM(tong)` ⇒ đúng 2 job đó **tính 0 video**, vì
        `process_job` ghi đè `tong` bằng số ref THẬT sau khi lọc trùng.

    Giữ như vậy có chủ đích: xin 2000 mà nhận 3 rồi bị trừ 2000 là phạt người
    dùng vì thứ họ không điều khiển được. Thứ đang được chia khẩu phần là lưu
    lượng TẢI thật.

    ⚠ HỆ QUẢ PHẢI BIẾT: **trần video KHÔNG bảo vệ lưu lượng liệt kê (index).**
    Một lượt quét hashtag đã cạn tiêu tới ~40 trang index mà `tong=0` nên
    không tốn gì của trần video. Thứ duy nhất đang bó nó là **trần JOB**:
    20 lượt × ~40 trang = ~800 lượt gọi index/ngày/cookie. Ai định cho ca
    "nguồn đã cạn" khỏi tính vào trần job thì phải thay bằng một trần khác,
    nếu không sẽ không còn gì bó — và `plan.md` R6 ghi rõ rate-limit đánh
    theo IP egress, tức đánh CẢ VĂN PHÒNG chứ không riêng tool này.

    Câu cũ đúng lúc nó được viết (khi hàm chỉ có trần job) rồi trở thành
    over-claim khi trần video được thêm vào cùng hàm mà không ai soát lại nó.
    Thêm nhánh vào một hàm thì phải soát mọi khẳng định đang đứng trên hàm đó.
    """
    used = jobs_today_for_cookie(db_path, cookies_dir, nguoi_tao, now)
    if used >= max_jobs_per_day:
        return (f"cookie này đã chạy {used}/{max_jobs_per_day} job trong hôm nay "
                "(tính theo ngày giờ VN, reset lúc nửa đêm). Trần đặt để TikTok không "
                "đọc lưu lượng của cả team từ một IP thành trang trại bot.")

    # Job count alone does not bound traffic: one job may ask for 2000 videos.
    # Checked against what this job WOULD add, not against what is already
    # spent — otherwise the last allowed job could still add 2000 on its own.
    # Trần thứ ba: lưu lượng LIỆT KÊ. Hai trần trên không bó nó (xem docstring),
    # và từ 16/09 ca "nguồn đã cạn" không còn trừ vào trần job — nên đây là thứ
    # duy nhất còn giữ số lượt gọi index.
    trang = pages_today_for_cookie(db_path, cookies_dir, nguoi_tao, now)
    if trang >= max_index_pages_per_day:
        return (f"cookie này đã đọc {trang}/{max_index_pages_per_day} trang index "
                "trong hôm nay (ngày giờ VN). Quét lại một nguồn đã cạn vẫn tốn "
                "lượt gọi TikTok dù không ra video nào.")

    spent = videos_today_for_cookie(db_path, cookies_dir, nguoi_tao, now)
    if spent + so_luong > max_videos_per_day:
        con_lai = max(max_videos_per_day - spent, 0)
        return (f"cookie này đã lấy {spent}/{max_videos_per_day} video trong hôm nay "
                f"(ngày giờ VN), nên job xin {so_luong} video sẽ vượt trần. "
                f"Còn lại hôm nay: {con_lai} video.")
    return None


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

    The per-cookie daily cap is `daily_cap_rejection`, not a gate here — see
    its docstring for why it must not share this function's status code.
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
        _bo_tep_do_dang(out, video_id)
        return False
    if not out.exists():
        # ffmpeg bảo thành công mà không có tệp ra. Nhánh này trước đây CÂM
        # hoàn toàn — `return out.exists()` trả False và không ai biết vì sao.
        log.warning("thumbnail %s: ffmpeg báo rc=0 nhưng không có tệp ra", video_id)
        return False
    if out.stat().st_size == 0:
        # Tệp 0 byte vẫn là `is_file()` với `/thumbs`, nên nó sẽ trả 200 kèm
        # thân rỗng MÃI MÃI cho video đó — và mọi lượt cắt lại dựa trên
        # `path.exists()` sẽ bỏ qua nó vĩnh viễn. Bất biến của lớp này là
        # "tệp có trên đĩa CHÍNH LÀ sự thật rằng có ảnh" (models.py:98-101);
        # một tệp rỗng phá đúng bất biến đó.
        log.warning("thumbnail %s: tệp ra rỗng 0 byte — bỏ", video_id)
        _bo_tep_do_dang(out, video_id)
        return False
    return True


def _bo_tep_do_dang(out: Path, video_id: str) -> None:
    """Dọn tệp ảnh dở. `ffmpeg -y` TẠO tệp ra trước rồi mới hỏng, nên một lượt
    cắt trượt vẫn để lại một tệp 0 byte nếu không ai dọn."""
    try:
        out.unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001 — dọn được thì tốt, không được thì thôi
        log.warning("thumbnail %s: không xoá được tệp dở (%s)", video_id, type(exc).__name__)


def _record_video_quietly(db_path: Path, job_id: int, ref: VideoRef,
                           drive_file_id: str | None = None) -> bool:
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
            music_id=ref.music_id, drive_file_id=drive_file_id,
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
            # `result.file_id` is this video's own Drive id — `result.drive_id`
            # is the Shared Drive's, identical for every file, and mixing them
            # up would make every card link to the same place.
            _record_video_quietly(db_path, job_id, ref, drive_file_id=result.file_id)

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
