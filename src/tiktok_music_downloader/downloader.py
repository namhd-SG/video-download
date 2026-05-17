"""yt-dlp wrapper: watermark-free MP4 download with jitter + adaptive backoff."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterable

from tenacity import RetryError, retry, stop_after_attempt, wait_exponential
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from tiktok_music_downloader.utils import (
    JitterThrottle,
    VideoRef,
    adaptive_backoff,
    random_user_agent,
)

log = logging.getLogger("ttmd")

BATCH_SIZE = 50
BATCH_REST_SECONDS = 60.0


def _ydl_opts(output_dir: Path, proxy: str | None) -> dict:
    """yt-dlp options for TikTok no-watermark MP4."""
    opts: dict = {
        # Prefer no-watermark h264 formats; fall back to best MP4 if extractor changes.
        "format": "bv*[vcodec^=h264][protocol^=http]+ba/best[ext=mp4]/best",
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
    return opts


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


def download_all(
    refs: Iterable[VideoRef],
    output_dir: Path,
    delay_seconds: float = 2.0,
    proxy: str | None = None,
    progress=None,
    batch_size: int = BATCH_SIZE,
    batch_rest: float = BATCH_REST_SECONDS,
) -> tuple[int, int, list[str]]:
    """
    Download each VideoRef.

    Anti-block: jitter delay between calls, adaptive backoff on rate-limit-like
    errors, mandatory rest after every `batch_size` successful downloads.
    Resumable: skip if file already on disk.

    Returns (downloaded, skipped, failed_ids).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts(output_dir, proxy)
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

    for ref in refs:
        target = output_dir / ref.filename
        if target.exists() and target.stat().st_size > 0:
            log.debug("skip existing %s", ref.filename)
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
            _download_one(ref.url, opts)
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

    return downloaded, skipped, failed
