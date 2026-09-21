"""Offline tests for _watch_feed_api's branch logic.

Fake page/response objects instead of a real browser: the four branches are
about what THIS code does with a response, and fakes pin each one exactly
(a live Chromium can only be coaxed towards them). No network, no browser.
"""
from __future__ import annotations

import logging

import pytest

from tiktok_music_downloader.scraper import _watch_feed_api

TAG_API = "https://www.tiktok.com/api/challenge/item_list/?msToken=x"
MUSIC_API = "https://www.tiktok.com/api/music/item_list/?msToken=x"


class FakePage:
    """Captures the handler that _watch_feed_api registers."""

    def __init__(self) -> None:
        self.handler = None

    def on(self, event: str, handler) -> None:
        assert event == "response"
        self.handler = handler


class FakeRequest:
    def __init__(self, method: str = "GET") -> None:
        self.method = method


class FakeResponse:
    def __init__(self, url: str, status: int = 200, *,
                 content_length: str | None = None,
                 content_encoding: str | None = None,
                 body: bytes | None = None, raises: bool = False,
                 raise_text: str = "Protocol error: No data found for resource",
                 header_raises: bool = False, method: str = "GET") -> None:
        self.url = url
        self.status = status
        self.request = FakeRequest(method)
        self._cl = content_length
        self._ce = content_encoding
        self._body = body
        self._raises = raises
        self._raise_text = raise_text
        self._header_raises = header_raises

    def header_value(self, name: str) -> str | None:
        if self._header_raises:
            raise RuntimeError("Target page, context or browser has been closed")
        if name == "content-length":
            return self._cl
        if name == "content-encoding":
            return self._ce
        return None

    def body(self) -> bytes:
        if self._raises:
            raise RuntimeError(self._raise_text)
        assert self._body is not None
        return self._body


def _fire(resp: FakeResponse) -> None:
    page = FakePage()
    _watch_feed_api(page)
    assert page.handler is not None
    page.handler(resp)


def test_content_length_zero_warns(caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, content_length="0"))
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    msg = warns[0].getMessage()
    assert "/api/challenge/item_list" in msg
    assert "Content-Length" in msg
    assert "200" in msg


def test_empty_body_read_warns_defensive(caplog):
    # Chunked reply with no content-length, so the body read decides. NOTE:
    # real Chromium was never observed handing back an empty bytes object —
    # it raises instead (see the unreadable-body test). This pins the
    # defensive branch, not measured browser behaviour.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, body=b""))
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert "body read" in warns[0].getMessage()


def test_unreadable_body_warns_and_admits_it_cannot_tell(caplog):
    # Chromium raises both for a 0-byte body and for one it already dropped.
    # Silence would let a blind detector read as a healthy feed; claiming
    # "empty" would be a guess. It must warn AND say it cannot distinguish.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, raises=True))
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1, warns
    assert "could not be read" in warns[0]
    assert "cannot tell which" in warns[0]


def test_teardown_read_failure_does_not_cry_wolf(caplog):
    # Measured on a successful /music/ run that downloaded 3 files: a feed
    # response landing during ctx.close() cannot be read. Warning there would
    # alarm the user on a run that worked.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(MUSIC_API, raises=True,
                           raise_text="Target page, context or browser has been closed"))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("body unreadable" in m for m in debugs), debugs


def test_gzip_empty_body_is_not_mistaken_for_a_full_one(caplog):
    # gzip of an empty body is still 20 bytes, so Content-Length cannot settle
    # it. Trusting the header here would silence the detector completely.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, content_length="20",
                           content_encoding="gzip", body=b""))
    warns = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1, warns
    assert "body read" in warns[0]


def test_redirect_with_zero_length_is_not_an_empty_feed(caplog):
    # A 302 carries no payload of its own; the target returns the items.
    # Warning here would be a false alarm the user-facing hints key on.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, status=302, content_length="0"))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_non_get_is_not_an_empty_feed(caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, content_length="0", method="OPTIONS"))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_handler_never_raises_even_if_playwright_rpc_fails(caplog):
    # Playwright saves an exception that escapes a listener and re-raises it on
    # the NEXT channel call ("Save the error to throw at the next API call"),
    # which would abort a scrape that had already collected refs.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, header_raises=True))  # must not raise
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("gave up on" in m for m in debugs), debugs


def test_full_body_stays_silent(caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(MUSIC_API, content_length="677593", body=b"x" * 677593))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_unwatched_api_endpoint_is_noted_but_never_warned(caplog):
    # Every /api/ response is debug-logged so an unlisted FEED endpoint shows
    # up under --verbose — the watched list is a snapshot, not a guarantee.
    # But an unwatched endpoint must never raise an empty-feed warning, even
    # with Content-Length: 0 (plenty of TikTok's own endpoints return that).
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse("https://www.tiktok.com/api/share/settings/",
                           content_length="0"))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("api response" in m and "share/settings" in m for m in debugs), debugs


def test_non_api_response_is_ignored_entirely(caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse("https://www.tiktok.com/tag/ai80slook",
                           content_length="0"))
    assert not caplog.records


# ---------------------------------------------------------------------------
# Bộ đếm trang: đo CHÍNH mối nối, không đo hạ lưu
# ---------------------------------------------------------------------------
# Hai test đào sâu trong `test_web_queue.py` có scraper giả TỰ gọi `dem_trang()`,
# nên chúng chỉ chứng minh "đếm được thì ghi đúng" — xoá sạch lời gọi
# `dem_trang()` trong `_watch_feed_api` mà chúng vẫn XANH (đo 21/09: 283 passed,
# y hệt control). Đó là test bóng ma ở đúng mối nối bản vá tạo ra. Các test dưới
# đây gọi thẳng handler thật.

def _dem_duoc(resp: FakeResponse) -> int:
    """Số lần `_watch_feed_api` đếm cho một response."""
    page = FakePage()
    dem = {"n": 0}
    _watch_feed_api(page, lambda: dem.__setitem__("n", dem["n"] + 1))
    assert page.handler is not None
    page.handler(resp)
    return dem["n"]


def test_moi_response_feed_2xx_duoc_dem_mot_lan():
    """ĐỘT BIẾN: xoá lời gọi `dem_trang()` trong `_watch_feed_api` ⇒ ĐỎ.
    Không có test này thì `so_trang` lặng lẽ về 0 — đúng trạng thái mà bản vá
    nói là đang chữa, và trần 800 mù trở lại."""
    assert _dem_duoc(FakeResponse(MUSIC_API, content_length="4096")) == 1
    assert _dem_duoc(FakeResponse(TAG_API, content_length="4096")) == 1


def test_response_feed_RONG_van_duoc_dem():
    """Lượt gọi đã tiêu thì tiêu, kể cả khi TikTok trả 0 byte. Trần này đo LƯU
    LƯỢNG mình tạo ra, không đo mình thu được gì — đếm sau khi biết rỗng sẽ
    miễn phí đúng những lượt bị chặn, tức đúng lúc cần bó nhất."""
    assert _dem_duoc(FakeResponse(MUSIC_API, content_length="0")) == 1


def test_khong_dem_thu_khong_phai_feed():
    """Phép thử phải có SỨC PHÂN ĐỊNH: nếu mọi response đều được đếm thì hai
    test trên xanh vì lý do sai."""
    assert _dem_duoc(FakeResponse("https://www.tiktok.com/api/khac/", content_length="99")) == 0
    assert _dem_duoc(FakeResponse(MUSIC_API, status=302, content_length="0")) == 0
    assert _dem_duoc(FakeResponse(MUSIC_API, content_length="99", method="POST")) == 0


def test_khong_truyen_dem_trang_thi_khong_no():
    """Đường CLI/GUI không đo trần nên không truyền `dem_trang`."""
    page = FakePage()
    _watch_feed_api(page)
    page.handler(FakeResponse(MUSIC_API, content_length="4096"))
