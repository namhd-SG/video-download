"""Scrape a TikTok music page for video URLs via Playwright."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterable

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
    parse_video_url,
    random_user_agent,
)

log = logging.getLogger("ttmd")

# Video anchors on a music page render as <a href="https://www.tiktok.com/@user/video/123...">
_VIDEO_LINK_SELECTOR = 'a[href*="/video/"]'


def _collect_links(page: Page) -> set[VideoRef]:
    """Snapshot all currently rendered video links on the page."""
    refs: set[VideoRef] = set()
    for href in page.eval_on_selector_all(
        _VIDEO_LINK_SELECTOR, "els => els.map(e => e.href)"
    ):
        ref = parse_video_url(href)
        if ref is not None:
            refs.add(ref)
    return refs


def _auto_scroll(
    page: Page,
    max_videos: int,
    scroll_pause: float,
    idle_rounds: int,
) -> set[VideoRef]:
    """Scroll until target reached, end of feed, or `idle_rounds` with no growth."""
    seen: set[VideoRef] = set()
    stale = 0
    while True:
        new_batch = _collect_links(page)
        before = len(seen)
        seen |= new_batch
        log.debug("scroll: %d unique (added %d)", len(seen), len(seen) - before)

        if len(seen) >= max_videos:
            log.info("reached --max=%d, stopping scroll", max_videos)
            break

        if len(seen) == before:
            stale += 1
            if stale >= idle_rounds:
                log.info("no new videos after %d idle rounds, stopping", stale)
                break
        else:
            stale = 0

        page.mouse.wheel(0, 4000)
        time.sleep(scroll_pause)

    return seen


def _open_context(
    pw,
    headless: bool,
    proxy: str | None,
    profile_dir: Path | None,
    user_agent: str,
) -> tuple[Browser | None, BrowserContext]:
    """Open a persistent or ephemeral Chromium context with stealth + UA."""
    common_kwargs = dict(
        user_agent=user_agent,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    proxy_cfg = {"server": proxy} if proxy else None

    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            proxy=proxy_cfg,
            **common_kwargs,
        )
        ctx.add_init_script(STEALTH_INIT_JS)
        return None, ctx

    browser = pw.chromium.launch(headless=headless, proxy=proxy_cfg)
    ctx = browser.new_context(**common_kwargs)
    ctx.add_init_script(STEALTH_INIT_JS)
    return browser, ctx


def scrape_music_page(
    music_url: str,
    max_videos: int = 200,
    headless: bool = True,
    scroll_pause: float = 1.5,
    idle_rounds: int = 4,
    cookies_path: str | None = None,
    proxy: str | None = None,
    profile_dir: str | None = None,
) -> list[VideoRef]:
    """Open music page, scroll, return up-to-max unique VideoRefs (newest-first as rendered)."""
    ua = random_user_agent()
    log.info(
        "scraping %s (max=%d, headless=%s, proxy=%s, profile=%s)",
        music_url,
        max_videos,
        headless,
        bool(proxy),
        bool(profile_dir),
    )

    with sync_playwright() as pw:
        browser, ctx = _open_context(
            pw,
            headless=headless,
            proxy=proxy,
            profile_dir=Path(profile_dir) if profile_dir else None,
            user_agent=ua,
        )
        if cookies_path:
            import json

            ctx.add_cookies(json.loads(Path(cookies_path).read_text()))

        page = ctx.new_page()
        try:
            page.goto(music_url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector(_VIDEO_LINK_SELECTOR, timeout=15_000)
            except PWTimeout:
                log.warning("no video links after 15s — try --headful or --cookies")

            refs = _auto_scroll(page, max_videos, scroll_pause, idle_rounds)
        finally:
            ctx.close()
            if browser is not None:
                browser.close()

    ordered = sorted(refs, key=lambda r: r.video_id, reverse=True)[:max_videos]
    log.info("collected %d unique video URLs", len(ordered))
    return ordered


def iter_refs(refs: Iterable[VideoRef]) -> Iterable[VideoRef]:
    return iter(refs)
