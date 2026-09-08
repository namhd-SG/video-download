"""Offline unit tests for URL parsing + throttle."""
from __future__ import annotations

import time

import pytest

from tiktok_music_downloader.utils import (
    USER_AGENTS,
    is_fb_ads_library,
    is_gdrive_folder,
    JitterThrottle,
    VideoRef,
    adaptive_backoff,
    is_music_page,
    is_tag_page,
    is_tiktok_collection,
    parse_video_url,
    random_user_agent,
)


def test_parse_video_url_valid():
    url = "https://www.tiktok.com/@creator.name/video/7374515087526136619"
    ref = parse_video_url(url)
    assert ref == VideoRef(video_id="7374515087526136619", url=url)
    assert ref.filename == "7374515087526136619.mp4"


def test_parse_video_url_with_query():
    url = "https://www.tiktok.com/@u/video/1234567890123456789?lang=en"
    ref = parse_video_url(url)
    assert ref is not None
    assert ref.video_id == "1234567890123456789"


def test_parse_video_url_invalid():
    assert parse_video_url("https://example.com/video/123") is None
    assert parse_video_url("https://www.tiktok.com/@user") is None


def test_is_music_page():
    assert is_music_page("https://www.tiktok.com/music/original-sound-7374515087526136619")
    assert not is_music_page("https://www.tiktok.com/@user/video/123")
    assert not is_music_page("https://example.com")


def test_is_music_page_non_ascii_slug():
    # Arabic slug, percent-encoded as pasted from the browser.
    assert is_music_page(
        "https://www.tiktok.com/music/%D8%A7%D9%84%D8%B5%D9%88%D8%AA-%D8%A7%D9%84%D8%A3%D8%B5%D9%84%D9%8A-7638038954847669013"
    )
    # Decoded Unicode slug (Vietnamese).
    assert is_music_page("https://www.tiktok.com/music/nhạc-buồn-1234567890")


def test_is_tag_page():
    assert is_tag_page("https://www.tiktok.com/tag/ai80slook")
    assert is_tag_page("https://tiktok.com/tag/fyp")
    # Query params (lang, from browser share) must not break the match.
    assert is_tag_page("https://www.tiktok.com/tag/ai80slook?lang=en")


def test_is_tag_page_non_ascii_slug():
    # Percent-encoded slug as pasted from the browser, and decoded Unicode.
    assert is_tag_page("https://www.tiktok.com/tag/%D8%A7%D9%84%D8%B5%D9%88%D8%AA")
    assert is_tag_page("https://www.tiktok.com/tag/nhạcbuồn")


def test_is_tag_page_rejects_non_tag_urls():
    # Discriminating power: the predicate must say False for valid non-tag URLs.
    assert not is_tag_page("https://example.com/tag/ai80slook")
    assert not is_tag_page("https://www.tiktok.com/@user/video/123")
    assert not is_tag_page("https://www.tiktok.com/music/original-sound-7374515087526136619")
    assert not is_tag_page("https://www.tiktok.com/tag/")


def test_tag_page_is_a_tiktok_collection():
    # The GUI/CLI gate reads is_tiktok_collection, so tag support hinges on this.
    assert is_tiktok_collection("https://www.tiktok.com/tag/ai80slook")
    assert is_tiktok_collection("https://www.tiktok.com/music/original-sound-7374515087526136619")
    assert is_tiktok_collection("https://www.tiktok.com/search?q=ai")
    assert not is_tiktok_collection("https://www.tiktok.com/@user/video/123")
    assert not is_tiktok_collection("https://example.com/tag/x")


def test_jitter_throttle_within_range():
    import random as _r
    t = JitterThrottle(0.2, rng=_r.Random(0))
    t.wait()  # first call: still sleeps
    samples = []
    for _ in range(5):
        start = time.monotonic()
        t.wait()
        samples.append(time.monotonic() - start)
    # base=0.2 → range [0.15, 0.40]. Every sample must fit, with small slack.
    assert all(0.13 <= s <= 0.45 for s in samples), samples


def test_jitter_zero_is_noop():
    t = JitterThrottle(0)
    start = time.monotonic()
    t.wait()
    t.wait()
    assert time.monotonic() - start < 0.05


def test_video_ref_hashable():
    a = VideoRef("1", "https://x")
    b = VideoRef("1", "https://x")
    assert {a, b} == {a}


def test_user_agent_pool_non_empty():
    assert len(USER_AGENTS) >= 3
    ua = random_user_agent()
    assert ua in USER_AGENTS


def test_adaptive_backoff_monotonic_then_capped():
    seqs = [adaptive_backoff(n) for n in range(1, 8)]
    # First should be 30; should increase, then cap at 300.
    assert seqs[0] == 30.0
    assert all(b >= a for a, b in zip(seqs, seqs[1:]))
    assert seqs[-1] <= 300.0
    assert adaptive_backoff(0) == 0.0


# --- URL gate anchoring -----------------------------------------------------
# The predicates used `.search()`, so anything could precede the scheme and a
# foreign host passed the gate. Cookies are added to the browser context before
# navigation (scraper.py), so a gate-passing foreign host would be visited
# carrying the TikTok session. These pin the anchoring shut.

REDIRECT_SMUGGLE = [
    "https://example.com/redir?u=https://www.tiktok.com/tag/x",
    "https://example.com/r?u=https://www.tiktok.com/music/sound-123",
    "https://example.com/r?u=https://www.tiktok.com/search?q=a",
    "javascript:alert(1)//https://www.tiktok.com/tag/x",
]

LOOKALIKE_HOSTS = [
    "https://evil.tiktok.com/tag/x",
    "https://www.tiktok.com.attacker.net/tag/x",
    "https://tiktok.com.evil.net/music/sound-123",
]


@pytest.mark.parametrize("url", REDIRECT_SMUGGLE)
def test_gate_rejects_url_smuggled_in_a_query_string(url):
    assert not is_tiktok_collection(url)


@pytest.mark.parametrize("url", LOOKALIKE_HOSTS)
def test_gate_rejects_lookalike_hosts(url):
    assert not is_tiktok_collection(url)


def test_parse_video_url_rejects_smuggled_and_lookalike():
    assert parse_video_url(
        "https://example.com/r?u=https://www.tiktok.com/@u/video/123"
    ) is None
    assert parse_video_url("https://evil.tiktok.com/@u/video/123") is None


def test_gate_still_accepts_valid_urls_after_anchoring():
    # Control: anchoring must not reject anything that worked before.
    assert is_tiktok_collection("https://www.tiktok.com/tag/ai80slook")
    assert is_tiktok_collection("https://tiktok.com/tag/fyp?lang=en")
    assert is_tiktok_collection("https://www.tiktok.com/music/nhạc-buồn-1234567890")
    assert is_tiktok_collection("https://www.tiktok.com/search?q=ai")
    # Pasted with surrounding whitespace (the CLI does not strip).
    assert is_tiktok_collection("  https://www.tiktok.com/tag/ai80slook  ")
    assert parse_video_url(
        "https://www.tiktok.com/@creator.name/video/7374515087526136619"
    ) is not None
