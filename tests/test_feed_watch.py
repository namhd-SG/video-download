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


class FakeResponse:
    def __init__(self, url: str, status: int = 200, *,
                 content_length: str | None = None,
                 body: bytes | None = None, raises: bool = False) -> None:
        self.url = url
        self.status = status
        self._cl = content_length
        self._body = body
        self._raises = raises

    def header_value(self, name: str) -> str | None:
        return self._cl if name == "content-length" else None

    def body(self) -> bytes:
        if self._raises:
            raise RuntimeError("Protocol error: No data found for resource")
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


def test_empty_body_read_warns(caplog):
    # Chunked reply: no content-length header, so the body read decides.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, body=b""))
    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert "body read" in warns[0].getMessage()


def test_unreadable_body_is_logged_not_swallowed(caplog):
    # A body Chromium cannot hand back proves nothing either way — but going
    # silent here would let a blind detector read as a healthy feed.
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(TAG_API, raises=True))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("body unreadable" in m for m in debugs), debugs


def test_full_body_stays_silent(caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse(MUSIC_API, content_length="677593", body=b"x" * 677593))
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_non_feed_url_ignored(caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        _fire(FakeResponse("https://www.tiktok.com/api/share/settings/",
                           content_length="0"))
    assert not caplog.records
