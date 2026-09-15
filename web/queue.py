"""Single-worker sequential job queue.

One Chromium per job, and this box (16GB) already runs Promax + ollama —
parallel jobs is the shortest path to OOM (measured: killed the search job
on 09-11). So exactly one background thread claims one job, runs it fully,
then looks for the next. Never two at once.
"""
from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

from tiktok_music_downloader.downloader import download_all
from tiktok_music_downloader.gdrive_upload import UploadResult
from tiktok_music_downloader.hashtag_enumerator import enumerate_hashtag
from tiktok_music_downloader.scraper import scrape_music_page
from tiktok_music_downloader.utils import VideoRef, parse_tag_slug
from tiktok_music_downloader.watermark import find_ffmpeg
from web import models
from web.lifecycle import on_video_verified

log = logging.getLogger("videodl.web")

POLL_INTERVAL_SECONDS = 1.0

# One line of ffmpeg's `-i` stderr for a real video stream looks like:
#   Stream #0:0(eng): Video: h264 (High), yuv420p, 720x1280, ...
# No ffprobe is bundled here — .gitattributes LFS-tracks only
# assets/ffmpeg-static/{ffmpeg,ffmpeg.exe} (verified in phase-01) — so
# `ffmpeg -i` is the only probe available, and its exit code is USELESS for
# this (it always exits non-zero when given no output file); the stream list
# only exists on stderr.
_VIDEO_STREAM_RE = re.compile(r"Stream.*Video:")


def verify_video_stream(path: Path, ffmpeg_bin: str | None = None,
                         timeout: float = 20.0) -> bool:
    """True iff ffmpeg reports >=1 video stream in `path`.

    This is the gate for constraint (a): a downloaded file only counts as
    "xong" (done) after this returns True. A TikTok photo/slideshow post
    yields an audio-only file that yt-dlp still reports as a successful
    download — measured 2026-09-10, 151/259 "downloads" were .mp3/.m4a. This
    function is what stops such a file from being counted as a real video.
    """
    ffmpeg_bin = ffmpeg_bin or find_ffmpeg()
    if not ffmpeg_bin or not path.exists():
        return False
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("ffmpeg -i probe on %s did not run (%s)", path, exc)
        return False
    matched_lines = [ln for ln in result.stderr.splitlines() if _VIDEO_STREAM_RE.search(ln)]
    return len(matched_lines) >= 1


class LifecycleHook(Protocol):
    """Interface `web/lifecycle.py`'s `on_video_verified` implements.

    Called once per video, right after it passes `verify_video_stream` —
    never before, and never batched to end-of-job — so it can push the file
    to Drive and delete the local copy immediately. The target disk holds
    only ~4-5GB and swings with other processes' swap, so nothing here may
    wait for the whole job to finish before cleaning up one file.

    Returns the real `UploadResult` — never `None`. `_JobProgress.note`
    below reads `.ok` off it to decide "xong" vs "loi"; a hook that always
    returned `None` would make every verified download count as done
    whether or not it actually reached Drive (see
    `~/.claude/rules/guard-marker-and-claim-write-ordering.md` vế 1: a
    "done" marker must only be written AFTER the thing it asserts is
    actually true).
    """

    def __call__(self, *, job_id: int, ref: VideoRef, path: Path,
                 db_path: Path | None = None) -> UploadResult: ...


def cookies_path_for_user(cookies_dir: Path, nguoi_tao: str) -> str | None:
    """Resolve which cookie jar belongs to this job's creator.

    Phase 05 wires real per-user auth + upload; until then this only
    guarantees the parameter travels down the right, per-user path — a real
    file at `<cookies_dir>/<sha256(nguoi_tao)>.json` when an operator has
    dropped one there by hand. No file for that user -> None (anonymous),
    never another user's cookies.

    The filename is the SHA-256 hex digest of `nguoi_tao`, not `nguoi_tao`
    itself — a hex digest never contains "/" or "." (structural, not a
    regex filter), so a path-traversal payload in `nguoi_tao` (e.g.
    "../../../etc/passwd") cannot escape `cookies_dir` no matter what value
    it carries. `web/app.py`'s `CreateJobRequest` no longer accepts
    `nguoi_tao` from the client (removed — it was the attacker-controlled
    input into this exact function), so today `nguoi_tao` is always the
    fixed "khach"; the hash stays as defense-in-depth for when Phase 05
    wires a real (still untrusted-until-verified) per-user identity through
    here.
    """
    digest = hashlib.sha256(nguoi_tao.encode("utf-8")).hexdigest()
    cookies_dir_resolved = cookies_dir.resolve()
    candidate = (cookies_dir_resolved / f"{digest}.json").resolve()
    if candidate.parent != cookies_dir_resolved:
        # Lưới thứ hai: cấu tạo digest ở trên đã chặn traversal rồi (không
        # có "/" hay ".."), đây chỉ là double-check phòng khi logic hash
        # đổi trong tương lai mà quên xét lại ràng buộc thư mục.
        log.error("cookies path traversal blocked for nguoi_tao=%r (resolved outside %s)",
                   nguoi_tao, cookies_dir_resolved)
        return None
    return str(candidate) if candidate.is_file() else None


def source_label(url: str) -> str:
    """How this job's source is named in `video_sightings`.

    Fixed now, before the first row is written: changing the shape later is a
    data migration, not an edit. `#tag` for a hashtag, the URL otherwise —
    music, search and profile pages are already distinguished by their path.
    """
    tag = parse_tag_slug(url)
    return f"#{tag}" if tag is not None else url


def _fetch_refs(url: str, max_videos: int, cookies_path: str | None,
                 proxy: str | None = None, db_path: Path | None = None,
                 job_id: int | None = None) -> list[VideoRef]:
    """Enumerate (hashtag) or scrape (music/search/profile) refs for one job.

    Videos the library already owns are dropped here, before anything is
    downloaded. That is the cheap place to do it: the expensive, rate-limited,
    account-risking step is fetching the video itself, and skipping early also
    means the hashtag is walked deeper until `max_videos` NEW ones are found
    rather than returning a short list padded with things we already have.

    Every skip is still written to `video_sightings`: a skipped video never
    reaches the download path, so this is the only moment its source for this
    run can be recorded, and the source filter reads exactly that table.

    `profile_dir` is HARDCODED to None on the scrape call below — never
    threaded in from any caller. `launch_persistent_context` (used only when
    profile_dir is set) keeps cookies on disk across runs; on a shared web
    service that would leak one user's TikTok session into the next user's
    job. See phase-02 constraint 6, and
    `test_web_queue.py::test_scraper_call_always_passes_profile_dir_none`.
    """
    nguon = source_label(url)

    def _already_have(ids: list[str]) -> set[str]:
        if db_path is None:
            return set()
        return models.known_video_ids(db_path, ids)

    def _note_skip(ref: VideoRef) -> None:
        if db_path is None or job_id is None:
            return
        try:
            models.record_sighting(db_path, video_id=ref.video_id, job_id=job_id,
                                    nguon=nguon, da_tai=False)
        except Exception as exc:  # noqa: BLE001 — a bookkeeping row must never kill a job
            log.warning("job %s: không ghi được sighting cho %s (%s)",
                        job_id, ref.video_id, type(exc).__name__)

    def _note_stop(ly_do: str) -> None:
        if db_path is None or job_id is None:
            return
        try:
            models.set_job_stop_reason(db_path, job_id, ly_do)
        except Exception as exc:  # noqa: BLE001
            log.warning("job %s: không ghi được lý do dừng (%s)", job_id, type(exc).__name__)

    tag = parse_tag_slug(url)
    if tag is not None:
        # The hashtag path filters page by page, so "go deeper until N new"
        # works; the scrapers below hand back one finished list, so they are
        # filtered once at the end.
        return enumerate_hashtag(tag, max_videos=max_videos, proxy=proxy,
                                  already_have=_already_have, on_skip=_note_skip,
                                  on_stop=_note_stop)

    refs = scrape_music_page(
        url,
        max_videos=max_videos,
        cookies_path=cookies_path,
        proxy=proxy,
        profile_dir=None,
    )
    # Every source, not just hashtags: re-running a music page today uploads a
    # SECOND copy of the same video to Drive (Drive allows duplicate names),
    # while `ON CONFLICT DO NOTHING` keeps the first row — so the second file
    # exists with nothing pointing at it.
    owned = _already_have([r.video_id for r in refs])
    kept = []
    for ref in refs:
        if ref.video_id in owned:
            _note_skip(ref)
        else:
            kept.append(ref)
    return kept


class _JobProgress:
    """Bridges `download_all`'s per-video callback into DB writes.

    `download_all` calls `.note(kind)` exactly once per ref (in ref order),
    right before `.update(1)`, for every one of "downloaded" / "skipped" /
    "failed" — but its callback protocol carries no ref/path, only the
    outcome string. We rely on call order matching `refs` order (true by
    construction: `download_all` iterates the same list we handed it) to
    know which file just finished.
    """

    def __init__(self, db_path: Path, job_id: int, refs: list[VideoRef],
                 output_dir: Path, lifecycle_hook: LifecycleHook,
                 nguon: str = ""):
        self._db_path = db_path
        self._job_id = job_id
        # Carried in rather than looked up per video: `on_video_verified` only
        # receives the job id, and re-reading the job row once per download to
        # recover its URL would be a query per file for a value that cannot
        # change during the run.
        self._nguon = nguon
        self._refs = refs
        self._output_dir = output_dir
        self._lifecycle_hook = lifecycle_hook
        self._idx = 0

    def _note_sighting(self, ref: VideoRef, *, da_tai: bool) -> None:
        """Record that this job saw this video under its source.

        Written only after the upload succeeded, so `da_tai=True` means the
        same thing the `videos` row means: this file is on Drive. Its twin —
        `da_tai=False` — is written in `_fetch_refs` for videos skipped as
        already-owned, and together the two make the source filter complete.
        """
        if not self._nguon:
            return
        try:
            models.record_sighting(self._db_path, video_id=ref.video_id,
                                    job_id=self._job_id, nguon=self._nguon, da_tai=da_tai)
        except Exception as exc:  # noqa: BLE001 — bookkeeping must not fail a job
            log.warning("job %s: không ghi được sighting cho %s (%s)",
                        self._job_id, ref.video_id, type(exc).__name__)

    def note(self, kind: str) -> None:
        ref = self._refs[self._idx]
        self._idx += 1
        if kind == "downloaded":
            path = self._output_dir / ref.filename
            # Constraint (a): the "xong" (done) mark is written ONLY after
            # this verification passes — never before, never unconditionally.
            if verify_video_stream(path):
                # The lifecycle hook (upload to Drive) runs BEFORE the
                # "xong" mark, and the mark is conditioned on its result —
                # not the other way around. Drive is the only store for
                # this file (no local retention); a video that never
                # reached Drive is not "xong" no matter how clean the
                # local download+verify was.
                result = self._lifecycle_hook(job_id=self._job_id, ref=ref, path=path,
                                               db_path=self._db_path)
                if result.ok:
                    models.increment_job_counts(self._db_path, self._job_id, xong_delta=1)
                    self._note_sighting(ref, da_tai=True)
                else:
                    log.warning(
                        "job %s: %s xác minh có luồng video nhưng lifecycle hook báo %s (%s)"
                        " — tính là lỗi, không tính là xong",
                        self._job_id, ref.filename, result.outcome.value, result.reason,
                    )
                    models.increment_job_counts(self._db_path, self._job_id, loi_delta=1)
            else:
                log.warning("job %s: %s downloaded but carries no video stream",
                            self._job_id, ref.filename)
                models.increment_job_counts(self._db_path, self._job_id, loi_delta=1)
        elif kind == "failed":
            models.increment_job_counts(self._db_path, self._job_id, loi_delta=1)
        # "skipped" = file already on disk from an earlier partial run; it was
        # never verified by *this* run, so it counts toward neither xong nor
        # loi here — `tong` already accounts for it.

    def update(self, n: int) -> None:
        # download_all's tqdm-style total-progress hook. DB writes already
        # happened granularly in note(); nothing further needed here.
        pass


def process_job(db_path: Path, downloads_dir: Path, cookies_dir: Path, job: dict,
                 lifecycle_hook: LifecycleHook | None = None) -> None:
    """Run exactly one job to completion. Never raises: one job's crash must
    not kill the worker loop, or every job behind it in the queue starves."""
    lifecycle_hook = lifecycle_hook or on_video_verified
    job_id = job["id"]
    try:
        cookies_path = cookies_path_for_user(cookies_dir, job["nguoi_tao"])
        refs = _fetch_refs(job["url"], max_videos=job["tong"], cookies_path=cookies_path,
                            db_path=db_path, job_id=job_id)
        models.set_job_total(db_path, job_id, len(refs))
        if not refs:
            models.finish_job(db_path, job_id, "done")
            return
        output_dir = downloads_dir / str(job_id)
        progress = _JobProgress(db_path, job_id, refs, output_dir, lifecycle_hook,
                                 nguon=source_label(job["url"]))
        download_all(refs, output_dir, cookies_path=cookies_path, progress=progress)
        # Mốc kết thúc ghi SAU khi đã biết kết quả thật, không vô điều kiện:
        # tong > 0 mà xong == 0 (mọi ref đều lỗi/không lên được Drive) không
        # phải là "done" dù download_all không raise.
        final = models.get_job(db_path, job_id)
        if final is not None and final["tong"] > 0 and final["xong"] == 0:
            models.finish_job(db_path, job_id, "failed")
        else:
            models.finish_job(db_path, job_id, "done")
    except Exception:  # noqa: BLE001 — isolate one job's failure from the loop
        log.exception("job %s crashed", job_id)
        models.finish_job(db_path, job_id, "failed")


class JobWorker:
    """Owns the single background thread that drains the job queue.

    Sequential by construction: `_loop` claims one job, calls `process_job`
    (which blocks until that job is fully done), then loops back to claim
    the next. There is no path that starts a second job before the first
    returns.
    """

    def __init__(self, db_path: Path, downloads_dir: Path, cookies_dir: Path,
                 poll_interval: float = POLL_INTERVAL_SECONDS,
                 process_job_fn: Callable[..., None] = process_job):
        self._db_path = db_path
        self._downloads_dir = downloads_dir
        self._cookies_dir = cookies_dir
        self._poll_interval = poll_interval
        self._process_job_fn = process_job_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Init schema, sweep crashed-mid-job rows (constraint b), then run."""
        models.init_db(self._db_path)
        interrupted = models.mark_running_as_interrupted(self._db_path)
        if interrupted:
            log.warning(
                "boot sweep: %d job(s) were 'running' at crash time -> 'interrupted'",
                interrupted,
            )
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="videodl-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = models.claim_next_pending_job(self._db_path)
            if job is None:
                time.sleep(self._poll_interval)
                continue
            self._process_job_fn(self._db_path, self._downloads_dir, self._cookies_dir, job)
