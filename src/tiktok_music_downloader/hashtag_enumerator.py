"""Enumerate the videos under a TikTok hashtag.

Why this module exists instead of scraping the page like every other source:
TikTok answers `/api/challenge/item_list/` with HTTP 200 and a **zero-length
body**. Measured 2026-09-08 and 2026-09-09 across headless, headful,
anonymous, a logged-in cookies file, a persistent browser profile, two
hashtags and two machines, while `/api/music/item_list/` returned 30 items
under identical conditions. yt-dlp reaches the same wall from the other side:
its `tiktok:tag` extractor is flagged `_WORKING = False`, and forcing app-info
args gets past the argument check only to receive the same empty body from the
mobile `challenge/aweme` endpoint. So the hashtag feed is not obtainable from
TikTok directly right now, by us or by anyone.

What works: a third-party index (tikwm) still lists a hashtag's videos, and
yt-dlp's single-video extractor still downloads each one. Only the **public
hashtag name** leaves this machine — never a cookie, a session or a file.

`_provider_page` is the seam. tikwm is unofficial and may disappear; when it does,
replace that one function and the rest of the tool is unaffected.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from tiktok_music_downloader.utils import VideoRef

log = logging.getLogger("ttmd")

# TikTok still server-renders the numeric challenge id for a crawler UA, even
# though the same page gives a browser an empty feed.
_CRAWLER_UA = ("facebookexternalhit/1.1 "
               "(+http://www.facebook.com/externalhit_uatext.php)")
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
_CHALLENGE_ID_RE = re.compile(rb"challenge/detail/(\d+)")
_PROVIDER_URL = "https://www.tikwm.com/api/challenge/posts"
_PAGE_SIZE = 30
_REQUEST_GAP_SECONDS = 1.2   # provider's free tier is about one request/second
_STALL_PAGES = 2             # consecutive pages adding nothing before giving up


def _fetch(url: str, user_agent: str, timeout: float = 25.0,
           proxy: str | None = None) -> bytes | None:
    """GET url, or None. Tests replace this; nothing else does network I/O.

    `proxy` is threaded through because the caller may have set one precisely
    so that their own address is never exposed — listing must honour it just
    like the download step does.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        if proxy:
            op = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            with op.open(req, timeout=timeout) as resp:
                return resp.read()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        log.warning("request to %s failed: %s", urllib.parse.urlsplit(url).netloc, exc)
        return None


def resolve_challenge_id(tag: str, proxy: str | None = None) -> str | None:
    """Map a hashtag name to TikTok's numeric challenge id.

    Refuses when the page offers more than one distinct id rather than taking
    the first: picking wrong would enumerate somebody else's hashtag and look
    like a success. Measured 2026-09-09 on #anos80 — the crawler page carried
    4 occurrences of exactly 1 id, so the single-id case is the normal one.
    """
    # The slug arrives already percent-encoded when pasted from a browser, so
    # decode before re-encoding: quoting it twice asks for a different tag.
    safe_tag = urllib.parse.quote(urllib.parse.unquote(tag), safe="")
    body = _fetch(f"https://www.tiktok.com/tag/{safe_tag}", _CRAWLER_UA, proxy=proxy)
    if body is None:
        return None
    ids = {m.decode() for m in _CHALLENGE_ID_RE.findall(body)}
    if not ids:
        log.warning("no challenge id in the page for #%s (%d bytes) — TikTok may "
                    "have changed the crawler page, or the hashtag is empty",
                    tag, len(body))
        return None
    if len(ids) > 1:
        log.warning("page for #%s offers %d different challenge ids (%s); refusing "
                    "to guess which one is this hashtag", tag, len(ids), ", ".join(sorted(ids)))
        return None
    return ids.pop()


def _provider_page(challenge_id: str, cursor: int,
                   proxy: str | None = None) -> tuple[list[VideoRef], int, bool, bool]:
    """One page from the provider: (refs, next_cursor, has_more, ok).

    `ok` is separate from `has_more` on purpose: a failed request and a genuine
    last page both yield no refs, and reporting the first as the second would
    turn a truncated list into an apparent complete one.

    THE SEAM. Swap this function to change indexes; callers only see VideoRefs.
    """
    query = urllib.parse.urlencode(
        {"challenge_id": challenge_id, "count": _PAGE_SIZE, "cursor": cursor})
    body = _fetch(f"{_PROVIDER_URL}?{query}", _BROWSER_UA, timeout=30.0, proxy=proxy)
    if body is None:
        return [], cursor, False, False
    try:
        payload = json.loads(body) or {}
    except json.JSONDecodeError as exc:
        log.warning("index returned %d bytes that are not JSON: %s", len(body), exc)
        return [], cursor, False, False

    data = payload.get("data")
    if not isinstance(data, dict):
        # tikwm answers rate limiting with HTTP 200 and {"code":-1,"msg":...};
        # that message is the actionable part, so it must not be swallowed.
        log.warning("index returned no data (code=%r msg=%r)",
                    payload.get("code"), payload.get("msg"))
        return [], cursor, False, False

    refs: list[VideoRef] = []
    try:
        for item in data.get("videos") or []:
            if not isinstance(item, dict):
                continue
            vid = str(item.get("video_id") or "").strip()
            if not vid.isdigit():
                continue
            author = item.get("author")
            handle = str((author or {}).get("unique_id") or "") if isinstance(author, dict) else ""
            if not handle:
                continue    # without a handle the post URL cannot be built
            refs.append(VideoRef(
                video_id=vid,
                url=f"https://www.tiktok.com/@{handle}/video/{vid}"))
        next_cursor = int(data.get("cursor") or 0)
    except (AttributeError, TypeError, ValueError) as exc:
        # The index is unofficial; the day its shape changes must not surface
        # as a Python traceback in the user's face.
        log.warning("index payload has an unexpected shape (%s) — treating this "
                    "page as unusable", exc)
        return [], cursor, False, False
    return refs, next_cursor, bool(data.get("hasMore")), True


def enumerate_hashtag(tag: str, max_videos: int = 200, max_pages: int = 40,
                      proxy: str | None = None) -> list[VideoRef]:
    """Return up to max_videos unique VideoRefs for a hashtag.

    An empty list means the hashtag could not be enumerated, and a SHORT list
    means the run stopped early — both say so at WARNING. It never reports a
    complete listing it did not observe.
    """
    if max_videos <= 0:
        return []
    challenge_id = resolve_challenge_id(tag, proxy=proxy)
    if challenge_id is None:
        return []
    log.info("hashtag #%s -> challenge_id %s", tag, challenge_id)

    seen: set[str] = set()
    refs: list[VideoRef] = []
    cursor = 0
    stalled = 0
    truncated_because = None

    for page in range(1, max_pages + 1):
        page_refs, cursor, has_more, ok = _provider_page(challenge_id, cursor, proxy=proxy)
        if not ok:
            truncated_because = "the index failed to answer"
            break
        added = 0
        for ref in page_refs:
            if ref.video_id in seen:
                continue
            seen.add(ref.video_id)
            refs.append(ref)
            added += 1
            if len(refs) >= max_videos:
                break
        log.info("page %d: %d listed, %d new, %d total", page, len(page_refs), added, len(refs))
        if len(refs) >= max_videos:
            break
        if not has_more:
            log.info("index reports no more pages for #%s", tag)
            break
        # `has_more` has been observed true on a page that added nothing, so a
        # run of such pages is a stall, not progress towards the target.
        stalled = stalled + 1 if added == 0 else 0
        if stalled >= _STALL_PAGES:
            truncated_because = (f"the index kept reporting more pages while adding "
                                 f"nothing for {stalled} pages")
            break
        time.sleep(_REQUEST_GAP_SECONDS)
    else:
        if len(refs) < max_videos:
            truncated_because = f"the page cap ({max_pages}) was reached"

    if not refs:
        log.warning("no videos listed for #%s. TikTok's own hashtag feed returns "
                    "an empty body, so this tool relies on an external index; "
                    "that index answered with nothing usable.", tag)
    elif truncated_because and len(refs) < max_videos:
        log.warning("listing for #%s is INCOMPLETE: asked for %d, got %d, because "
                    "%s.", tag, max_videos, len(refs), truncated_because)
    return refs[:max_videos]
