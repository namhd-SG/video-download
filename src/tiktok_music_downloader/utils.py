"""Shared helpers: logger, URL parsing, jittered throttle, UA pool, backoff."""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass

_VIDEO_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/@[\w.\-]+/video/(\d+)")
# Slug allows: \w (Unicode word chars — Vietnamese, Russian, etc.),
# hyphen, and `%` for percent-encoded URLs (e.g., Arabic slugs pasted from browser).
_MUSIC_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/music/[\w\-%]+-(\d+)")
_SEARCH_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/search/?\?")
# Hashtag page: /tag/<slug>. Same slug charset as music (Unicode word chars,
# hyphen, percent-encoding) but with no trailing numeric id to anchor on.
_TAG_RE = re.compile(r"https?://(?:www\.)?tiktok\.com/tag/[\w\-%]+")
_FB_ADS_RE = re.compile(r"https?://(?:www\.)?facebook\.com/ads/library/?\?")
# Google Drive folder share link. Covers all three URL shapes the share UI
# emits: `/folders/<ID>`, `/drive/folders/<ID>`, and `/drive/u/<N>/folders/<ID>`.
# ID is base64-ish — word chars and dashes.
_GDRIVE_FOLDER_RE = re.compile(
    r"https?://drive\.google\.com/(?:drive/(?:u/\d+/)?)?folders/([\w\-]+)"
)
# FBCDN MP4 URLs embed `xpv_asset_id` inside a base64-encoded `efg=` query
# param. Extracting it lets us name the downloaded file deterministically so
# resume-on-rerun works without re-downloading.
_FB_ASSET_RE = re.compile(r'"xpv_asset_id":(\d+)')

# Pool of recent Chrome desktop UA strings. Rotated per scrape session.
USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

# Hide common headless fingerprints (best-effort, not foolproof).
STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
"""


def setup_logger(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("ttmd")


@dataclass(frozen=True)
class VideoRef:
    """Stable reference to one TikTok video."""

    video_id: str
    url: str

    @property
    def filename(self) -> str:
        return f"{self.video_id}.mp4"


def parse_video_url(url: str) -> VideoRef | None:
    """Extract video_id from a TikTok video URL. Returns None if no match."""
    m = _VIDEO_RE.match(url.strip())
    if not m:
        return None
    return VideoRef(video_id=m.group(1), url=url)


def is_music_page(url: str) -> bool:
    """True if url is a TikTok music aggregation page."""
    return bool(_MUSIC_RE.match(url.strip()))


def is_search_page(url: str) -> bool:
    """True if url is a TikTok search results page (`/search?q=...`)."""
    return bool(_SEARCH_RE.match(url.strip()))


def is_tag_page(url: str) -> bool:
    """True if url is a TikTok hashtag page (`/tag/<slug>`)."""
    return bool(_TAG_RE.match(url.strip()))


def is_tiktok_collection(url: str) -> bool:
    """Any TikTok URL the scraper can enumerate — music, search, or hashtag.

    All three render the same `a[href*="/video/"]` cards inside a lazy-loading
    scroller, so `scrape_music_page` handles them without page-type branching.
    """
    return is_music_page(url) or is_search_page(url) or is_tag_page(url)


def is_gdrive_folder(url: str) -> bool:
    """True if url is a public Google Drive folder share link."""
    return bool(_GDRIVE_FOLDER_RE.match(url.strip()))


def is_fb_ads_library(url: str) -> bool:
    """True if url targets Facebook's Ads Library (any filter combination)."""
    return bool(_FB_ADS_RE.match(url.strip()))


def parse_fb_video_url(url: str) -> "VideoRef | None":
    """Extract a stable id from a FBCDN MP4 URL.

    The `efg=` query param holds base64-encoded JSON that contains the
    `xpv_asset_id`. We base64-decode and regex it out. Falls back to a hash of
    the URL's path if decoding fails — file naming stays deterministic either
    way, so resume / dedup still work.
    """
    import base64
    import hashlib
    import urllib.parse

    try:
        qs = urllib.parse.urlparse(url).query
        params = urllib.parse.parse_qs(qs)
        efg = params.get("efg", [""])[0]
        if efg:
            # FB uses standard base64 (with '%3D' = '=' padding) in URL form.
            efg_pad = efg + "=" * (-len(efg) % 4)
            decoded = base64.b64decode(efg_pad).decode("utf-8", "replace")
            m = _FB_ASSET_RE.search(decoded)
            if m:
                return VideoRef(video_id=f"fb-{m.group(1)}", url=url)
    except Exception:  # noqa: BLE001 — fall back rather than refuse to download
        pass
    # Fallback: short hash of the URL path (auth params stripped).
    path = urllib.parse.urlparse(url).path
    digest = hashlib.sha1(path.encode()).hexdigest()[:12]
    return VideoRef(video_id=f"fb-{digest}", url=url)


def random_user_agent(rng: random.Random | None = None) -> str:
    return (rng or random).choice(USER_AGENTS)


class JitterThrottle:
    """Enforce a random delay in [base*0.75, base*2.0] between calls."""

    def __init__(self, base_seconds: float, rng: random.Random | None = None):
        self.base = max(0.0, base_seconds)
        self.rng = rng or random.Random()
        self._last = 0.0

    def _next_interval(self) -> float:
        if self.base <= 0:
            return 0.0
        return self.rng.uniform(self.base * 0.75, self.base * 2.0)

    def wait(self) -> None:
        interval = self._next_interval()
        if interval == 0.0:
            return
        elapsed = time.monotonic() - self._last
        remain = interval - elapsed
        if remain > 0:
            time.sleep(remain)
        self._last = time.monotonic()


def adaptive_backoff(failure_streak: int, max_seconds: float = 300.0) -> float:
    """Return cool-down seconds given consecutive-failure count (1-indexed)."""
    if failure_streak <= 0:
        return 0.0
    seconds = min(30.0 * (2 ** (failure_streak - 1)), max_seconds)
    return seconds
