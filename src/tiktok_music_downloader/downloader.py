"""yt-dlp wrapper: watermark-free MP4 download with jitter + adaptive backoff."""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Iterable

from tenacity import (
    RetryError,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from tiktok_music_downloader.utils import (
    JitterThrottle,
    VideoRef,
    adaptive_backoff,
    random_user_agent,
)
from tiktok_music_downloader.watermark import WatermarkConfig, apply_watermark

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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)
def _download_one(url: str, opts: dict) -> None:
    with YoutubeDL(opts) as ydl:
        ydl.download([url])


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
        r.raise_for_status()
        tmp = target.with_suffix(target.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(target)


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
) -> tuple[int, int, list[str]]:
    """
    Download each VideoRef.

    Anti-block: jitter delay between calls, adaptive backoff on rate-limit-like
    errors, mandatory rest after every `batch_size` successful downloads.
    Resumable: skip if file already on disk.
    Auth: `cookies_path` (the same JSON used by the scraper) is converted to
    Netscape format and passed to yt-dlp — unlocks age-gated videos.

    Returns (downloaded, skipped, failed_ids).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cookiefile_tmp: Path | None = None
    if cookies_path:
        try:
            cookiefile_tmp = _write_netscape_cookies(Path(cookies_path))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not load cookies for yt-dlp (%s) — continuing without", exc)
    opts = _ydl_opts(output_dir, proxy, str(cookiefile_tmp) if cookiefile_tmp else None)
    throttle = JitterThrottle(delay_seconds)

    downloaded = 0
    skipped = 0
    failed: list[str] = []
    failure_streak = 0
    since_rest = 0

    def _note(kind: str) -> None:
        """Inform the UI of a per-video outcome, if it supports `note()`."""
        if progress is not None and hasattr(progress, "note"):
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

            if since_rest >= batch_size:
                log.info("batch of %d done — resting %.0fs", batch_size, batch_rest)
                time.sleep(batch_rest)
                since_rest = 0

            throttle.wait()
            outcome: str | None = None
            try:
                # FB Ads Library refs carry a signed FBCDN MP4 URL — yt-dlp
                # can't authenticate them, so use a direct HTTP stream.
                # TikTok refs go through yt-dlp as before.
                if ref.video_id.startswith("fb-"):
                    _download_url_direct(ref.url, target, proxy)
                else:
                    _download_one(ref.url, opts)
                # Post-process: apply watermark in-place if configured. Failures
                # are non-fatal — the un-watermarked file remains on disk.
                if watermark is not None and not watermark.is_empty:
                    apply_watermark(target, watermark)
                downloaded += 1
                since_rest += 1
                failure_streak = 0
                outcome = "downloaded"
                log.info("✓ %s", ref.filename)
            except (DownloadError, RetryError, Exception) as exc:  # noqa: BLE001
                failed.append(ref.video_id)
                outcome = "failed"
                log.error("✗ %s: %s", ref.video_id, exc)
                if _looks_like_rate_limit(exc):
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
                    _note(outcome)
                if progress is not None:
                    progress.update(1)
    finally:
        if cookiefile_tmp is not None:
            try:
                cookiefile_tmp.unlink(missing_ok=True)
            except OSError:
                pass

    return downloaded, skipped, failed
