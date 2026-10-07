"""Scrape Facebook Ads Library for direct MP4 URLs.

The Ads Library is publicly accessible (no login wall for `view_all_page_id=*`
filter URLs) and renders each ad with a <video src=...mp4> pointing at a
signed FBCDN URL. We let Playwright run the SPA, scroll a few times so the
infinite-scroll fetches batches, then collect every distinct video src.

URLs are signed (HMAC + expiry in `oh=` / `oe=` query params) — the caller
should start downloading shortly after scrape finishes; the same FBCDN URL
will 410 once the HMAC expires (typically a few hours).
"""
from __future__ import annotations

import logging
import random
import time
import urllib.parse
from pathlib import Path
from typing import Callable

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PWTimeout,
    sync_playwright,
)

from tiktok_music_downloader.utils import (
    STEALTH_INIT_JS,
    VideoRef,
    parse_fb_video_url,
    random_user_agent,
)

log = logging.getLogger("ttmd")


# Trần số ref khi đếm riêng video mới (xem `_auto_scroll`).
HE_SO_TRAN_DA_CO = 3


def _dedup_key(url: str) -> str:
    """Strip auth params so the same asset across page reloads dedups to one ref."""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.netloc}{parsed.path}"


def _collect_video_urls(page: Page) -> set[str]:
    """Snapshot every <video src> currently in the DOM."""
    srcs = page.eval_on_selector_all(
        "video",
        "els => els.map(e => e.currentSrc || e.src).filter(s => s && s.startsWith('http'))",
    )
    return {s for s in srcs if s}


def _auto_scroll(
    page: Page,
    max_videos: int,
    scroll_pause: float,
    idle_rounds: int,
    da_co: Callable[[list[str]], set[str]] | None = None,
) -> list[VideoRef]:
    """Scroll Ads Library and dedupe video URLs by asset id.

    Returns a list of VideoRef. Stops on: reaching `max_videos`, end of feed,
    or `idle_rounds` consecutive scrolls with no new asset.

    `da_co` (ids → tập id thư viện đã có): khi truyền, `max_videos` đếm video MỚI chứ không đếm cả cái
    đã có, với trần tổng `max_videos * HE_SO_TRAN_DA_CO` ref (chạm trần thì dừng — không cuộn vô hạn
    trên trang toàn video đã tải). Trả về MỌI ref thu được (cả cái đã có); người gọi lọc và cắt.
    """
    seen_keys: set[str] = set()
    owned: set[str] = set()
    refs: list[VideoRef] = []
    tran = max_videos * HE_SO_TRAN_DA_CO if da_co is not None else max_videos
    da_hoi = 0
    stale = 0
    # Số ref ở vòng thu TRƯỚC (None = chưa có vòng nào). "Có video mới không" phải đo SAU khi thu ở
    # vòng kế: DOM chỉ thêm video sau khi cuộn, và `refs` chỉ đổi ở bước thu. So `len(refs)` ngay sau
    # lệnh cuộn (chưa thu) luôn bằng nhau ⇒ `stale` tăng mọi vòng ⇒ dừng sau đúng `idle_rounds` lần cuộn.
    vong_truoc: int | None = None
    while True:
        for src in _collect_video_urls(page):
            key = _dedup_key(src)
            if key in seen_keys:
                continue
            ref = parse_fb_video_url(src)
            if ref is None:
                continue
            seen_keys.add(key)
            refs.append(ref)
        log.debug("scroll: %d unique videos", len(refs))

        if da_co is not None and da_hoi < len(refs):
            owned |= da_co([r.video_id for r in refs[da_hoi:]])
            da_hoi = len(refs)
        moi = len(refs) - len(owned)
        if (moi if da_co is not None else len(refs)) >= max_videos or len(refs) >= tran:
            log.info("reached --max=%d, stopping scroll", max_videos)
            break

        if vong_truoc is not None:
            if len(refs) > vong_truoc:
                stale = 0
            else:
                stale += 1
                if stale >= idle_rounds:
                    log.info("no new videos after %d idle rounds, stopping", stale)
                    break
        vong_truoc = len(refs)

        # JS scroll triggers FB's intersection observers (mouse.wheel often
        # misses the right container in obfuscated React DOM).
        page.evaluate(
            "window.scrollBy(0, Math.round(window.innerHeight * (0.7 + Math.random() * 0.3)))"
        )
        time.sleep(random.uniform(scroll_pause * 0.8, scroll_pause * 1.6))
    return refs[:tran]


def _open_context(
    pw, headless: bool, proxy: str | None, profile_dir: Path | None, user_agent: str,
) -> tuple[Browser | None, BrowserContext]:
    """Open a persistent or ephemeral Chromium context with stealth + UA."""
    common = dict(user_agent=user_agent, viewport={"width": 1400, "height": 900},
                  locale="en-US")
    proxy_cfg = {"server": proxy} if proxy else None
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir), headless=headless,
            proxy=proxy_cfg, **common,
        )
        ctx.add_init_script(STEALTH_INIT_JS)
        return None, ctx
    browser = pw.chromium.launch(headless=headless, proxy=proxy_cfg)
    ctx = browser.new_context(**common)
    ctx.add_init_script(STEALTH_INIT_JS)
    return browser, ctx


def scrape_ads_library(
    url: str,
    max_videos: int = 50,
    headless: bool = True,
    scroll_pause: float = 1.5,
    idle_rounds: int = 6,
    proxy: str | None = None,
    profile_dir: str | None = None,
    da_co: Callable[[list[str]], set[str]] | None = None,
) -> list[VideoRef]:
    """Open an Ads Library URL, scroll, and return up to `max_videos` unique refs.

    Defaults are conservative (50, idle 6) because FB is more rate-aggressive
    than TikTok — better to do two smaller passes than one suspicious sprint.
    """
    ua = random_user_agent()
    log.info("scraping FB ads library (max=%d, headless=%s, proxy=%s, profile=%s)",
             max_videos, headless, bool(proxy), bool(profile_dir))
    with sync_playwright() as pw:
        browser, ctx = _open_context(
            pw, headless=headless, proxy=proxy,
            profile_dir=Path(profile_dir) if profile_dir else None, user_agent=ua,
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector("video", timeout=15_000)
            except PWTimeout:
                log.warning("no <video> after 15s — Ads Library may need cookies "
                            "or your IP is being challenged")
            refs = _auto_scroll(page, max_videos, scroll_pause, idle_rounds, da_co=da_co)
        finally:
            ctx.close()
            if browser is not None:
                browser.close()
    log.info("collected %d unique video URLs", len(refs))
    return refs
