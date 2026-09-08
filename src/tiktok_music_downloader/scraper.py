"""Scrape a TikTok music page for video URLs via Playwright."""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Iterable

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Response,
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

# Cookie-Editor / EditThisCookie export keys mapped to Playwright's expected keys.
# Playwright rejects unknown fields and uses different names / sameSite values, so
# we normalize on load to avoid `add_cookies()` errors.
_SAMESITE_MAP = {
    "no_restriction": "None",
    "unspecified": "Lax",
    "lax": "Lax",
    "strict": "Strict",
    "none": "None",
}
_PW_COOKIE_KEYS = {
    "name", "value", "domain", "path", "url",
    "expires", "httpOnly", "secure", "sameSite",
}


def _normalize_cookie(raw: dict) -> dict:
    """Coerce one cookie dict from common exporter formats into Playwright shape."""
    c: dict = {}
    for k, v in raw.items():
        if k == "expirationDate":
            c["expires"] = int(v)
        elif k == "sameSite":
            c["sameSite"] = _SAMESITE_MAP.get(str(v).lower(), "Lax")
        elif k in _PW_COOKIE_KEYS:
            c[k] = v
    # Playwright needs either url or domain — strip leading dot is fine for it,
    # but some exports omit it for host-only cookies; fall back to the value.
    if "domain" not in c and "url" not in c:
        return {}
    return c


def _load_cookies(path: Path) -> list[dict]:
    """Read JSON cookies file and return a list Playwright can accept.

    Common user mistakes (RTF save, BOM, Cookie-Editor "Header String" format)
    are detected upfront so the error message points to a fix, not at a cryptic
    JSON parser position.
    """
    import json

    raw = path.read_text(encoding="utf-8", errors="replace").lstrip("﻿").lstrip()
    if raw.startswith(r"{\rtf"):
        raise ValueError(
            f"{path.name} looks like Rich Text (RTF), not JSON. In TextEdit do "
            "Format → Make Plain Text (Cmd+Shift+T) before pasting cookies and "
            "saving."
        )
    if not raw.startswith(("[", "{")):
        raise ValueError(
            f"{path.name} doesn't look like JSON (starts with {raw[:20]!r}). "
            "Re-export from Cookie-Editor and pick the JSON format, not 'Header "
            "String' or 'Netscape'."
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path.name} is not valid JSON at line {exc.lineno} col {exc.colno}: "
            f"{exc.msg}. First 80 chars: {raw[:80]!r}"
        ) from exc

    # storage_state format: {"cookies": [...], "origins": [...]} — unwrap it.
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    if not isinstance(data, list):
        raise ValueError(
            f"{path.name}: expected a JSON array of cookies, got {type(data).__name__}."
        )
    cookies = [_normalize_cookie(c) for c in data if isinstance(c, dict)]
    cookies = [c for c in cookies if c.get("name") and c.get("value")]
    log.info("loaded %d cookies from %s", len(cookies), path.name)
    return cookies


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


# Feed endpoints, one per page type. TikTok answers these with HTTP 200 and a
# ZERO-LENGTH body when it withholds a feed, so every request looks healthy
# while the page renders nothing at all. We watch for exactly that shape and
# log it where it happens, so a zero-video scrape reports which side dropped
# the data instead of sending the user off to re-export cookies.
_FEED_API_MARKERS = (
    "/api/challenge/item_list",   # hashtag page  (/tag/<slug>)
    "/api/search/general",        # search page   (/search?q=...)
    "/api/music/item_list",       # music page    (/music/...)
)


def _watch_feed_api(page: Page) -> None:
    """Log feed endpoints that answer with no body, and say when we can't tell.

    Reports only what it read off the response: the endpoint, the HTTP status,
    the byte count, and which of the two measurements produced it. It draws no
    conclusion about WHY the body is empty — cookies, rate limiting and a
    server-side gate all look identical from here, and the caller knows the
    page type while this handler does not.

    Two measurements, because they cover different response framings:
      - `Content-Length: 0` is a positive detection and costs no transfer.
      - Chunked replies carry no length, so fall back to reading the body.
    Chromium keeps no retrievable body for some zero-length and all redirect
    responses, so `body()` raises there; that is logged at debug level rather
    than swallowed, so a blind detector shows up under --verbose instead of
    looking like a healthy feed.
    """

    def on_response(resp: Response) -> None:
        marker = next((m for m in _FEED_API_MARKERS if m in resp.url), None)
        if marker is None:
            return

        if resp.header_value("content-length") == "0":
            size, how = 0, "Content-Length"
        else:
            try:
                size, how = len(resp.body()), "body read"
            except Exception as exc:  # noqa: BLE001 — record it, never swallow
                log.debug(
                    "feed %s: HTTP %d, body unreadable (%s) — cannot tell "
                    "empty from full for this response",
                    marker, resp.status, exc,
                )
                return

        if size == 0:
            log.warning(
                "%s answered HTTP %d with a 0-byte body (measured via %s): "
                "the response carried no items.",
                marker, resp.status, how,
            )

    page.on("response", on_response)


# JS helper: find the actual scrollable container (TikTok search uses an inner
# div with its own overflow, not the document body). We probe all elements
# and return the largest one whose scrollHeight exceeds its clientHeight.
_FIND_SCROLLER_JS = """
() => {
  const all = document.querySelectorAll('*');
  let best = null, bestExtra = 0;
  for (const el of all) {
    const s = getComputedStyle(el);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
        el.scrollHeight > el.clientHeight + 50) {
      const extra = el.scrollHeight - el.clientHeight;
      if (extra > bestExtra) { best = el; bestExtra = extra; }
    }
  }
  return best
    ? { kind: 'inner', height: best.scrollHeight, client: best.clientHeight }
    : { kind: 'window', height: document.scrollingElement.scrollHeight,
        client: window.innerHeight };
}
"""

_SCROLL_DOWN_JS = """
() => {
  const all = document.querySelectorAll('*');
  let best = null, bestExtra = 0;
  for (const el of all) {
    const s = getComputedStyle(el);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
        el.scrollHeight > el.clientHeight + 50) {
      const extra = el.scrollHeight - el.clientHeight;
      if (extra > bestExtra) { best = el; bestExtra = extra; }
    }
  }
  const target = best || document.scrollingElement;
  const step = Math.round(window.innerHeight * (0.8 + Math.random() * 0.3));
  target.scrollBy(0, step);
  return target.scrollHeight;
}
"""


def _auto_scroll(
    page: Page,
    max_videos: int,
    scroll_pause: float,
    idle_rounds: int,
) -> set[VideoRef]:
    """Scroll until target reached, end of feed, or `idle_rounds` with no growth.

    Handles both layouts TikTok uses:
      - Music page: document.body itself scrolls (window.scrollBy works).
      - /search?q=…: an inner <div> with overflow:auto holds the results, so
        scrolling the window has no effect. We probe at runtime for the
        largest overflow:scroll element and target it directly.
    Additionally we dispatch mouse.wheel events at the viewport centre —
    real wheel events fire IntersectionObservers attached deep inside React,
    which JS scrolling sometimes misses.
    """
    seen: set[VideoRef] = set()
    stale = 0
    last_height = 0
    # Detect layout once up front so log shows which path we picked.
    layout = page.evaluate(_FIND_SCROLLER_JS)
    log.debug("scroll layout: %s", layout)

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

        # Scroll the right container (inner div on /search, body on /music).
        cur_height = int(page.evaluate(_SCROLL_DOWN_JS) or 0)
        # ALSO emit a real wheel event at viewport centre — some lazy-load
        # observers only listen for wheel/touch, not programmatic scrollBy.
        try:
            page.mouse.move(700, 450)
            page.mouse.wheel(0, 1200)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(random.uniform(scroll_pause * 0.8, scroll_pause * 1.6))

        # Real end-of-feed signal: scrollHeight of the active scroller stops
        # growing for half an idle window AND no new links appeared.
        if cur_height == last_height and stale >= idle_rounds // 2:
            log.info("scroller stuck at height %d for %d rounds — end of feed",
                     cur_height, stale)
            break
        last_height = cur_height

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
    idle_rounds: int = 12,
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
            ctx.add_cookies(_load_cookies(Path(cookies_path)))

        page = ctx.new_page()
        _watch_feed_api(page)
        try:
            page.goto(music_url, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector(_VIDEO_LINK_SELECTOR, timeout=15_000)
            except PWTimeout:
                # Neutral wording on purpose: the 0-byte feed warning above
                # (if any) already names the real cause; cookies/headful are
                # only worth trying when the server DID send items.
                log.warning(
                    "no video links rendered after 15s — if a '0-byte body' "
                    "warning appeared above, the server sent no items; "
                    "otherwise try --headful or --cookies"
                )

            refs = _auto_scroll(page, max_videos, scroll_pause, idle_rounds)
        finally:
            ctx.close()
            if browser is not None:
                browser.close()

    ordered = sorted(refs, key=lambda r: r.video_id, reverse=True)[:max_videos]
    log.info("collected %d unique video URLs", len(ordered))
    return ordered


def scrape_music_page_multi(
    music_url: str,
    passes: int = 1,
    pass_delay_min: float = 60.0,
    pass_delay_max: float = 180.0,
    min_new_rate: float = 0.30,
    max_videos: int = 200,
    **kwargs,
) -> list[VideoRef]:
    """Run scrape_music_page N times, dedupe, with anti-block safeguards.

    Rationale: a TikTok music page renders a randomized ~30-60 video slice per
    visit, so multiple visits accumulate more unique IDs. But hammering the
    same URL is the #1 bot signal, so we:

      - cap passes (caller should keep ≤3, this fn enforces ≥1)
      - close the browser context fully between passes (each scrape_music_page
        call opens & closes its own context) so each pass looks like a fresh
        session, not a tab in the same session.
      - sleep `pass_delay_min..max` seconds (jittered) between passes — long
        enough to fall outside short-window rate counters.
      - stop early on diminishing returns (new-rate < `min_new_rate`) or on a
        zero-result pass (likely soft block — back off, don't retry).

    On account-flag risk: even with these safeguards, doing many passes with
    the SAME logged-in cookies is the riskiest variant. Prefer ephemeral
    context (no cookies) for passes ≥ 2 if the user is worried about their
    account. Right now we don't downgrade cookies between passes — caller can
    choose to omit cookies_path for safer multipass.
    """
    if passes < 1:
        passes = 1
    passes = min(passes, 5)  # hard cap; >5 is "spray-and-pray" territory.

    all_refs: set[VideoRef] = set()
    for i in range(passes):
        before = len(all_refs)
        if i > 0:
            delay = random.uniform(pass_delay_min, pass_delay_max)
            log.info(
                "pass %d/%d: waiting %.0fs to avoid rate-limit pattern…",
                i + 1, passes, delay,
            )
            time.sleep(delay)

        log.info("=== pass %d/%d ===", i + 1, passes)
        batch = scrape_music_page(music_url, max_videos=max_videos, **kwargs)
        if not batch:
            log.warning("pass %d returned 0 videos — likely soft block, stopping", i + 1)
            break

        all_refs.update(batch)
        added = len(all_refs) - before
        rate = added / len(batch) if batch else 0.0
        log.info(
            "pass %d/%d: +%d new (%d/%d = %.0f%% novel), total unique %d",
            i + 1, passes, added, added, len(batch), rate * 100, len(all_refs),
        )

        if len(all_refs) >= max_videos:
            log.info("reached max_videos=%d across passes, stopping", max_videos)
            break
        if i > 0 and rate < min_new_rate:
            log.info(
                "novelty %.0f%% < %.0f%% threshold — diminishing returns, stopping",
                rate * 100, min_new_rate * 100,
            )
            break

    ordered = sorted(all_refs, key=lambda r: r.video_id, reverse=True)[:max_videos]
    log.info("multipass total: %d unique videos across %d passes",
             len(ordered), min(i + 1, passes))
    return ordered


def iter_refs(refs: Iterable[VideoRef]) -> Iterable[VideoRef]:
    return iter(refs)
