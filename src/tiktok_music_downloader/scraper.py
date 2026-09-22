"""Scrape a TikTok music page for video URLs via Playwright."""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Callable, Iterable

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Response,
    TimeoutError as PWTimeout,
    sync_playwright,
)

from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED,
    STOP_COMPLETE,
    STOP_HET_THOI_GIAN,
    STOP_HET_VONG,
    STOP_NGHI_BI_CHAN,
    STOP_SOURCE_EMPTY,
    STOP_STALLED,
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
        # KHÔNG trích nội dung. Một bản xuất "Header String" bắt đầu bằng
        # `sessionid=…`, nên `raw[:20]` ở đây từng đưa nguyên token vào thông
        # điệp lỗi — mà thông điệp đó chảy vào log của dịch vụ web
        # (`downloader.py` log.warning, `queue.py` log.exception) trên một máy
        # dùng chung. Nói LOẠI hỏng là đủ để người dùng sửa.
        raise ValueError(
            f"{path.name} doesn't look like JSON — it may be a 'Header String' "
            "or 'Netscape' export. Re-export from Cookie-Editor and pick JSON."
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Vị trí và lý do thì an toàn; 80 ký tự đầu thì không — với một tệp
        # cookie bị cắt cụt, 80 ký tự đầu chứa nguyên giá trị `sessionid`.
        raise ValueError(
            f"{path.name} is not valid JSON at line {exc.lineno} col {exc.colno}: "
            f"{exc.msg}"
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
    hrefs = page.eval_on_selector_all(
        _VIDEO_LINK_SELECTOR, "els => els.map(e => e.href)"
    )
    unparsed = 0
    for href in hrefs:
        ref = parse_video_url(href)
        if ref is None:
            unparsed += 1
            continue
        refs.add(ref)
    # Every href here matched `a[href*="/video/"]`, so one the parser rejects
    # is a URL shape we do not recognise — dropped with no other symptom than
    # fewer videos. Count it so --verbose shows the loss.
    if unparsed:
        log.debug("links: %d hrefs seen, %d not parsed", len(hrefs), unparsed)
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


def _warn_empty_feed(marker: str, status: int, how: str) -> None:
    log.warning(
        "%s answered HTTP %d with a 0-byte body (measured via %s): the "
        "response carried no items.",
        marker, status, how,
    )


def _watch_feed_api(page: Page, dem_trang: Callable[[], None] | None = None) -> None:
    """Log feed endpoints that answer with no body, and say when we can't tell.

    `dem_trang` is called once per feed response that actually carried a
    payload, which is how this branch pays into the daily index-page cap.
    Until 21/09 it paid NOTHING: `on_pages` was wired only on the hashtag
    path, so a music/search job recorded `so_trang = 0` while making just as
    many requests. The cap was not loose here, it was blind.

    One counted response = one request that answered with an array of videos,
    the same unit the hashtag path counts as a "page". Counting a whole
    multi-pass run as one page instead would undercount by however many times
    the scroller fetched, which on a long scroll is most of the traffic.

    Reports only what it read off the response: endpoint, HTTP status, byte
    count, and which measurement produced it. It draws no conclusion about WHY
    a feed is empty — cookies, rate limiting and a server-side gate look
    identical from here, and the caller knows the page type while this handler
    does not.

    The endpoint list is a snapshot of observed traffic, so absence of a
    warning is NOT proof the feeds were healthy; every `/api/` response is
    debug-logged so an unlisted feed endpoint shows up under --verbose.
    """

    def on_response(resp: Response) -> None:
        # Nothing may escape this listener. Playwright stores an escaped
        # exception and re-raises it on the NEXT channel call
        # (_connection.py: "Save the error to throw at the next API call"),
        # which would abort a scrape that had already collected refs.
        try:
            if "/api/" in resp.url:
                log.debug("api response %s -> %d", resp.url.split("?")[0], resp.status)

            marker = next((m for m in _FEED_API_MARKERS if m in resp.url), None)
            if marker is None:
                return

            # A redirect or a non-GET carries no feed payload of its own: a 302
            # with Content-Length: 0 is routine, and calling it an empty feed
            # would be a false alarm while the target returns items fine.
            if not (200 <= resp.status < 300) or resp.request.method != "GET":
                log.debug("feed %s: skipped HTTP %d %s",
                          marker, resp.status, resp.request.method)
                return

            # Đếm ở ĐÂY, ngay khi biết đây là một lượt feed thật (2xx, GET) —
            # trước mọi nhánh phân tích rỗng/không-rỗng bên dưới. Một lượt gọi
            # đã tiêu rồi thì nó tiêu, dù nó trả về rỗng: trần này đo LƯU LƯỢNG
            # mình đã tạo ra với TikTok, không đo mình thu được gì.
            if dem_trang is not None:
                dem_trang()

            declared = resp.header_value("content-length")
            encoding = (resp.header_value("content-encoding") or "").strip().lower()

            if declared == "0":
                # Encoding-independent: zero octets decode to nothing.
                _warn_empty_feed(marker, resp.status, "Content-Length: 0")
                return
            if declared is not None and declared.isdigit() and encoding in ("", "identity"):
                # Uncompressed, so the declared length IS the decoded length —
                # a non-zero value settles it without moving the payload.
                return
            # Either chunked (no length) or compressed, where Content-Length is
            # the COMPRESSED size: gzip of an empty body is still 20 bytes, so
            # the header cannot answer the question. Read the body.
            try:
                if len(resp.body()) == 0:
                    _warn_empty_feed(marker, resp.status, "body read")
            except Exception as exc:  # noqa: BLE001
                if "No data found for resource" in str(exc):
                    # Chromium keeps no retrievable body for a zero-length
                    # reply; it says the same for one it has already evicted,
                    # so this must not claim to know which.
                    log.warning(
                        "%s answered HTTP %d but its body could not be read "
                        "(%s). Chromium reports this both for a 0-byte body "
                        "and for a response it already dropped — this cannot "
                        "tell which.",
                        marker, resp.status, exc,
                    )
                else:
                    # Measured on a SUCCESSFUL /music/ run: a feed response
                    # landing during ctx.close() raises "Target page, context
                    # or browser has been closed". That says nothing about the
                    # feed, so warning here would cry wolf on the healthy path
                    # — and a warning users learn to ignore protects nobody.
                    log.debug("feed %s: HTTP %d, body unreadable (%s)",
                              marker, resp.status, exc)
        except Exception as exc:  # noqa: BLE001 — never escape the listener
            log.debug("feed watcher gave up on %s: %s", resp.url[:120], exc)

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
    dem_trang: Callable[[], None] | None = None,
) -> list[VideoRef]:
    """Open music page, scroll, return up-to-max unique VideoRefs (newest-first as rendered).

    `dem_trang` fires once per feed request this visit makes — see
    `_watch_feed_api`. Callers that meter a daily request budget must pass it;
    the CLI and the desktop GUI do not meter, so they leave it off.
    """
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
        _watch_feed_api(page, dem_trang)
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
    already_have: Callable[[list[str]], set[str]] | None = None,
    on_skip: Callable[[VideoRef], None] | None = None,
    on_stop: Callable[[str], None] | None = None,
    max_seconds: float | None = None,
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

    ---- Đào sâu tới khi đủ N video MỚI (21/09) ----

    `already_have` biến hàm này từ "gom N video" thành "gom N video mà THƯ VIỆN
    CHƯA CÓ" — đúng việc nhánh hashtag đã làm, và là thứ người dùng thật sự xin.
    Không có nó thì xin 50 mà trùng 30 sẽ về 20 và dừng, vì 50 "đã thấy" là đủ.

    ⚠ HAI BỘ ĐẾM, KHÔNG ĐƯỢC GỘP — chỗ này gộp là hỏng cả hai chiều:

      · `fresh` = chưa thấy Ở LƯỢT CHẠY NÀY → nuôi `rate` (độ mới). Nó trả lời
        *"nguồn còn đưa ra thứ chưa thấy không"*, tức câu hỏi CHỐNG CHẶN.
      · `moi`  = chưa có trong THƯ VIỆN → đếm về `max_videos`. Nó trả lời
        *"đã đủ hàng cho người dùng chưa"*, tức câu hỏi CÔNG VIỆC.

    Nhét "mới với thư viện" vào mẫu số của `rate` thì: chia cho batch gốc ⇒ một
    lượt toàn video đã có cho `rate` thấp giả ⇒ DỪNG SỚM SAI đúng lúc cần đào
    tiếp; chia cho batch đã lọc ⇒ mẫu số co theo tử số ⇒ `rate` không bao giờ
    xuống ⇒ CHẠY TỚI KỊCH TRẦN. Cả hai đều là hỏng âm thầm.

    `max_seconds` là trần thời gian cả lượt (user chốt 10 phút). Kiểm TRƯỚC khi
    ngủ giữa hai lượt: ngủ 60-180s rồi mới phát hiện hết giờ là vứt đi đúng
    khoảng thời gian vừa chờ.
    """
    if passes < 1:
        passes = 1
    passes = min(passes, 5)  # hard cap; >5 is "spray-and-pray" territory.

    bat_dau = time.monotonic()
    da_thay: set[str] = set()          # mới với LƯỢT CHẠY NÀY
    moi: dict[str, VideoRef] = {}      # mới với THƯ VIỆN, giữ thứ tự gặp
    bo_qua = 0                         # số video bỏ vì thư viện đã có
    ly_do = STOP_COMPLETE
    # Số lượt ĐÃ CÀO THẬT, không phải số lượt đã thử. Hai con số lệch nhau ở
    # đúng ca trần thời gian cắt TRƯỚC khi `scrape_music_page` kịp chạy: dùng
    # `i + 1` cho câu log cuối sẽ báo dư một lượt chưa từng xảy ra. Một dòng
    # log khai nhiều hơn thứ nó đo được là thứ người sau sẽ trích như số đo.
    da_cao = 0

    def _con_lai() -> float | None:
        if max_seconds is None:
            return None
        return max_seconds - (time.monotonic() - bat_dau)

    for i in range(passes):
        if i > 0:
            delay = random.uniform(pass_delay_min, pass_delay_max)
            con = _con_lai()
            if con is not None and con <= delay:
                # Không ngủ một giấc mà mình đã biết là sẽ không kịp tỉnh.
                log.info("hết trần thời gian (%.0fs) trước lượt %d — dừng",
                         max_seconds, i + 1)
                ly_do = STOP_HET_THOI_GIAN
                break
            log.info(
                "pass %d/%d: waiting %.0fs to avoid rate-limit pattern…",
                i + 1, passes, delay,
            )
            time.sleep(delay)

        log.info("=== pass %d/%d ===", i + 1, passes)
        # CỬA SỔ QUÉT phải SÂU DẦN, nếu không "đào sâu" chỉ là quét lại chỗ cũ.
        #
        # `_auto_scroll` ngừng cuộn ngay khi THẤY đủ `max_videos` video — nó
        # đếm video THÔ, không biết gì về thư viện. Truyền cùng một
        # `max_videos` cho mọi lượt thì lượt 2..5 dừng lại ở đúng cửa sổ lượt 1
        # đã dừng, và nếu thư viện đã có trọn cửa sổ đó thì mọi lượt đều về 0
        # video mới — rồi lý do dừng thành `already_owned` ("đổi nguồn, chạy
        # lại chắc chắn vô ích") trong khi phần chưa ai có nằm ngay dưới mép
        # cuộn. Đó là hỏng ÂM THẦM đúng trong ca tính năng này sinh ra để chữa.
        #
        # Muốn có thêm `còn_thiếu` video mới thì phải cuộn qua hết những cái đã
        # thấy rồi mới tới phần chưa thấy ⇒ mục tiêu thô = đã_thấy + còn_thiếu.
        # NỚI GẤP ĐÔI, không nới theo số còn thiếu.
        #
        # Bản đầu dùng `đã_thấy + còn_thiếu`, tức nới TUYẾN TÍNH mỗi lượt đúng
        # bằng phần hụt. Đo 21/09, trang 200 video mà thư viện đã có 40 cái
        # ĐẦU, xin 10 mới: cửa sổ đi 10 → 20 → 30 → 40 rồi hết lượt ⇒ **0
        # video mới**, trong khi 160 cái chưa ai có nằm ngay dưới. Phần đầu
        # trang mà thư viện đã có dài bao nhiêu là chuyện của thư viện, KHÔNG
        # liên quan gì tới số người dùng xin — nên lấy số xin làm bước nhảy là
        # lấy sai đại lượng.
        #
        # Gấp đôi thì vượt một tiền tố đã-có dài N sau khoảng log2(N) lượt:
        # 40 cái đã có bị bỏ lại ngay ở lượt 3 thay vì lượt 5.
        con_thieu = max_videos - len(moi)
        muc_tieu_tho = max(max_videos, (len(da_thay) + con_thieu) * 2)
        batch = scrape_music_page(music_url, max_videos=muc_tieu_tho, **kwargs)
        if not batch:
            # Lượt ĐẦU ra 0 = nguồn chưa bao giờ đưa gì (link sai/hết hạn).
            # Lượt SAU ra 0 = nó đang đưa rồi ngừng ⇒ nghi bị chặn mềm. Hai ca
            # này khuyên người dùng hai việc ngược nhau, nên không được gộp.
            if i == 0:
                log.warning("lượt đầu ra 0 video — nguồn không đưa ra gì")
                ly_do = STOP_SOURCE_EMPTY
            else:
                log.warning("lượt %d ra 0 video — nghi bị chặn mềm, dừng", i + 1)
                ly_do = STOP_NGHI_BI_CHAN
            break

        da_cao += 1
        fresh = [r for r in batch if r.video_id not in da_thay]
        da_thay.update(r.video_id for r in fresh)
        # Mẫu số là CẢ RỔ, cố ý giữ nguyên.
        #
        # Có một bản vá thử đổi mẫu số thành "phần cửa sổ vừa nới thêm", với lý
        # do nghe rất xuôi: cửa sổ nới dần nên `batch` là tập cha của lượt
        # trước, mẫu số phình mà tử số thì không. Đo lại thì bản đó SAI hai lần:
        #   · không test nào cần nó — đột biến hoàn nguyên nó vẫn XANH, vì phép
        #     nới GẤP ĐÔI đã giữ tỉ lệ trên ngưỡng rồi;
        #   · và nó PHÁ đường GUI (`gui.py`), nơi cửa sổ KHÔNG nới: ở đó
        #     `len(batch) - đã_thấy_trước = 0` ⇒ mẫu số rơi về 1 ⇒ `rate` luôn
        #     ≥ 1 ⇒ cửa "lợi ích giảm dần" KHÔNG BAO GIỜ đóng, và bản desktop
        #     quét đủ 5 lượt mỗi lần. Đo: batch 50, đã thấy 50, mới 10 ⇒ cũ
        #     0,20 (dừng, đúng ý) · mới 10,0 (chạy tiếp mãi).
        # Một bản vá không ai cần mà lại đổi hành vi một đường không ai yêu cầu
        # sửa thì không phải bản vá.
        rate = len(fresh) / len(batch)

        owned = already_have([r.video_id for r in fresh]) if (already_have and fresh) else set()
        for ref in fresh:
            if ref.video_id in owned:
                bo_qua += 1
                if on_skip is not None:
                    # Video bị bỏ qua không bao giờ đi tiếp vào đường tải, nên
                    # đây là lúc DUY NHẤT nguồn lần này của nó còn quan sát được.
                    on_skip(ref)
            elif ref.video_id not in moi:
                moi[ref.video_id] = ref

        log.info(
            "pass %d/%d: %d/%d mới với lượt này (%.0f%%), %d mới với thư viện, "
            "%d đã có — cộng dồn %d/%d",
            i + 1, passes, len(fresh), len(batch), rate * 100,
            len(moi), bo_qua, len(moi), max_videos,
        )

        if len(moi) >= max_videos:
            log.info("đủ %d video mới, dừng", max_videos)
            ly_do = STOP_COMPLETE
            break
        con = _con_lai()
        if con is not None and con <= 0:
            log.info("hết trần thời gian sau lượt %d", i + 1)
            ly_do = STOP_HET_THOI_GIAN
            break
        if i > 0 and rate < min_new_rate:
            log.info(
                "độ mới %.0f%% < ngưỡng %.0f%% — nguồn cạn dần, dừng",
                rate * 100, min_new_rate * 100,
            )
            ly_do = STOP_STALLED
            break
    else:
        if len(moi) < max_videos:
            ly_do = STOP_HET_VONG

    # Nâng cấp lý do — chép nguyên tắc của nhánh hashtag
    # (`hashtag_enumerator.py`): dừng vì hết giờ/hết vòng/cạn dần mà KHÔNG gom
    # được video mới nào trong khi nguồn vẫn đưa ra video, thì lý do thật không
    # phải "hết giờ" — nó là "thư viện đã có hết những gì nguồn đưa". Hai ca
    # bảo người dùng hai việc ngược nhau: một cái bảo ĐỔI NGUỒN (chạy lại chắc
    # chắn vô ích), một cái bảo CHẠY LẠI (có thể ra thêm).
    if ly_do in (STOP_HET_THOI_GIAN, STOP_HET_VONG, STOP_STALLED) and not moi and bo_qua:
        ly_do = STOP_ALREADY_OWNED

    if on_stop is not None and ly_do != STOP_COMPLETE:
        on_stop(ly_do)

    # Giữ nguyên phép sắp xếp của bản cũ (`video_id` giảm dần ≈ mới nhất trước):
    # khi `already_have` không được truyền — đường CLI và GUI desktop — hàm này
    # phải trả về ĐÚNG như trước, kể cả thứ tự. Đổi thứ tự ở đây là đổi thứ tự
    # tải của một công cụ không ai yêu cầu sửa.
    ket_qua = sorted(moi.values(), key=lambda r: r.video_id, reverse=True)[:max_videos]
    log.info("multipass: %d video mới qua %d lượt đã cào, lý do dừng=%r",
             len(ket_qua), da_cao, ly_do or "đủ")
    return ket_qua


def iter_refs(refs: Iterable[VideoRef]) -> Iterable[VideoRef]:
    return iter(refs)
