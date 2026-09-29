"""Phân loại lỗi từng video (TikTok vs hệ thống) và mức log tương ứng.

Đột biến phải ĐỎ: `phan_loai_loi` luôn trả `he_thong` · `downloader.py` log lỗi
TikTok ở mức ERROR.
"""
from __future__ import annotations

import logging

import pytest

from tiktok_music_downloader import downloader
from tiktok_music_downloader.phan_loai_loi import LOI_KHONG_CO_LUONG_VIDEO, phan_loai_loi
from tiktok_music_downloader.utils import VideoRef


@pytest.mark.parametrize("text, mong_doi", [
    ("ERROR: [TikTok] 123: Requested format is not available. Use --list-formats", "tiktok"),
    ("requested FORMAT is not available", "tiktok"),
    ("ERROR: [TikTok] 1: Video unavailable. This video is not available", "tiktok"),
    ("Private video. Sign in if you've been granted access", "tiktok"),
    ("This video is private", "tiktok"),
    (LOI_KHONG_CO_LUONG_VIDEO, "tiktok"),
    # Mặc định là hệ thống: mạng, Drive, lifecycle, lỗi chưa từng thấy, rỗng.
    ("Unable to download webpage: HTTP Error 503", "he_thong"),
    ("upload_failed: Drive quota exceeded", "he_thong"),
    ("[Errno 28] No space left on device", "he_thong"),
    ("HTTP Error 429: Too Many Requests", "he_thong"),
    ("", "he_thong"),
    (None, "he_thong"),
])
def test_phan_loai_loi_bang_ca(text, mong_doi):
    assert phan_loai_loi(text) == mong_doi


class _ProgressGhi:
    def __init__(self):
        self.nhan = []

    def note(self, kind, info=None):
        self.nhan.append((kind, info))

    def update(self, *a, **k):
        pass


def _tai_mot_video_loi(tmp_path, monkeypatch, exc):
    def _hong(url, opts):
        raise exc

    monkeypatch.setattr(downloader, "_download_one", _hong)
    ghi = _ProgressGhi()
    downloader.download_all([VideoRef(video_id="1", url="https://x/1")], tmp_path,
                             delay_seconds=0, progress=ghi)
    return ghi


def test_loi_tiktok_log_warning_khong_co_error(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        ghi = _tai_mot_video_loi(tmp_path, monkeypatch,
                                 Exception("Requested format is not available"))
    dong = [r for r in caplog.records if "✗" in r.getMessage()]
    assert [r.levelno for r in dong] == [logging.WARNING], \
        "lỗi phía TikTok phải đúng MỘT dòng WARNING, không có ERROR"
    assert ghi.nhan == [("failed", {"loi": "Requested format is not available"})]


def test_loi_he_thong_log_error(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        ghi = _tai_mot_video_loi(tmp_path, monkeypatch, OSError("No space left on device"))
    dong = [r for r in caplog.records if "✗" in r.getMessage()]
    assert [r.levelno for r in dong] == [logging.ERROR]
    assert ghi.nhan[0][0] == "failed" and "No space left" in ghi.nhan[0][1]["loi"]
