"""Offline tests for the hashtag enumerator. No network: `_fetch` is replaced."""
from __future__ import annotations

import json
import logging

import pytest

from tiktok_music_downloader import hashtag_enumerator as he


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(he.time, "sleep", lambda _s: None)


def _page(videos, cursor, has_more):
    return json.dumps({"data": {
        "videos": [{"video_id": v, "author": {"unique_id": u}} for v, u in videos],
        "cursor": cursor, "hasMore": has_more}}).encode()


def _wire(monkeypatch, *, challenge=b'href="/challenge/detail/2709669"', pages=()):
    """Serve the SSR page then the given provider pages, in order."""
    calls = {"n": 0, "urls": []}
    seq = list(pages)

    def fake(url, user_agent, timeout=25.0, proxy=None):
        calls["urls"].append(url)
        if "/tag/" in url:
            return challenge
        calls["n"] += 1
        return seq.pop(0) if seq else _page([], 0, False)

    monkeypatch.setattr(he, "_fetch", fake)
    return calls


def test_enumerates_and_builds_video_urls(monkeypatch):
    _wire(monkeypatch, pages=[_page([("111", "alice"), ("222", "bob")], 20, False)])
    refs = he.enumerate_hashtag("anos80")
    assert [r.video_id for r in refs] == ["111", "222"]
    assert refs[0].url == "https://www.tiktok.com/@alice/video/111"
    assert refs[0].filename == "111.mp4"


def test_paginates_until_max_videos(monkeypatch):
    _wire(monkeypatch, pages=[
        _page([(str(i), "u") for i in range(10)], 10, True),
        _page([(str(i), "u") for i in range(10, 20)], 20, True),
    ])
    assert len(he.enumerate_hashtag("t", max_videos=15)) == 15


def test_dedupes_ids_repeated_across_pages(monkeypatch):
    _wire(monkeypatch, pages=[
        _page([("1", "a"), ("2", "b")], 10, True),
        _page([("2", "b"), ("3", "c")], 20, False),
    ])
    assert [r.video_id for r in he.enumerate_hashtag("t")] == ["1", "2", "3"]


def test_missing_challenge_id_returns_empty_and_says_why(monkeypatch, caplog):
    _wire(monkeypatch, challenge=b"<html>nothing here</html>")
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert he.enumerate_hashtag("gone") == []
    assert any("no challenge id" in r.getMessage() for r in caplog.records)


def test_unreachable_page_returns_empty_not_an_exception(monkeypatch, caplog):
    monkeypatch.setattr(he, "_fetch", lambda *a, **k: None)
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert he.enumerate_hashtag("t") == []


def test_provider_returning_non_json_is_reported(monkeypatch, caplog):
    _wire(monkeypatch, pages=[b"<html>rate limited</html>"])
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert he.enumerate_hashtag("t") == []
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "not JSON" in msgs and "external index" in msgs


def test_empty_pages_with_has_more_set_do_not_spin(monkeypatch, caplog):
    # Observed for real: has_more true on a page that added nothing. The stall
    # guard must stop after a couple of those instead of burning every page.
    _wire(monkeypatch, pages=[_page([], 20, True)] * 40)
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert he.enumerate_hashtag("t", max_pages=40) == []
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "nothing usable" in msgs or "adding" in msgs, msgs

def test_non_numeric_video_ids_are_skipped(monkeypatch):
    _wire(monkeypatch, pages=[_page([("abc", "a"), ("", "b"), ("333", "c")], 0, False)])
    assert [r.video_id for r in he.enumerate_hashtag("t")] == ["333"]


def test_real_fetch_sends_no_cookie_header(monkeypatch):
    """Exercise the REAL _fetch and inspect what it actually puts on the wire.

    The previous version of this test replaced _fetch — the only function that
    builds headers — so it could not have caught a leak, and its substring
    check would also have tripped on an innocent hashtag like #authentic.
    """
    captured = {}

    class FakeResp:
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(he.urllib.request, "urlopen", fake_urlopen)
    he._fetch("https://www.tikwm.com/api/challenge/posts?x=1", "UA/1.0")

    names = {k.lower() for k in captured["headers"]}
    assert "cookie" not in names, captured["headers"]
    assert "authorization" not in names, captured["headers"]
    # Only the UA we passed; urllib adds nothing identifying of its own.
    assert captured["headers"].get("User-agent") == "UA/1.0"
    assert names <= {"user-agent"}, captured["headers"]


def test_proxy_is_used_when_given(monkeypatch):
    # A user who sets a proxy does it so their address is never exposed; the
    # listing step must honour it, not just the download step.
    seen = {}

    class FakeOpener:
        def open(self, req, timeout=None):
            class R:
                def read(self): return b"{}"
                def __enter__(self): return self
                def __exit__(self, *a): return False
            return R()

    def fake_build_opener(handler):
        seen["proxies"] = handler.proxies
        return FakeOpener()

    monkeypatch.setattr(he.urllib.request, "build_opener", fake_build_opener)
    he._fetch("https://example.com/x", "UA/1.0", proxy="http://127.0.0.1:8888")
    assert seen["proxies"]["https"] == "http://127.0.0.1:8888"


def test_no_proxy_means_no_opener_is_built(monkeypatch):
    monkeypatch.setattr(he.urllib.request, "build_opener",
                        lambda h: (_ for _ in ()).throw(AssertionError("must not build")))
    monkeypatch.setattr(he.urllib.request, "urlopen",
                        lambda req, timeout=None: type("R", (), {
                            "read": lambda self: b"{}",
                            "__enter__": lambda self: self,
                            "__exit__": lambda self, *a: False})())
    assert he._fetch("https://example.com/x", "UA/1.0") == b"{}"


# --- failures must be distinguishable from a finished listing -------------

def test_partial_listing_is_reported_as_incomplete(caplog):
    """Page 1 fine, page 2 fails: the short list must say so.

    The dangerous shape is a silent one — the caller downloads 30 of the 200
    it asked for and the CLI prints a green "downloaded: 30".
    """
    calls = {"n": 0}

    def fake(url, user_agent, timeout=25.0, proxy=None):
        if "/tag/" in url:
            return b'href="/challenge/detail/2709669"'
        calls["n"] += 1
        if calls["n"] == 1:
            return _page([(str(i), "u") for i in range(30)], 30, True)
        return None                      # network failure on page 2

    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(he, "_fetch", fake)
        with caplog.at_level(logging.WARNING, logger="ttmd"):
            refs = he.enumerate_hashtag("t", max_videos=200)
    assert len(refs) == 30
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "INCOMPLETE" in msgs, msgs
    assert "index reports no more pages" not in msgs, msgs


def test_rate_limit_message_from_the_index_is_surfaced(monkeypatch, caplog):
    # tikwm answers rate limiting with HTTP 200 and {"code":-1,"msg":...}.
    _wire(monkeypatch, pages=[json.dumps({"code": -1, "msg": "Free Api Limit"}).encode()])
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert he.enumerate_hashtag("t") == []
    assert "Free Api Limit" in " ".join(r.getMessage() for r in caplog.records)


def test_stalls_instead_of_burning_every_page(monkeypatch, caplog):
    # has_more set forever while the same ids come back.
    same = _page([("1", "a"), ("2", "b")], 10, True)
    _wire(monkeypatch, pages=[same] * 40)
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        refs = he.enumerate_hashtag("t", max_videos=200, max_pages=40)
    assert len(refs) == 2
    assert "adding\nnothing" in " ".join(r.getMessage() for r in caplog.records).replace(" ", "\n") \
        or "nothing" in " ".join(r.getMessage() for r in caplog.records)


def test_refuses_when_the_page_offers_several_challenge_ids(monkeypatch, caplog):
    # Picking the first would enumerate somebody else's hashtag and look fine.
    _wire(monkeypatch, challenge=b"challenge/detail/111 ... challenge/detail/222")
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert he.enumerate_hashtag("t") == []
    assert "refusing" in " ".join(r.getMessage() for r in caplog.records)


def test_percent_encoded_slug_is_not_double_encoded(monkeypatch):
    # A non-Latin hashtag copied from Chrome arrives already encoded; quoting
    # it again asks TikTok for a different, nonexistent tag.
    urls = []

    def fake(url, user_agent, timeout=25.0, proxy=None):
        urls.append(url)
        return b'href="/challenge/detail/9"' if "/tag/" in url else _page([], 0, False)

    monkeypatch.setattr(he, "_fetch", fake)
    he.enumerate_hashtag("%D8%A7%D9%84%D8%B5%D9%88%D8%AA")
    assert "%25" not in urls[0], urls[0]


def test_zero_or_negative_max_videos_returns_empty(monkeypatch):
    _wire(monkeypatch, pages=[_page([("1", "a")], 0, False)])
    assert he.enumerate_hashtag("t", max_videos=0) == []
    assert he.enumerate_hashtag("t", max_videos=-5) == []


def test_item_without_a_handle_is_skipped(monkeypatch):
    # Without a handle the post URL cannot be built; a guessed one 404s.
    bad = json.dumps({"data": {"videos": [
        {"video_id": "111", "author": {}},
        {"video_id": "222", "author": {"unique_id": "ok"}}], "cursor": 0, "hasMore": False}}).encode()
    _wire(monkeypatch, pages=[bad])
    assert [r.video_id for r in he.enumerate_hashtag("t")] == ["222"]


def test_unexpected_payload_shape_does_not_raise(monkeypatch, caplog):
    weird = json.dumps({"data": {"videos": "not a list", "cursor": "abc"}}).encode()
    _wire(monkeypatch, pages=[weird])
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert he.enumerate_hashtag("t") == []       # must not raise
