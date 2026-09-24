"""Offline tests for the one-shot session warm-up in `_mo_trang_co_ham_phien`.

The fake page replays, per `goto`, the response sequence recorded on a real
headless search run on 25/09 (`~/agy-ws/exchange/search-rong-R7-data/
dev-p2-dev-E.log`): first visit → `/api/search/general/full/` 200 with
Content-Length 0 next to a `preview` that DOES carry bytes; second visit in
the same context → `full` with a body. The real `_watch_feed_api` counts the
responses, so these tests exercise the same measurement the scraper uses.
"""
from __future__ import annotations

import logging

from playwright.sync_api import TimeoutError as PWTimeout

from tiktok_music_downloader import scraper
from tiktok_music_downloader.scraper import _mo_trang_co_ham_phien, _watch_feed_api

SEARCH_URL = "https://www.tiktok.com/search?q=Strom%20AI%20trend"
PROFILE_URL = "https://www.tiktok.com/@fdcvhuy"
MUSIC_URL = "https://www.tiktok.com/music/She-Drives-Me-Crazy-6700000000000000000"
API = "https://www.tiktok.com"
VIDEO_HREFS = [f"https://www.tiktok.com/@u/video/74{i:017d}" for i in range(3)]


class _Req:
    method = "GET"


class _Resp:
    def __init__(self, path: str, *, content_length: str | None = None,
                 encoding: str | None = None, body: bytes = b"",
                 unreadable: bool = False) -> None:
        self.url = API + path + "?msToken=x"
        self.status = 200
        self.request = _Req()
        self._cl, self._ce, self._body = content_length, encoding, body
        self._unreadable = unreadable

    def header_value(self, name: str) -> str | None:
        return {"content-length": self._cl, "content-encoding": self._ce}.get(name)

    def body(self) -> bytes:
        if self._unreadable:
            raise RuntimeError("Protocol error: No data found for resource with given identifier")
        return self._body


def _empty_first_visit(feed_path: str) -> list[_Resp]:
    """Lượt 1 thật: feed 0 byte (Content-Length: 0), endpoint gợi ý có byte."""
    return [
        _Resp("/tiktok/ppf/api/eligibility/v2", content_length="120"),
        _Resp(feed_path, content_length="0"),
        _Resp("/api/search/suggest/guide/", content_length="153"),
        _Resp("/api/search/general/preview/", content_length="772"),
    ]


def _full_second_visit(feed_path: str, nbytes: int = 207477) -> list[_Resp]:
    """Lượt 2 thật: feed nén/chunked (không Content-Length) có thân."""
    return [
        _Resp("/tiktok/ppf/api/eligibility/v2", content_length="120"),
        _Resp("/api/search/suggest/guide/", content_length="153"),
        _Resp(feed_path, encoding="gzip", body=b"x" * nbytes),
    ]


class FakePage:
    """Each `goto` fires the next scripted visit; links render iff that visit
    delivered a feed body (the page renders only what the feed sent)."""

    def __init__(self, visits: list[list[_Resp]]) -> None:
        self.visits = visits
        self.handler = None
        self.gotos: list[str] = []
        self._links: list[str] = []

    def on(self, event: str, handler) -> None:
        assert event == "response"
        self.handler = handler

    def goto(self, url: str, **_kw) -> None:
        self.gotos.append(url)
        visit = self.visits[len(self.gotos) - 1] if len(self.gotos) <= len(self.visits) else []
        for resp in visit:
            self.handler(resp)
        has_body = any(scraper._feed_marker(r.url) and r._body for r in visit)
        self._links = VIDEO_HREFS if has_body else []

    def wait_for_selector(self, _sel: str, timeout: int) -> None:
        if not self._links:
            raise PWTimeout(f"Timeout {timeout}ms exceeded.")

    def eval_on_selector_all(self, _sel: str, _js: str) -> list[str]:
        return list(self._links)


def _open(url: str, visits: list[list[_Resp]]) -> tuple[FakePage, dict[str, int]]:
    page, feed_luot = FakePage(visits), {}
    _watch_feed_api(page, None, feed_luot)
    _mo_trang_co_ham_phien(page, url, feed_luot)
    return page, feed_luot


def test_search_empty_first_visit_is_reopened_once_and_gets_links(caplog):
    with caplog.at_level(logging.INFO, logger="ttmd"):
        page, feed_luot = _open(SEARCH_URL, [
            _empty_first_visit("/api/search/general/full/"),
            _full_second_visit("/api/search/general/full/"),
        ])
    assert page.gotos == [SEARCH_URL, SEARCH_URL]
    assert page.eval_on_selector_all("", "") == VIDEO_HREFS
    assert feed_luot["rong"] == 1 and feed_luot["co_du_lieu"] == 1
    lines = [r.getMessage() for r in caplog.records if "[ham-phien]" in r.getMessage()]
    assert lines == ["[ham-phien] lan=2 feed=search bytes=207477 links=3"]
    assert not [r for r in caplog.records if "no video links rendered" in r.getMessage()]


def test_profile_empty_first_visit_is_reopened_once():
    page, feed_luot = _open(PROFILE_URL, [
        _empty_first_visit("/api/post/item_list/"),
        _full_second_visit("/api/post/item_list/"),
    ])
    assert len(page.gotos) == 2
    assert feed_luot["co_du_lieu"] == 1


def test_reopen_is_capped_at_one_even_if_second_visit_is_empty_too(caplog):
    with caplog.at_level(logging.INFO, logger="ttmd"):
        page, feed_luot = _open(SEARCH_URL, [
            _empty_first_visit("/api/search/general/full/"),
            _empty_first_visit("/api/search/general/full/"),
            _full_second_visit("/api/search/general/full/"),
        ])
    assert len(page.gotos) == 2
    assert feed_luot["rong"] == 2 and feed_luot.get("co_du_lieu", 0) == 0
    msgs = [r.getMessage() for r in caplog.records]
    assert "[ham-phien] lan=2 feed=search bytes=0 links=0" in msgs
    assert any("no video links rendered" in m for m in msgs)


def test_music_page_is_never_reopened_even_when_its_feed_is_empty():
    page, _ = _open(MUSIC_URL, [
        _empty_first_visit("/api/music/item_list/"),
        _full_second_visit("/api/music/item_list/"),
    ])
    assert page.gotos == [MUSIC_URL]


def test_music_page_with_data_on_first_visit_opens_once():
    page, _ = _open(MUSIC_URL, [_full_second_visit("/api/music/item_list/")])
    assert page.gotos == [MUSIC_URL]


def test_empty_first_feed_whose_body_cannot_be_read_still_reopens():
    # Feed rỗng tới dạng nén không Content-Length ⇒ Chromium "No data found":
    # watcher không vào ô rong nhưng vẫn phải mở lại, không thì job lại ra 0 video.
    first = [r for r in _empty_first_visit("/api/search/general/full/")
             if "general/full" not in r.url]
    first.insert(1, _Resp("/api/search/general/full/", encoding="gzip", unreadable=True))
    page, feed_luot = _open(SEARCH_URL, [first, _full_second_visit("/api/search/general/full/")])
    assert len(page.gotos) == 2
    assert feed_luot.get("rong", 0) == 0 and feed_luot["khong_doc_duoc"] == 1
    assert feed_luot["co_du_lieu"] == 1


def test_no_reopen_when_emptiness_was_not_measured():
    # Feed không xuất hiện (vd bị chặn trước khi gọi): không đo được thì không đoán.
    page, _ = _open(SEARCH_URL, [[_Resp("/api/search/suggest/guide/", content_length="153")]])
    assert page.gotos == [SEARCH_URL]


def test_scrape_merges_counts_into_caller_stats_without_bytes_key(monkeypatch):
    visits = [_empty_first_visit("/api/search/general/full/"),
              _full_second_visit("/api/search/general/full/")]

    class _Ctx:
        def new_page(self):
            return FakePage(visits)

        def close(self):
            pass

    monkeypatch.setattr(scraper, "_open_context", lambda *a, **k: (None, _Ctx()))
    monkeypatch.setattr(scraper, "_auto_scroll",
                        lambda page, *a: scraper._collect_links(page))

    class _PW:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(scraper, "sync_playwright", lambda: _PW())
    tk = {"rong": 0, "co_du_lieu": 0}
    refs = scraper.scrape_music_page(SEARCH_URL, max_videos=10, thong_ke_feed=tk)
    assert len(refs) == 3
    assert tk == {"rong": 1, "co_du_lieu": 1}
