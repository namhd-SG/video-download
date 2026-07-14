"""Offline unit tests for URL parsing + throttle."""
from __future__ import annotations

import time

import pytest

from tiktok_music_downloader.utils import (
    USER_AGENTS,
    JitterThrottle,
    VideoRef,
    adaptive_backoff,
    is_music_page,
    is_profile_page,
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


def test_is_profile_page():
    # Bare handle, trailing slash, and query string all count as a profile.
    assert is_profile_page("https://www.tiktok.com/@cataldotez5")
    assert is_profile_page("https://www.tiktok.com/@cataldotez5/")
    assert is_profile_page("https://www.tiktok.com/@creator.name?lang=en")
    assert is_profile_page("https://tiktok.com/@user_123")
    # A single video URL is NOT a profile page.
    assert not is_profile_page("https://www.tiktok.com/@user/video/7374515087526136619")
    assert not is_profile_page("https://www.tiktok.com/music/original-sound-123")
    assert not is_profile_page("https://example.com/@user")


def test_is_tiktok_collection_includes_profile():
    assert is_tiktok_collection("https://www.tiktok.com/@cataldotez5")
    assert is_tiktok_collection("https://www.tiktok.com/music/original-sound-123")
    assert not is_tiktok_collection("https://www.tiktok.com/@user/video/123")


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
