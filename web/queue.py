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
from tiktok_music_downloader.phan_loai_loi import LOI_KHONG_CO_LUONG_VIDEO, phan_loai_loi
from tiktok_music_downloader.scraper import scrape_music_page_multi
from dataclasses import replace

from tiktok_music_downloader.utils import (
    STOP_FEED_RONG, STOP_HASHTAG_KHONG_TRA_DUOC, STOP_INDEX_FAILED, STOP_NGHI_BI_CHAN,
    STOP_SOURCE_EMPTY, VideoRef, parse_tag_slug,
)
from tiktok_music_downloader.watermark import find_ffmpeg
from web import models
# Re-exported: `cookies_path_for_user` moved to `web/cookies.py` so
# `web/lifecycle.py` can reach it too without importing this module back.
# Callers (and its tests) still reach it as `queue.cookies_path_for_user`.
from web.cookies import cookies_path_for_user  # noqa: F401
from web.cookies import ly_do_jar_khong_dung_duoc
from web.lifecycle import check_disk_guard, on_video_verified

log = logging.getLogger("videodl.web")

POLL_INTERVAL_SECONDS = 1.0

# Lý do dừng mà một lượt RỖNG (0 video) phải ghi "Lỗi", không phải "Xong": tất cả
# đều là "không lấy được gì" chứ không phải "đã làm xong" — kể cả hai ca hashtag
# lỗi ngay đầu (nguồn liệt kê hỏng, không tra được mã hashtag). `already_owned`
# không nằm đây — thư viện đã có hết những gì nguồn đưa ra là xong thật.
_LY_DO_RONG_LA_LOI = frozenset({
    STOP_FEED_RONG, STOP_SOURCE_EMPTY, STOP_NGHI_BI_CHAN,
    STOP_INDEX_FAILED, STOP_HASHTAG_KHONG_TRA_DUOC,
})
# Trần nghỉ giữa hai vòng worker khi lỗi LẶP (nghỉ lùi dần: poll, 2×poll, 4×poll…).
# Đủ dài để không ghi log dồn dập khi DB/đĩa hỏng kéo dài, đủ ngắn để tự chạy lại
# trong vòng một phút sau khi hết lỗi.
TRAN_NGHI_LOI_GIAY = 60.0
# Chờ đĩa kéo dài: nhắc lại một dòng log mỗi chừng này giây (không phải mỗi vòng — lý do
# mang số MB đổi từng giây và log dồn lên chính cái đĩa đang dưới ngưỡng; cũng không
# phải chỉ một lần — chờ nhiều ngày mà log chỉ còn một dòng đầu là im lặng).
NHAC_CHO_DIA_GIAY = 600.0

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

# Cầu dao "hỏng hàng loạt": nhiều video CÙNG báo `Requested format is not
# available` trong một job là dấu hiệu của sự cố chung (yt-dlp/TikTok đổi gì đó),
# không phải từng video hỏng. Chỉ đếm ĐÚNG chuỗi này — cố ý KHÔNG đếm bài ảnh
# ("carries no video stream": 58% ở một nguồn ngày 10/09, bình thường) và các mẫu
# TikTok khác.
#
# ⚠ HAI SỐ NÀY CHƯA HIỆU CHỈNH. Nền đo được 29/09: tối đa 1 lỗi/job, tổng 2 lỗi
# trên ~960 video. Chúng là ngưỡng thiết kế đã thoả thuận (agy caudaotiktok-R1b),
# không phải kết quả đo — chỉnh khi có số liệu thật.
#   trip khi: ≥ CAU_DAO_SO_LIEN_TIEP lỗi LIÊN TIẾP,
#         hoặc: tổng ≥ CAU_DAO_SO_LIEN_TIEP VÀ tổng > CAU_DAO_TI_LE × số video đã thử.
CAU_DAO_MAU_LOI = "requested format is not available"
CAU_DAO_SO_LIEN_TIEP = 5
CAU_DAO_TI_LE = 0.30

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
                 job_id: int | None = None,
                 ly_do_ra: dict | None = None) -> list[VideoRef]:
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

    `ly_do_ra`, khi được truyền, nhận lý do dừng (`ly_do_ra["ly_do"]`) NGAY trong
    bộ nhớ. `process_job` quyết "Xong" hay "Lỗi" cho lượt rỗng từ chính giá trị
    này chứ không đọc lại `ly_do_dung` trong DB: `_note_stop` nuốt lỗi ghi DB
    (một lần ghi trượt không được giết lượt tải), nên đọc lại từ DB thì một lần
    trượt sẽ âm thầm đưa lượt rỗng về lại nhãn "Xong" giả.
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
        if ly_do_ra is not None:
            ly_do_ra["ly_do"] = ly_do
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
    # Ba ô dưới chỉ yt-dlp có (không nguồn liệt kê nào trả), nên luôn lấy từ
    # `info`. `description` là caption ĐẦY ĐỦ — `title` của trang liệt kê bị
    # cắt ~70 ký tự (đo 24/09: 72 vs 1402 ký tự cho cùng một video).
    thay["description"] = _cat_tran(info.get("description"), DESCRIPTION_TOI_DA)
    thay["track"] = _cat_tran(info.get("track"), NHAC_TOI_DA)
    thay["artist"] = _cat_tran(info.get("artist"), NHAC_TOI_DA)
    return replace(ref, **{k: v for k, v in thay.items() if v is not None})


# Trần độ dài khi LƯU, không phải khi hiển thị. 4000 = trần caption TikTok
# (chưa tra lại tại nguồn TikTok; lớn nhất đo được ở lượt thật 24/09 là 1402).
# Vượt trần thì cắt và ghi log — một caption dài bất thường là thứ nên thấy,
# không phải thứ nên nuốt.
DESCRIPTION_TOI_DA = 4000
NHAC_TOI_DA = 200


def _cat_tran(gia_tri, toi_da: int) -> str | None:
    """Chuỗi đã `strip`, cắt ở `toi_da` ký tự; rỗng/không phải chuỗi ⇒ None."""
    if not isinstance(gia_tri, str):
        return None
    s = gia_tri.strip()
    if not s:
        return None
    if len(s) > toi_da:
        log.info("metadata dài %d ký tự, cắt còn %d", len(s), toi_da)
        return s[:toi_da]
    return s


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
        # Cầu dao hỏng hàng loạt (theo TỪNG job — object này sống một job).
        self._rf_tong = 0        # số lỗi `Requested format` đã thấy
        self._rf_lien_tiep = 0   # chuỗi lỗi đó liên tiếp, về 0 khi gặp video khác
        self._da_thu = 0         # số video đã thử tải (không tính video bỏ qua)
        self._da_bao = False     # mốc "đã báo ERROR" — TÁCH khỏi bộ đếm
        self._da_luu = False     # mốc "đã ghi cờ vào DB"

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

    def _ghi_loi(self, ref: VideoRef, ly_do: object, *, loai: str | None = None,
                 da_log: bool = False) -> None:
        """Đếm một video lỗi: `loi` luôn +1, `loi_tiktok` +1 khi TikTok không
        cho tải. `loai=None` ⇒ tự phân loại theo `ly_do`; truyền `"he_thong"`
        để ép (lỗi Drive không bao giờ được xếp vào phía TikTok).

        Lỗi phía TikTok chỉ WARNING — ERROR dành cho lỗi hệ thống thật.
        `da_log=True` khi thư viện `downloader.py` đã log đúng mức cho lỗi tải
        này, để không ghi thêm một dòng trùng.
        """
        loai = loai or phan_loai_loi(ly_do)
        la_tiktok = loai == "tiktok"
        if da_log:
            pass
        elif la_tiktok:
            log.warning("job %s: video %s lỗi phía TikTok (%s)", self._job_id, ref.video_id, ly_do)
        else:
            log.error("job %s: video %s lỗi hệ thống (%s)", self._job_id, ref.video_id, ly_do)
        models.increment_job_counts(self._db_path, self._job_id, loi_delta=1,
                                    loi_tiktok_delta=1 if la_tiktok else 0)

    def _theo_doi_hang_loat(self, la_rf: bool) -> None:
        """Cập nhật bộ đếm cầu dao sau MỘT video đã thử, rồi phán.

        ERROR ĐÚNG MỘT lần mỗi job: mốc `_da_bao` là một biến riêng, không suy
        ra từ bộ đếm (bộ đếm còn tăng sau ngưỡng). Cờ DB có mốc riêng `_da_luu`
        chỉ đặt SAU khi ghi thành công, và là CHỐT: đã báo mà chưa lưu được thì
        MỌI video sau đó đều thử lưu lại, không phụ thuộc điều kiện còn đúng hay
        không (chuỗi đã đứt, tỉ lệ đã tụt) — nếu không, một lần ghi trượt sẽ mất
        cờ vĩnh viễn.
        """
        self._da_thu += 1
        if la_rf:
            self._rf_tong += 1
            self._rf_lien_tiep += 1
        else:
            self._rf_lien_tiep = 0
        vuot_chuoi = self._rf_lien_tiep >= CAU_DAO_SO_LIEN_TIEP
        vuot_ti_le = (self._rf_tong >= CAU_DAO_SO_LIEN_TIEP
                      and self._rf_tong > CAU_DAO_TI_LE * self._da_thu)
        if (vuot_chuoi or vuot_ti_le) and not self._da_bao:
            log.error("job %s: nghi sự cố hàng loạt — %d/%d video đã thử báo 'Requested format is "
                      "not available' (liên tiếp %d)", self._job_id, self._rf_tong,
                      self._da_thu, self._rf_lien_tiep)
            self._da_bao = True
        if self._da_bao and not self._da_luu:
            try:
                models.set_job_nghi_su_co_hang_loat(self._db_path, self._job_id)
                self._da_luu = True
            except Exception as exc:  # noqa: BLE001 — bookkeeping must not fail a job
                log.warning("job %s: không ghi được cờ sự cố hàng loạt (%s)",
                            self._job_id, type(exc).__name__)

    def note(self, kind: str, info: dict | None = None) -> None:
        ref = self._refs[self._idx]
        self._idx += 1
        if kind == "downloaded":
            self._theo_doi_hang_loat(False)
        elif kind == "failed":
            self._theo_doi_hang_loat(
                CAU_DAO_MAU_LOI in str((info or {}).get("loi", "")).lower())
        if kind == "failed":
            # `info` của nhánh lỗi chỉ mang lý do, không phải metadata yt-dlp.
            self._ghi_loi(ref, (info or {}).get("loi", ""), da_log=True)
            return
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
                    # Lỗi hệ thống: ĐÚNG MỘT dòng ERROR (ở `_ghi_loi`), kèm đủ
                    # ngữ cảnh — không thêm dòng WARNING song song.
                    self._ghi_loi(
                        ref,
                        f"xác minh có luồng video nhưng lifecycle hook báo "
                        f"{result.outcome.value} ({result.reason}) — tính là lỗi, không tính là xong",
                        loai="he_thong")
            else:
                self._ghi_loi(ref, LOI_KHONG_CO_LUONG_VIDEO)
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
        dung = {}
        refs = _fetch_refs(job["url"], max_videos=job["tong"], cookies_path=cookies_path,
                            db_path=db_path, job_id=job_id, ly_do_ra=dung)
        models.set_job_found(db_path, job_id, len(refs))
        if not refs:
            # Lượt rỗng KHÔNG mặc nhiên là "Xong": nguồn trả 0 video, feed TikTok
            # rỗng, hay nghi bị chặn đều là "không lấy được gì" — ghi "Xong" cho
            # chúng là bảo user việc đã hoàn thành trong khi chưa tải được gì.
            # Chỉ `already_owned` (thư viện đã có hết những gì nguồn đưa ra) và
            # lượt không báo lý do mới là xong thật.
            ket_qua = "failed" if dung.get("ly_do") in _LY_DO_RONG_LA_LOI else "done"
            models.finish_job(db_path, job_id, ket_qua)
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
                 process_job_fn: Callable[..., None] = process_job,
                 disk_guard_fn: Callable[[Path], object] = check_disk_guard):
        self._db_path = db_path
        self._downloads_dir = downloads_dir
        self._cookies_dir = cookies_dir
        self._poll_interval = poll_interval
        self._process_job_fn = process_job_fn
        self._disk_guard_fn = disk_guard_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Trạng thái đọc từ luồng khác (`trang_thai()`); chỉ luồng worker ghi.
        # Hai bộ đếm, hai việc: `_loi_lien_tiep` là số BÁO RA (healthz/badge) — xoá ngay khi
        # nhận được job, để một lỗi thoáng qua không bị báo "lỗi lặp" suốt job lành kế tiếp;
        # `_so_lan_nghi` chỉ để nghỉ lùi — xoá khi CẢ vòng trót lọt, để "nhận được mà xử lý
        # hỏng" liên tục vẫn nghỉ lùi dần thay vì dội vào DB mỗi nhịp poll.
        self._loi_lien_tiep = 0
        self._so_lan_nghi = 0
        self._loi_cuoi: str | None = None
        self._cho_dia: str | None = None
        self._nhac_cho_dia_luc = 0.0
        # Job dở chưa ghi được 'interrupted'. `frozenset` và chỉ GÁN LẠI cả tập: luồng web
        # đọc nó trong `trang_thai()`, sửa tại chỗ sẽ làm phép duyệt bên đó nổ.
        self._cho_danh_dau: frozenset[int] = frozenset()

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

    def trang_thai(self) -> dict:
        """Cho healthz / badge quản trị: worker có sống không, lỗi lặp bao nhiêu lần
        liên tiếp (0 trong lúc một job đang chạy lành), có đang chờ vì đĩa không. Luồng chết im lặng từng xảy ra 7 lần
        (23–24/09, `disk I/O error` ở `claim_next_pending_job`) — không ai biết."""
        return {
            "song": self._thread is not None and self._thread.is_alive(),
            "loi_lien_tiep": self._loi_lien_tiep,
            "loi_cuoi": self._loi_cuoi,
            "cho_dia": self._cho_dia,
            "job_ket": sorted(self._cho_danh_dau),
        }

    def _loop(self) -> None:
        # MỖI vòng được bọc: trước đây một `OperationalError` ở `claim_next_pending_job`
        # (hay ở `finish_job` bên trong `process_job`) lọt ra đây và GIẾT luồng — app
        # vẫn phục vụ web, job kẹt 'running'/'pending' tới lần restart sau.
        while not self._stop.is_set():
            job = None
            self._thu_lai_danh_dau()
            try:
                # Cổng đĩa LÚC NHẬN job, cùng ngưỡng với cổng lúc tạo job (`POST /jobs`):
                # job đã chờ trước khi đĩa tụt không được bắt đầu tải khi đĩa đã cạn.
                # Không tự fail — job ở lại 'pending', chạy khi đĩa có chỗ lại.
                dia = self._disk_guard_fn(self._downloads_dir)
                if not dia.ok:
                    # Log khi BƯỚC VÀO trạng thái chờ, không log mỗi vòng: lý do mang số MB
                    # đổi từng giây (đĩa mini tụt theo swap của account khác), và log dồn
                    # lên chính cái đĩa đang dưới ngưỡng. `_cho_dia` vẫn cập nhật số mới.
                    bay_gio = time.monotonic()
                    if self._cho_dia is None or bay_gio - self._nhac_cho_dia_luc >= NHAC_CHO_DIA_GIAY:
                        log.warning("worker %s, chưa nhận job pending: %s",
                                    "CHỜ" if self._cho_dia is None else "VẪN CHỜ", dia.reason)
                        self._nhac_cho_dia_luc = bay_gio
                    self._cho_dia = dia.reason
                    self._loi_lien_tiep = self._so_lan_nghi = 0
                    self._stop.wait(self._poll_interval)
                    continue
                if self._cho_dia is not None:
                    log.info("worker hết chờ đĩa, nhận job lại")
                self._cho_dia = None
                job = models.claim_next_pending_job(self._db_path)
                self._loi_lien_tiep = 0  # nhận được (hoặc hàng rỗng): DB đang đọc/ghi được
                if job is not None:
                    self._process_job_fn(self._db_path, self._downloads_dir, self._cookies_dir, job)
                self._so_lan_nghi = 0  # cả vòng trót lọt
                if job is None:
                    self._stop.wait(self._poll_interval)
            except Exception as exc:  # noqa: BLE001 — vòng worker không được chết
                self._so_lan_nghi += 1
                # Báo ra CHUỖI lỗi thật (1, 2, 3…) kể cả khi mỗi vòng đều nhận được job rồi
                # mới hỏng — xoá lúc claim chỉ để job LÀNH kế tiếp không bị báo "lỗi lặp".
                self._loi_lien_tiep = self._so_lan_nghi
                self._loi_cuoi = type(exc).__name__
                log.error("worker lỗi (lần %d liên tiếp)%s", self._loi_lien_tiep,
                          f", job {job['id']} đang dở" if job else "", exc_info=True)
                if job is not None:
                    try:
                        models.mark_job_interrupted(self._db_path, job["id"])
                    except Exception:  # noqa: BLE001 — DB vẫn hỏng: thử lại ở đầu vòng sau
                        self._cho_danh_dau = self._cho_danh_dau | {job["id"]}
                        log.error("worker: chưa ghi được 'interrupted' cho job %s — thử lại "
                                  "mỗi vòng", job["id"], exc_info=True)
                self._stop.wait(self.nghi_sau_loi(self._so_lan_nghi))

    def _thu_lai_danh_dau(self) -> None:
        """Job bị bỏ dở mà lần trước chưa ghi được 'interrupted' (DB còn hỏng lúc đó): thử
        lại MỖI vòng tới khi ghi được — lượt quét lúc khởi động giờ hiếm chạy, vì worker
        không còn chết để được restart. Nằm NGOÀI đường nhận job: một hàng không ghi được
        mãi (vd trang DB hỏng cục bộ) không được chặn cả hàng đợi. Trượt thì im lặng (đã log
        lúc thêm vào); id vẫn hiện ở `job_ket` của healthz/badge cho tới khi ghi được."""
        for jid in sorted(self._cho_danh_dau):
            try:
                models.mark_job_interrupted(self._db_path, jid)
            except Exception:  # noqa: BLE001
                continue
            self._cho_danh_dau = self._cho_danh_dau - {jid}  # đã đổi, hoặc đã rời 'running'
            log.info("worker: đã ghi 'interrupted' cho job %s (thử lại)", jid)

    def nghi_sau_loi(self, lan: int) -> float:
        """Số giây nghỉ sau lần lỗi liên tiếp thứ `lan` (≥1): poll, 2×poll, 4×poll…, trần
        `TRAN_NGHI_LOI_GIAY`. Kẹp số mũ: lỗi lặp cả ngày không được làm tràn số NGAY TRONG
        nhánh bắt lỗi (đó là chỗ duy nhất gọi hàm này)."""
        return min(self._poll_interval * 2 ** min(max(lan, 1) - 1, 16), TRAN_NGHI_LOI_GIAY)
