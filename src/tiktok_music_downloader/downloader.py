"""yt-dlp wrapper: watermark-free MP4 download with jitter + adaptive backoff."""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable

from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from tiktok_music_downloader.phan_loai_loi import LOI_THIEU_JS, ly_do_loi_video, phan_loai_loi, phat_hien_chan
from tiktok_music_downloader.utils import (
    che_url,
    JitterThrottle,
    VideoRef,
    adaptive_backoff,
    random_user_agent,
)
from tiktok_music_downloader.watermark import WatermarkConfig, apply_watermark, find_deno, find_ffmpeg

log = logging.getLogger("ttmd")

# Jar Netscape tạm mang cookie ở dạng văn bản thuần. `download_all` xoá nó
# trong `finally`, nhưng SIGKILL không chạy `finally` — và dịch vụ web chạy
# dưới launchd `KeepAlive=true`, tức bị giết là dựng lại ngay. Lớp web trỏ
# `COOKIE_TMP_DIR` vào thư mục dữ liệu 0700 của chính nó rồi quét sạch lúc
# khởi động; để `None` thì hành vi y như cũ (thư mục tạm hệ thống), nên công
# cụ dòng lệnh không đổi gì.
COOKIE_TMP_PREFIX = "ttmd-cookies-"
COOKIE_TMP_DIR: str | None = None

BATCH_SIZE = 50
BATCH_REST_SECONDS = 60.0


# Cảnh báo yt-dlp khi KHÔNG tìm được JS runtime (đường Deno trỏ sai / Deno hỏng). yt-dlp vẫn chạy tiếp và có
# thể ra thiếu định dạng, nên với nền tảng link lẻ cảnh báo này phải biến thành LỖI của video đó.
_MAU_THIEU_JS = "no supported javascript runtime"


class _YtdlpLog:
    """Đích log của yt-dlp: mọi mức xuống DEBUG của `ttmd`. Lỗi tải được ghi ĐÚNG MỘT lần bởi dòng `✗`
    của `download_all` (có phân loại tiktok/hệ thống, đã che URL); cảnh báo yt-dlp vốn đã tắt (`no_warnings`).

    Ngoại lệ: cảnh báo "No supported JavaScript runtime" được BẮT riêng (cờ `thieu_js`) rồi vẫn xuống DEBUG —
    người dùng object này (`download_all`, bước liệt kê) đọc cờ sau mỗi lời gọi yt-dlp."""

    thieu_js = False

    def debug(self, msg: str) -> None:
        log.debug("yt-dlp: %s", msg)

    info = error = debug

    def warning(self, msg: str) -> None:
        if _MAU_THIEU_JS in str(msg).lower():
            self.thieu_js = True
        self.debug(msg)


def _ydl_opts(output_dir: Path, proxy: str | None, cookiefile: str | None) -> dict:
    """yt-dlp options for TikTok no-watermark MP4."""
    opts: dict = {
        # Prefer no-watermark h264 formats; fall back to best MP4 if extractor changes.
        # Every branch must carry a VIDEO stream. A TikTok photo/slideshow post
        # offers exactly one format — `vcodec=none, acodec=mp3` — so an
        # unconstrained `/best` tail accepts it and yt-dlp reports success for
        # an .mp3 that is not a video at all. Measured 2026-09-10 on #trendanos80:
        # 151 of 259 "downloads" came back as .mp3/.m4a that way. With
        # `[vcodec!=none]` on every branch such a post fails loudly instead.
        "format": ("bv*[vcodec^=h264][protocol^=http]+ba/"
                   "best[ext=mp4][vcodec!=none]/best[vcodec!=none]"),
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # Không có `logger` thì yt-dlp ghi THẲNG stderr (launchd gom vào cùng tệp log), bỏ qua formatter che URL.
        # KHÔNG đưa thẳng `log`: yt-dlp gọi `logger.error` cho mọi lỗi tải (×3 vì retry) và `logger.warning` bất
        # kể `no_warnings` ⇒ lỗi phía TikTok sẽ lên ERROR, trái với "lỗi TikTok chỉ WARNING" (queue `_ghi_loi`).
        "logger": _YtdlpLog(),
        "concurrent_fragment_downloads": 1,
        "retries": 2,
        "fragment_retries": 2,
        "http_headers": {"User-Agent": random_user_agent()},
        "extractor_args": {
            "tiktok": {"api_hostname": ["api22-normal-c-useast2a.tiktokv.com"]},
        },
    }
    if proxy:
        opts["proxy"] = proxy
    if cookiefile:
        # yt-dlp uses cookies to bypass "Log in for access" gates (age-gated /
        # sensitive videos that the music page lists but won't serve to anon).
        opts["cookiefile"] = cookiefile
    return opts


# Nền tảng KHÁC TikTok (link lẻ qua yt-dlp). Mọi nhánh mang luồng HÌNH (`vcodec!=none`) — cùng bài học với dict
# TikTok: một nhánh `/best` trần nhận được tệp chỉ có tiếng rồi yt-dlp báo thành công. Ưu tiên ≤1080p, mp4/m4a
# trước (ghép bằng remux, không mã hoá lại); rơi dần về bất kỳ định dạng có hình.
FORMAT_NEN_TANG_KHAC = (
    "bv*[height<=1080][ext=mp4][vcodec!=none]+ba[ext=m4a]/"
    "bv*[height<=1080][vcodec!=none]+ba/"
    "b[height<=1080][vcodec!=none]/"
    "bv*[vcodec!=none]+ba/b[vcodec!=none]"
)


def opts_chung_nen_tang_khac(proxy: str | None = None) -> dict:
    """Phần dùng chung cho liệt kê (`extract_info(download=False)`) và tải của nền tảng KHÁC TikTok.

    Dịch vụ chạy với PATH không có Homebrew nên yt-dlp KHÔNG tự thấy ffmpeg (ghép DASH) lẫn Deno (JS của
    YouTube): chỉ đường tường minh. Không tìm thấy thì bỏ khoá (để yt-dlp tự báo), không truyền `None`.
    Không đặt `http_headers`/`extractor_args` của TikTok: UA ngẫu nhiên lệch với client YouTube mà yt-dlp mô phỏng."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _YtdlpLog(),
        # Link `watch?v=…&list=…` là MỘT video; playlist thật không được nhận ở bước nhận dạng.
        "noplaylist": True,
        "concurrent_fragment_downloads": 1,
        "retries": 2,
        "fragment_retries": 2,
    }
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    deno = find_deno()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    if proxy:
        opts["proxy"] = proxy
    return opts


def _ydl_opts_nen_tang_khac(output_dir: Path, proxy: str | None, cookiefile: str | None) -> dict:
    """yt-dlp options cho nền tảng KHÁC TikTok. `outtmpl` đặt lại theo TỪNG ref ở `download_all` (tên tệp là
    `ref.video_id` đã có tiền tố nền tảng, không phải id trần của yt-dlp)."""
    opts = opts_chung_nen_tang_khac(proxy)
    opts.update({
        "format": FORMAT_NEN_TANG_KHAC,
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
    })
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


class DungTai(Exception):
    """Cổng nền tảng (`cong.truoc_goi`) từ chối lời gọi kế tiếp: hết trần giờ/ngày hoặc nền tảng đã tắt. Mang
    mã lý do dừng. Không phải lỗi của video — `_download_one` không thử lại và `download_all` dừng cả lượt."""

    def __init__(self, ly_do: str):
        super().__init__(ly_do)
        self.ly_do = ly_do


def _write_netscape_cookies(json_path: Path) -> Path:
    """Convert Playwright/Cookie-Editor JSON cookies to Netscape format for yt-dlp.

    yt-dlp's `cookiefile` expects the Netscape (curl) text format. We reuse the
    same JSON the scraper uses, normalize, and write a temp file. Caller is
    responsible for deleting the returned path.

    Netscape format columns (tab-separated):
        domain  include_subdomains  path  secure  expires  name  value
    """
    # Reuse the scraper's loader so format quirks (RTF, storage_state wrapper,
    # sameSite normalization) are handled in one place.
    from tiktok_music_downloader.scraper import _load_cookies

    cookies = _load_cookies(json_path)
    fd, tmp = tempfile.mkstemp(prefix=COOKIE_TMP_PREFIX, suffix=".txt",
                                dir=COOKIE_TMP_DIR)
    da_ghi = 0
    bo_qua_ky_tu_la = 0
    with open(fd, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in cookies:
            domain = c.get("domain") or ""
            if not domain:
                continue
            path = c.get("path") or "/"
            name = c.get("name", "")
            value = c.get("value", "")
            # Netscape phân cột bằng TAB. Một cookie mang TAB/xuống dòng trong
            # giá trị sẽ sinh ra dòng sai số cột, và yt-dlp KHÔNG ném lỗi — nó
            # in NGUYÊN dòng đó (kèm `sessionid` đầy đủ) ra stderr rồi chạy
            # tiếp. stderr của dịch vụ đổ thẳng vào ~/Library/Logs/videodl.log
            # trên máy dùng chung, và file đó không nằm trong lớp 0700 nào.
            # Đây là chỗ DUY NHẤT ta kiểm soát được — thông điệp của yt-dlp thì
            # không. Bỏ qua cookie đó và chỉ đếm, không log giá trị.
            if any("\t" in str(x) or "\n" in str(x) or "\r" in str(x)
                   for x in (domain, path, name, value)):
                bo_qua_ky_tu_la += 1
                continue
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            secure = "TRUE" if c.get("secure") else "FALSE"
            # `expires` đi qua `_normalize_cookie` NGUYÊN XI (chỉ `expirationDate`
            # mới được ép kiểu), nên bản xuất ghi ISO hay chuỗi float sẽ làm
            # `int()` ném — và lời gọi này nằm trong một `except` nuốt lỗi rồi
            # chạy tiếp KHÔNG cookie, tức hỏng âm thầm. Không đọc được hạn thì
            # coi như cookie phiên.
            try:
                expires = int(c.get("expires", 0) or 0)
            except (TypeError, ValueError):
                expires = 0
            f.write(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            da_ghi += 1
    if bo_qua_ky_tu_la:
        log.warning("bỏ qua %d cookie có ký tự phân cột (TAB/xuống dòng) trong giá trị",
                     bo_qua_ky_tu_la)
    log.info("wrote %d cookies to yt-dlp jar %s", da_ghi, tmp)
    return Path(tmp)


def _nen_thu_lai(exc: BaseException) -> bool:
    """Thử lại mọi lỗi, TRỪ lệnh dừng của cổng nền tảng và lỗi đã đánh dấu `khong_thu_lai` (nền tảng link lẻ:
    tín hiệu chặn, video riêng tư/giới hạn tuổi). Thử lại hai loại đó vô ích, và mỗi lần thử là một lượt tính vào
    trần IP — còn gõ lại vào đúng thứ đang chặn mình thì làm đậm dấu vết."""
    # `Exception` chứ không phải mọi `BaseException`: SystemExit/KeyboardInterrupt không bao giờ được thử lại
    # (mặc định của tenacity cũng vậy — bản này không được rộng hơn).
    return isinstance(exc, Exception) and not isinstance(exc, DungTai) and not getattr(exc, "khong_thu_lai", False)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_exception(_nen_thu_lai),
    reraise=True,
)
def _download_one(url: str, opts: dict, truoc_goi: Callable[[], str | None] | None = None) -> dict | None:
    """Tải một video, và trả về metadata yt-dlp đã phải đọc để tải được nó.

    `extract_info(download=True)` làm đúng việc `download()` làm, chỉ khác là
    nó KHÔNG vứt cái dict nó vừa dựng. Đây là nguồn metadata duy nhất phủ được
    mọi nguồn: chỉ trang hashtag có index trả `title`/`author`/`region`; music
    page và profile thì scraper chỉ dựng được `VideoRef(video_id, url)` trần,
    nên thư viện hiện "chưa có tiêu đề" cho mọi video tải từ hai nguồn đó.

    `truoc_goi` (chỉ nền tảng link lẻ): chạy ĐẦU MỖI LẦN THỬ — kể cả lần thử lại của tenacity, vì mỗi lần là một
    lời gọi thật tới nền tảng — để bộ đếm lượt ghi TRƯỚC khi gọi. Trả lý do ⇒ `DungTai`, không gọi, không thử lại.
    """
    if truoc_goi is not None:
        ly_do = truoc_goi()
        if ly_do:
            raise DungTai(ly_do)
    try:
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True)
    except Exception as exc:
        if truoc_goi is not None and (phat_hien_chan(exc) or ly_do_loi_video(exc)):
            exc.khong_thu_lai = True
        raise


def _looks_like_rate_limit(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in ("429", "rate", "too many", "blocked", "captcha"))


def _fb_download_headers() -> dict:
    """Build fresh headers per download — UA is rotated, not frozen at import."""
    return {
        "Referer": "https://www.facebook.com/",
        "Origin": "https://www.facebook.com",
        "User-Agent": random_user_agent(),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    retry=retry_if_not_exception_type(RuntimeError),
    reraise=True,
)
def _download_url_direct(url: str, target: Path, proxy: str | None) -> None:
    """Stream a signed MP4 URL to disk. Retries transient errors; bails on 410.

    410 means the FBCDN HMAC expired between scrape and download — no point
    retrying (raises RuntimeError which the retry decorator skips).
    """
    import requests  # lazy import so users without `requests` see a clean error

    proxies = {"http": proxy, "https": proxy} if proxy else None
    with requests.get(url, headers=_fb_download_headers(), stream=True,
                      proxies=proxies, timeout=(10, 60)) as r:
        if r.status_code == 410:
            # Don't retry — URL is permanently expired.
            raise RuntimeError("FBCDN URL expired (410 Gone) — re-scrape needed")
        if r.status_code == 403:
            # Chữ ký HMAC hết hạn / bị từ chối cũng trả 403 — cùng bản chất với 410, thử lại chỉ tốn backoff.
            raise RuntimeError("FBCDN URL refused (403 Forbidden) — re-scrape needed")
        r.raise_for_status()
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
            tmp.replace(target)
        finally:
            # Lỗi giữa luồng (đứt mạng) không được để lại `.part` trên đĩa; thành công thì đã đổi tên.
            tmp.unlink(missing_ok=True)


def _tai_nen_tang_khac(ref: VideoRef, opts: dict, output_dir: Path, cong) -> dict | None:
    """Tải MỘT video của nền tảng KHÁC TikTok. Tên tệp đích = `ref.video_id` (có tiền tố nền tảng).

    Hai lỗi cấu hình phải LỘ NGAY thành lỗi của video, không được trôi thành tệp thiếu:
      · không có ffmpeg ⇒ yt-dlp chỉ cảnh báo rồi để hai luồng rời, không ra `<id>.mp4`;
      · cảnh báo "No supported JavaScript runtime" lọt tới `_YtdlpLog` ⇒ định dạng có thể thiếu: xoá tệp vừa
        tải (nếu không, lượt chạy lại sẽ coi nó "đã có trên đĩa" và nuốt lỗi) rồi báo lỗi."""
    if not opts.get("ffmpeg_location"):
        raise RuntimeError("thiếu ffmpeg: không ghép được hình và tiếng của video")
    logger = opts["logger"]
    logger.thieu_js = False
    opts_ref = {**opts, "outtmpl": str(output_dir / f"{ref.video_id}.%(ext)s")}
    info = (_download_one(ref.url, opts_ref, cong.truoc_goi) if cong is not None
            else _download_one(ref.url, opts_ref))
    if logger.thieu_js:
        (output_dir / ref.filename).unlink(missing_ok=True)
        raise RuntimeError(f"{LOI_THIEU_JS}: yt-dlp không thấy JavaScript runtime (Deno) — đường Deno sai hoặc hỏng")
    return info


def download_all(
    refs: Iterable[VideoRef],
    output_dir: Path,
    delay_seconds: float = 2.0,
    proxy: str | None = None,
    progress=None,
    batch_size: int = BATCH_SIZE,
    batch_rest: float = BATCH_REST_SECONDS,
    cookies_path: str | None = None,
    watermark: WatermarkConfig | None = None,
    truoc_moi_file: Callable[[VideoRef], str | None] | None = None,
    nen_tang: str | None = None,
    cong=None,
    delay_range: tuple[float, float] | None = None,
) -> tuple[int, int, list[str]]:
    """
    Download each VideoRef.

    Anti-block: jitter delay between calls, adaptive backoff on rate-limit-like
    errors, mandatory rest after every `batch_size` successful downloads.
    Resumable: skip if file already on disk.
    Auth: `cookies_path` (the same JSON used by the scraper) is converted to
    Netscape format and passed to yt-dlp — unlocks age-gated videos.

    `truoc_moi_file(ref)` chạy ngay trước khi tải từng ref (sau bước "đã có trên đĩa"): trả chuỗi lý do
    ⇒ DỪNG cả lượt (không tải ref này và các ref sau), trả None ⇒ tải tiếp. Dùng cho cổng đĩa.

    `nen_tang` (None hoặc "tiktok" ⇒ đường TikTok, dict opts y hệt cũ; tên nền tảng khác ⇒ opts yt-dlp riêng,
    xem `_ydl_opts_nen_tang_khac`) và `cong` (bộ điều tốc IP của nền tảng đó, `web/pacer.py::CongNenTang`:
    `truoc_goi()` trả lý do hoặc None, `xu_ly_loi(exc)` trả lý do dừng khi lỗi là tín hiệu chặn) chỉ có tác dụng
    ở đường nền tảng khác. Cổng từ chối / tín hiệu chặn ⇒ DỪNG cả lượt (cổng tự ghi lý do vào `cong`).
    `delay_range` = khoảng nghỉ (thấp, cao) giữa hai video thay cho `delay_seconds`.

    Returns (downloaded, skipped, failed_ids).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cookiefile_tmp: Path | None = None
    if cookies_path:
        try:
            cookiefile_tmp = _write_netscape_cookies(Path(cookies_path))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not load cookies for yt-dlp (%s) — continuing without", che_url(exc))
    la_tiktok = nen_tang is None or nen_tang == "tiktok"
    cookiefile_str = str(cookiefile_tmp) if cookiefile_tmp else None
    opts = (_ydl_opts(output_dir, proxy, cookiefile_str) if la_tiktok
            else _ydl_opts_nen_tang_khac(output_dir, proxy, cookiefile_str))
    throttle = JitterThrottle(delay_seconds, khoang=delay_range)

    downloaded = 0
    skipped = 0
    failed: list[str] = []
    failure_streak = 0
    since_rest = 0

    def _note(kind: str, info: dict | None = None) -> None:
        """Inform the UI of a per-video outcome, if it supports `note()`.

        `info` đi kèm chứ không sửa `refs` tại chỗ: `download_all` nhận
        `Iterable`, nên không có gì bảo đảm người gọi đang giữ CÙNG một list —
        một bản vá dựa vào việc sửa được phần tử sẽ im lặng không có tác dụng
        với người gọi truyền generator.
        """
        if progress is None or not hasattr(progress, "note"):
            return
        try:
            progress.note(kind, info)
        except TypeError:
            # `note()` cũ chỉ nhận một tham số. Giữ đường lui để thư viện này
            # dùng được ngoài web app (CLI truyền progress riêng).
            progress.note(kind)

    try:
        for ref in refs:
            target = output_dir / ref.filename
            if target.exists() and target.stat().st_size > 0:
                log.info("⊙ skip (already on disk) %s", ref.filename)
                skipped += 1
                _note("skipped")
                if progress is not None:
                    progress.update(1)
                continue

            if truoc_moi_file is not None:
                ly_do_dung = truoc_moi_file(ref)
                if ly_do_dung:
                    log.warning("dừng lượt tải trước %s: %s", ref.filename, ly_do_dung)
                    break

            if since_rest >= batch_size:
                log.info("batch of %d done — resting %.0fs", batch_size, batch_rest)
                time.sleep(batch_rest)
                since_rest = 0

            throttle.wait()
            outcome: str | None = None
            note_info: dict | None = None
            da_dung = False
            try:
                # FB Ads Library refs carry a signed FBCDN MP4 URL — yt-dlp
                # can't authenticate them, so use a direct HTTP stream.
                # TikTok refs go through yt-dlp as before.
                info: dict | None = None
                if ref.video_id.startswith("fb-"):
                    _download_url_direct(ref.url, target, proxy)
                elif ref.video_id.startswith("gd-"):
                    # Drive: từng file theo id (nguồn đã liệt kê, không tải cả thư mục), để file
                    # đi đúng đường verify → đẩy Drive → xoá local rồi mới tới file kế.
                    from tiktok_music_downloader.gdrive import download_file
                    download_file(ref.video_id[len("gd-"):], target, proxy)
                elif la_tiktok:
                    info = _download_one(ref.url, opts)
                else:
                    info = _tai_nen_tang_khac(ref, opts, output_dir, cong)
                # Post-process: apply watermark in-place if configured. Failures
                # are non-fatal — the un-watermarked file remains on disk.
                if watermark is not None and not watermark.is_empty:
                    apply_watermark(target, watermark)
                downloaded += 1
                since_rest += 1
                failure_streak = 0
                outcome = "downloaded"
                note_info = info
                log.info("✓ %s", ref.filename)
            except DungTai as dung:
                # Cổng từ chối TRƯỚC khi gọi nền tảng: video này chưa được thử nên không tính lỗi (không `outcome`,
                # không vào `failed`); lý do dừng nằm ở `cong`. DỪNG thay vì ngủ chờ cửa sổ trống: ngủ sẽ giữ cả lane.
                log.warning("dừng lượt tải trước %s: %s", ref.filename, dung.ly_do)
                da_dung = True
            except (DownloadError, RetryError, Exception) as exc:  # noqa: BLE001
                failed.append(ref.video_id)
                outcome = "failed"
                # Lỗi do TikTok không cho tải (bài ảnh, video gỡ) là ca bình
                # thường của việc quét nguồn — WARNING, để ERROR dành cho lỗi
                # thật của hệ thống. Không rõ loại nào thì mặc định ERROR.
                if phan_loai_loi(exc) == "tiktok":
                    log.warning("✗ %s: [tiktok] %s", ref.video_id, che_url(exc))
                else:
                    log.error("✗ %s: [he_thong] %s", ref.video_id, che_url(exc))
                note_info = {"loi": str(exc)}
                if cong is not None and cong.xu_ly_loi(exc):
                    # Tín hiệu CHẶN của nền tảng: không tải tiếp video nào nữa (cũng không backoff-ngủ).
                    da_dung = True
                elif _looks_like_rate_limit(exc):
                    failure_streak += 1
                    cool = adaptive_backoff(failure_streak)
                    log.warning(
                        "rate-limit signal (streak=%d) → cooling %.0fs",
                        failure_streak,
                        cool,
                    )
                    time.sleep(cool)
            finally:
                if outcome:
                    _note(outcome, note_info)
                if progress is not None:
                    progress.update(1)
            if da_dung:
                break
    finally:
        if cookiefile_tmp is not None:
            try:
                cookiefile_tmp.unlink(missing_ok=True)
            except OSError:
                pass

    return downloaded, skipped, failed
