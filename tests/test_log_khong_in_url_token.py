"""Log không mang URL nguồn, handle khách hay token khung giải (ĐP-1115/1121).

Thông điệp dùng dạng THẬT của Playwright ("Call log … navigating to …") và yt-dlp ("ERROR: [TikTok] …"), kể cả dạng mã hoá
`%2F%40`. Chỗ che được giữ hẹp có chủ đích: `@` phải đứng ngay sau `/` (hoặc `%2F`) mới là handle — email không bị che.
"""
from __future__ import annotations

import logging
import re

import pytest

from tiktok_music_downloader import downloader, scraper
from tiktok_music_downloader.utils import VideoRef, che_url, loai_nguon
from web.app import CheTokenAccessLog, _che_token_trong_access_log

HANDLE = "khach.hang"
URL_HO_SO = f"https://www.tiktok.com/@{HANDLE}?lang=vi"
CALL_LOG = (f'Timeout 30000ms exceeded.\nCall log:\n  - navigating to "https://www.tiktok.com/@{HANDLE}", '
            'waiting until "domcontentloaded"')
YTDLP_LOI = (f"ERROR: [TikTok] 7692740350766517525: No video formats found!; "
             f"https://www.tiktok.com/@{HANDLE}/video/7692740350766517525")


def _sach(text: str) -> None:
    assert "http" not in text and not re.search(r"www\.[^\s/]+/", text), text  # host trần được phép, URL thì không
    assert HANDLE not in text and "/@" + HANDLE not in text and "%40" + HANDLE not in text, text


# ---------------------------------------------------------------- che_url / loai_nguon

def test_che_url_che_call_log_playwright_that():
    _sach(che_url(CALL_LOG))
    assert "Timeout 30000ms exceeded." in che_url(CALL_LOG), "giữ phần chữ chẩn đoán"


def test_che_url_che_dang_ma_hoa_va_khong_scheme():
    for t in (f"navigating to https%3A%2F%2Fwww.tiktok.com%2F%40{HANDLE}",
              f"path=%2F%40{HANDLE}%2Fvideo",
              f"loaded www.tiktok.com/@{HANDLE}"):
        _sach(che_url(t))


def test_che_url_khong_che_email():
    """Lệch có chủ đích so với agy R2b: handle cần `/` đứng trước — email trong log giữ nguyên."""
    assert che_url("nguoi tao x@y.com bam giai") == "nguoi tao x@y.com bam giai"


def test_che_url_giu_chu_va_cat_do_dai():
    ra = che_url(YTDLP_LOI)
    _sach(ra)
    assert "No video formats found" in ra and "7692740350766517525" in ra, "id video GIỮ (ĐP-1115 b)"
    assert len(che_url("x" * 1000)) == 301


@pytest.mark.parametrize("url,loai", [
    (URL_HO_SO, "profile"),
    (f"https://www.tiktok.com/@{HANDLE}/video/1", "video"),
    ("https://www.tiktok.com/music/bai-hat-1234", "music"),
    ("https://www.tiktok.com/tag/abc", "tag"),
    ("https://www.facebook.com/ads/library", "khac"),
])
def test_loai_nguon(url, loai):
    assert loai_nguon(url) == loai


# ---------------------------------------------------------------- 3 dòng log

def test_dong_scraping_chi_ghi_host_va_loai(monkeypatch, caplog):
    """ĐỘT BIẾN: trả `music_url` vào dòng `scraping` ⇒ ĐỎ."""
    def dung():
        raise RuntimeError("dừng sau dòng log")

    monkeypatch.setattr(scraper, "sync_playwright", dung)
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        scraper.scrape_music_page(URL_HO_SO, max_videos=1)
    dong = [r.getMessage() for r in caplog.records if r.getMessage().startswith("scraping")]
    assert dong and "host=www.tiktok.com loai=profile" in dong[0], dong
    for r in caplog.records:
        _sach(r.getMessage())


def _ydl_nem(thong_diep):
    class _Ydl:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError(thong_diep)

        def download(self, urls):
            raise RuntimeError(thong_diep)

    return _Ydl


class _ProgressGhi:
    def __init__(self):
        self.nhan = []

    def note(self, kind, info=None):
        self.nhan.append((kind, info))

    def update(self, *a, **k):
        pass


def test_dong_loi_tai_che_url_giu_chan_doan_va_cau_dao_van_thay_chuoi_tho(monkeypatch, tmp_path, caplog):
    """ĐỘT BIẾN: trả `exc` thô vào dòng `✗` ⇒ ĐỎ. Cầu dao (queue) đọc `info["loi"]` THÔ ⇒ phải còn nguyên."""
    monkeypatch.setattr(downloader, "YoutubeDL", _ydl_nem(YTDLP_LOI))
    ghi = _ProgressGhi()
    with caplog.at_level(logging.INFO):
        downloader.download_all([VideoRef(video_id="7692740350766517525", url=f"https://www.tiktok.com/@{HANDLE}/video/7692740350766517525")],
                                tmp_path, delay_seconds=0, progress=ghi)
    x = [r.getMessage() for r in caplog.records if r.getMessage().startswith("✗")]
    assert x and "No video formats found" in x[0] and "[he_thong]" in x[0], x
    for r in caplog.records:
        _sach(r.getMessage())
    loi = [info for kind, info in ghi.nhan if kind == "failed"]
    assert loi and loi[0]["loi"] == YTDLP_LOI, "chuỗi cho cầu dao/phân loại KHÔNG bị che"


def _ban_ghi_access(path):
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                             ("127.0.0.1:5000", "GET", path, "1.1", 200), None)


def test_access_log_che_gia_tri_token_moi_route():
    """ĐỘT BIẾN: bỏ bộ lọc / không dựng lại tuple ⇒ ĐỎ."""
    f = CheTokenAccessLog()
    r = _ban_ghi_access("/jobs/5/giai/khung?token=cbf64148-a896-4a29-b5e0-1865a971d0d4&x=1")
    assert f.filter(r) is True
    msg = r.getMessage()
    assert "cbf64148" not in msg and "token=<redacted>" in msg and "x=1" in msg, msg
    r2 = _ban_ghi_access("/khac?a=1&token=abc")
    f.filter(r2)
    assert "abc" not in r2.getMessage() and "a=1" in r2.getMessage()
    r3 = _ban_ghi_access("/healthz")
    f.filter(r3)
    assert r3.getMessage() == '127.0.0.1:5000 - "GET /healthz HTTP/1.1" 200'


def test_bo_loc_gan_vao_logger_uvicorn_access_mot_lan():
    lg = logging.getLogger("uvicorn.access")
    truoc = list(lg.filters)
    try:
        _che_token_trong_access_log()
        _che_token_trong_access_log()
        assert sum(isinstance(f, CheTokenAccessLog) for f in lg.filters) == 1
    finally:
        lg.filters = truoc
