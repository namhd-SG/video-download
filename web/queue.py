"""Single-worker sequential job queue.

One Chromium per job, and this box (16GB) already runs Promax + ollama —
parallel jobs is the shortest path to OOM (measured: killed the search job
on 09-11). So exactly one background thread claims one job, runs it fully,
then looks for the next. Never two at once.
"""
from __future__ import annotations

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
from tiktok_music_downloader.scraper import scrape_music_page_multi
from dataclasses import replace

from tiktok_music_downloader.utils import VideoRef, parse_tag_slug
from tiktok_music_downloader.watermark import find_ffmpeg
from web import models
# Re-exported: `cookies_path_for_user` moved to `web/cookies.py` so
# `web/lifecycle.py` can reach it too without importing this module back.
# Callers (and its tests) still reach it as `queue.cookies_path_for_user`.
from web.cookies import cookies_path_for_user  # noqa: F401
from web.cookies import ly_do_jar_khong_dung_duoc
from web.lifecycle import on_video_verified

log = logging.getLogger("videodl.web")

POLL_INTERVAL_SECONDS = 1.0

# Trần cho một lượt ĐÀO SÂU trên nhánh music/search/profile — USER CHỐT 21/09
# qua `AskUserQuestion`, không phải số chọn tay.
#
# 10 phút: mỗi lượt quét lại phải nghỉ 60-180s (jitter) để không thành một nhịp
# TikTok nhận ra, nên 10 phút là chỗ cho khoảng 4 lượt. Hụt thì job dừng với mã
# `het_thoi_gian` — ca này khuyên CHẠY LẠI, khác hẳn `already_owned`.
# 5 vòng: giữ nguyên trần cứng vốn có trong `scrape_music_page_multi`, đã chạy
# thật trong bản desktop. Cái nào chạm trước thì dừng.
#
# ⚠ Hai số này CHƯA có nền đo từ phía TikTok — chưa ai biết TikTok chặn ở
# ngưỡng nào. Chúng là lựa chọn của người dùng với đánh đổi đã bày ra, không
# phải kết quả hiệu chỉnh. Đổi chúng thì phải hỏi lại người dùng.
TRAN_GIAY_MOT_LUOT = 600.0

# Tạm ĐẶT VỀ 1 — USER CHỐT 22/09 qua `AskUserQuestion`. Một lượt nghĩa là không
# đào sâu, tức xấp xỉ hành vi trước khi có tính năng này: mã đào sâu lên máy thật
# nhưng nằm im, nên chuyến deploy này không mang rủi ro TikTok chặn.
#
# Lý do đặt ở đây thay vì gỡ commit: hai commit trên nhánh trộn lẫn hai vấn đề
# trong cùng một thay đổi (vá hạn mức đụng scraper, vá cửa sổ quét đụng trang Cài
# đặt), nên mổ tay ra sẽ tạo một tổ hợp chưa ai chạy.
#
# Mở lại = đổi số này về 5 rồi deploy. Chỉ làm thế khi đã sẵn sàng đo lượt chạy
# thật đầu tiên, vì đó là lúc duy nhất lấy được ba số còn thiếu: một job ăn bao
# nhiêu trang, số lượt đã cào thật kèm lý do dừng, và TikTok có chặn hay không.
SO_VONG_DAO_SAU = 1

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

    # Đếm video bỏ qua vì thư viện đã có. Ghi TĂNG DẦN mỗi lần bỏ, cùng lý do
    # với `_dem_mot_trang` bên dưới: job bị huỷ hay chết giữa chừng vẫn đã bỏ
    # qua thật, và người dùng cần con số đó để hiểu vì sao nhận ít video hơn
    # số mình xin. Ghi một lần lúc xong thì ca chết giữa chừng mất con số.
    _da_bo = {"so": 0}

    def _note_skip(ref: VideoRef) -> None:
        if db_path is None or job_id is None:
            return
        _da_bo["so"] += 1
        try:
            models.record_sighting(db_path, video_id=ref.video_id, job_id=job_id,
                                    nguon=nguon, da_tai=False)
        except Exception as exc:  # noqa: BLE001 — a bookkeeping row must never kill a job
            log.warning("job %s: không ghi được sighting cho %s (%s)",
                        job_id, ref.video_id, type(exc).__name__)
        # `try` riêng: mất con số này thì lời giải thích hụt, nhưng không được
        # làm hỏng một lượt tải đang chạy. Và nó phải nằm NGOÀI `try` ở trên —
        # gộp vào thì một sighting trượt sẽ nuốt luôn bộ đếm.
        try:
            models.set_job_skipped(db_path, job_id, _da_bo["so"])
        except Exception:  # noqa: BLE001
            log.warning("job %s: không ghi được số video bỏ qua", job_id)

    def _note_pages(so_trang: int) -> None:
        """Ghi số trang index đã đọc. Trong `try` riêng: mất con số này thì
        trần liệt kê hụt, nhưng không được làm hỏng một lượt tải đã chạy xong.

        Cửa `db_path is None` giống hệt `_note_skip`/`_note_stop` ở trên, và
        nó KHÔNG thừa: không có DB (đường CLI/GUI, và test) thì đây là "chưa
        cấu hình", không phải "đã cấu hình mà trượt". Hai ca đó mà trả cùng
        một dòng cảnh báo thì cảnh báo mất hết giá trị — và từ 21/09 hàm này
        chạy MỖI LỜI GỌI FEED chứ không còn một lần cuối job, nên ca đầu đẻ
        ra hàng chục dòng rác che đúng ca thứ hai. Đo được: 3 lời gọi feed
        không DB ⇒ 3 dòng `job None: không ghi được số trang index`.
        (`guard-marker-and-claim-write-ordering.md` vế 2.)
        """
        if db_path is None or job_id is None:
            return
        try:
            models.set_job_pages(db_path, job_id, so_trang)
        except Exception:  # noqa: BLE001
            log.warning("job %s: không ghi được số trang index", job_id)

    # Bộ đếm trang cho nhánh music/search/profile, ghi TĂNG DẦN chứ không phải
    # một lần lúc xong.
    #
    # Vì sao không gộp vào `_note_pages`: nhánh hashtag báo tổng MỘT LẦN ở cuối
    # (`hashtag_enumerator.py`), và đó là một lỗ đo được 21/09 — job bị huỷ hay
    # chết giữa chừng đã tiêu request thật với TikTok nhưng sổ ghi 0, còn job
    # đang chạy thì chưa ghi gì nên job xếp hàng kế tiếp được duyệt trên sổ cũ
    # (`app.py` kiểm trần lúc TẠO job, đọc `SUM(so_trang)` đã commit). Bản vá
    # đào sâu kéo một job từ ~1 phút lên tới 10 phút, tức nó LÀM CỬA SỔ ĐÓ RỘNG
    # RA — nên nhánh mới không được thừa kế cách ghi cũ.
    #
    # `guard-marker-and-claim-write-ordering.md` vế 3: mốc "đã tiêu" và mốc
    # "đã xong" là hai mốc khác nhau. Cái đầu phải ghi ngay khi tiêu.
    _da_doc = {"trang": 0}

    def _dem_mot_trang() -> None:
        _da_doc["trang"] += 1
        _note_pages(_da_doc["trang"])

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
                                  on_stop=_note_stop,
                                  on_pages=_note_pages)

    # Đào sâu tới khi đủ `max_videos` video MỚI — không còn "lấy một danh sách
    # rồi lọc một lần ở cuối".
    #
    # `scrape_music_page_multi` đã tồn tại từ lâu và GUI desktop đã dùng nó cho
    # đúng ba loại trang này; chỉ đường web là gọi bản một lượt. Nên đây là NỐI
    # lại thứ đã chạy thật, không phải viết mới một cơ chế phân trang — và nhờ
    # vậy giữ nguyên phần chống chặn đã đo: đóng hẳn context giữa các lượt,
    # nghỉ jitter 60-180s, dừng khi độ mới tụt, dừng khi nghi bị chặn mềm.
    refs = scrape_music_page_multi(
        url,
        passes=SO_VONG_DAO_SAU,
        max_videos=max_videos,
        max_seconds=TRAN_GIAY_MOT_LUOT,
        already_have=_already_have,
        on_skip=_note_skip,
        on_stop=_note_stop,
        cookies_path=cookies_path,
        proxy=proxy,
        profile_dir=None,
        dem_trang=_dem_mot_trang,
    )
    # Lọc trùng và lý do dừng giờ nằm TRONG `scrape_music_page_multi`: nó phải
    # biết "video này thư viện đã có" ngay giữa các lượt để quyết định đào tiếp
    # hay dừng. Lọc một lần ở ngoài, sau khi quét xong, chính là cái không bù
    # được số hụt — và `on_skip` chạy trong đó nên video bị bỏ vẫn để lại dấu
    # nguồn của lượt này, đúng như trước.
    #
    # `on_stop` cũng do nó gọi, với BỐN ca phân biệt được thay vì hai:
    #   · `source_empty`     nguồn không đưa ra gì  ⇒ link có thể sai/hết hạn
    #   · `already_owned`    mình đã có hết         ⇒ ĐỔI NGUỒN, chạy lại vô ích
    #   · `het_thoi_gian` / `het_vong`              ⇒ chạy lại CÓ THỂ ra thêm
    #   · `nghi_bi_chan`     đang trả rồi ngừng     ⇒ NGHỈ rồi hãy chạy lại
    # Ba nhóm đó bảo người dùng ba việc khác nhau; gộp lại là quay về "một dòng
    # chữ lặng lẽ" — thứ đã khiến người dùng hỏi "có lỗi không, sao hai link
    # khác nhau lại ra giống nhau".
    return refs


def _bo_sung_metadata(ref: VideoRef, info: dict | None) -> VideoRef:
    """Điền metadata yt-dlp đọc được vào những ô mà nguồn liệt kê bỏ trống.

    Chỉ điền ô đang `None`, không đè: index của trang hashtag là nguồn chính
    xác hơn cho `region` và `title` (nó nói về video trong ngữ cảnh TikTok),
    còn yt-dlp nói về tệp nó vừa tải. Ô nào index đã có thì giữ.

    Đây là thứ chữa "(chưa có tiêu đề)" cho music page và profile — hai nguồn
    mà scraper chỉ dựng được `VideoRef(video_id, url)` trần.
    """
    if not info:
        return ref
    def _so(x):
        try:
            return int(x) if x is not None else None
        except (TypeError, ValueError):
            return None
    thay = {}
    if ref.title is None:
        # yt-dlp đặt mô tả TikTok vào `title`; `description` là bản dài hơn của
        # cùng một thứ, dùng làm đường lui.
        thay["title"] = info.get("title") or info.get("description") or None
    if ref.author is None:
        thay["author"] = info.get("uploader") or info.get("uploader_id") or None
    if ref.duration is None:
        thay["duration"] = _so(info.get("duration"))
    if ref.play_count is None:
        thay["play_count"] = _so(info.get("view_count"))
    return replace(ref, **{k: v for k, v in thay.items() if v is not None})


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

    def note(self, kind: str, info: dict | None = None) -> None:
        ref = self._refs[self._idx]
        self._idx += 1
        ref = _bo_sung_metadata(ref, info)
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
        # TIỀN-KIỂM: jar có mà hỏng/hết hạn thì DỪNG, không chạy tiếp không
        # cookie. `download_all` nuốt lỗi cookie thành một dòng log rồi chạy
        # ẩn danh — với dòng lệnh đó là tiện, với lớp web dùng chung thì job
        # vẫn báo "xong" mà ra ít video hơn hẳn và không ai biết vì sao.
        # Không có jar thì KHÔNG phải lỗi: đó là chạy ẩn danh có chủ đích.
        if cookies_path is not None:
            ly_do = ly_do_jar_khong_dung_duoc(cookies_path)
            if ly_do is not None:
                models.set_job_stop_reason(db_path, job_id, ly_do)
                models.finish_job(db_path, job_id, "failed")
                return
        refs = _fetch_refs(job["url"], max_videos=job["tong"], cookies_path=cookies_path,
                            db_path=db_path, job_id=job_id)
        models.set_job_found(db_path, job_id, len(refs))
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
