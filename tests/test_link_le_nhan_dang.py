"""Link lẻ đa nền tảng: nhận dạng URL (không mạng), cấu hình nền tảng bật, và cổng `POST /jobs` cho một/nhiều link.

DB file thật trong tmp_path; không mạng — `socket` bị chặn trong các test nhận dạng để CHỨNG MINH nhận dạng
không gọi mạng (một lời gọi mạng sẽ ĐỎ, không treo).
"""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader.nguon import (
    BANG_LINK_LE, NEN_TANG_LINK_LE, LinkLe, chon_nguon, nen_tang_bat, tach_link)
from web import app as app_mod
from web import models

MA = "dQw4w9WgXcQ"
BANG_NHAN = [
    # (url, nen_tang, tiền tố id)
    (f"https://www.youtube.com/watch?v={MA}", "youtube", "yt-"),
    (f"https://youtu.be/{MA}", "youtube", "yt-"),
    (f"https://www.youtube.com/shorts/{MA}", "youtube", "yt-"),
    ("https://www.tiktok.com/@nguoi.dung/video/7123456789012345678", "tiktok", ""),
    ("https://www.instagram.com/reel/Cabc123xyz/", "instagram", "ig-"),
    ("https://www.facebook.com/watch/?v=1234567890", "facebook", "fbv-"),
    ("https://www.facebook.com/reel/1234567890", "facebook", "fbv-"),
    ("https://x.com/ai_do/status/1234567890123", "x", "x-"),
    ("https://twitter.com/ai_do/status/1234567890123", "x", "x-"),
    ("https://www.pinterest.com/pin/123456789012/", "pinterest", "pin-"),
    ("https://www.douyin.com/video/7123456789012345678", "douyin", "dy-"),
    ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili", "bili-"),
    ("https://www.snapchat.com/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYYWlkdXhheXRiAZDL", "snapchat", "snap-"),
]
KHONG_NHAN = [
    "https://www.youtube.com/@mot.kenh",
    "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx",
    "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "https://www.instagram.com/mot.nguoi/",
    "https://vm.tiktok.com/ZMabcdef/",
    "https://www.tiktok.com/@nguoi.dung/photo/7123456789012345678",
    "https://example.com/mot-trang",
    "https://drive.google.com/file/d/abc/view",
    MA,                       # id trần: một số extractor nhận, bảng này không
    "khong-phai-url",
]


@pytest.fixture
def khong_mang(monkeypatch):
    """Mọi lần mở kết nối socket ⇒ lỗi. Nhận dạng chạy dưới fixture này phải vẫn xanh."""
    def _cam(*a, **kw):
        raise AssertionError("nhận dạng link không được chạm mạng")
    monkeypatch.setattr(socket.socket, "connect", _cam)
    monkeypatch.setattr(socket, "getaddrinfo", _cam)


@pytest.mark.parametrize("url, nen_tang, tien_to", BANG_NHAN)
def test_nhan_dang_dung_nen_tang_va_tien_to_khong_mang(khong_mang, url, nen_tang, tien_to):
    n = chon_nguon(url)
    assert isinstance(n, LinkLe)
    assert LinkLe().phan_loai(url) == (nen_tang, tien_to)
    assert n.nen_tang(url) == nen_tang
    assert n.loai_log(url) == f"{nen_tang}:video"
    assert url not in n.loai_log(url)


@pytest.mark.parametrize("url", KHONG_NHAN)
def test_kenh_playlist_tab_va_url_la_khong_nhan(khong_mang, url):
    assert LinkLe().phan_loai(url) is None
    assert chon_nguon(url) is None


def test_tiktok_collection_van_thuoc_nguon_tiktok_khong_bi_link_le_cuop(khong_mang):
    for url in ("https://www.tiktok.com/@nguoi.dung", "https://www.tiktok.com/tag/ai80slook",
                "https://www.tiktok.com/music/original-sound-7374515087526136619"):
        n = chon_nguon(url)
        assert n is not None and n.ten == "tiktok" and not isinstance(n, LinkLe)
    # Facebook Ads Library không bị extractor `Facebook*` của yt-dlp cướp.
    assert chon_nguon("https://www.facebook.com/ads/library/?id=1").ten == "fb_ads"


def test_bang_chi_gom_extractor_co_that_va_khong_co_threads():
    from yt_dlp.extractor import gen_extractor_classes
    co = {ie.ie_key() for ie in gen_extractor_classes()}
    assert set(BANG_LINK_LE) <= co, set(BANG_LINK_LE) - co
    assert not any("thread" in k.lower() for k in BANG_LINK_LE)
    assert NEN_TANG_LINK_LE == {"youtube", "tiktok", "instagram", "facebook", "x", "pinterest",
                                "douyin", "bilibili", "snapchat"}


# --- cấu hình nền tảng được bật -------------------------------------------

def test_mac_dinh_chi_bat_youtube_va_tiktok(monkeypatch):
    monkeypatch.delenv(nguon_mod.ENV_NEN_TANG_BAT, raising=False)
    assert nen_tang_bat() == {"youtube", "tiktok"}
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "   ")
    assert nen_tang_bat() == {"youtube", "tiktok"}


def test_cau_hinh_bat_them_va_bo_ten_la_co_canh_bao(monkeypatch, caplog):
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "YouTube, instagram ,youtub")
    with caplog.at_level("WARNING", logger="ttmd"):
        assert nen_tang_bat() == {"youtube", "instagram"}
    assert any("youtub" in r.getMessage() for r in caplog.records)


def test_tach_link_bo_dong_trong_va_trung_giu_thu_tu():
    assert tach_link("  a \n\n b\r\na\n  \nc ") == ["a", "b", "c"]
    assert tach_link("") == [] and tach_link(None) == []


# --- cổng POST /jobs ------------------------------------------------------

def _dung_app(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: None)
    monkeypatch.delenv(nguon_mod.ENV_NEN_TANG_BAT, raising=False)
    return db


def _tao(url, so_luong=5):
    return app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=so_luong), nguoi_tao="a@x.vn")


def _loi400(url):
    with pytest.raises(HTTPException) as e:
        _tao(url)
    assert e.value.status_code == 400
    return e.value.detail


def test_nen_tang_trong_bang_nhung_chua_bat_thi_400_noi_ro_va_khong_ghi_job(tmp_path, monkeypatch, khong_mang):
    db = _dung_app(tmp_path, monkeypatch)
    chi_tiet = _loi400("https://www.instagram.com/reel/Cabc123xyz/")
    assert "instagram" in chi_tiet and "chưa bật" in chi_tiet
    assert models.list_jobs(db, None) == []
    monkeypatch.setenv(nguon_mod.ENV_NEN_TANG_BAT, "youtube,tiktok,instagram")
    ra = _tao("https://www.instagram.com/reel/Cabc123xyz/")
    assert ra["nen_tang"] == "instagram" and ra["trang_thai"] == "pending"


def test_mot_link_youtube_vao_lane_khac_con_tiktok_video_le_vao_lane_tiktok(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    yt = _tao(f"https://www.youtube.com/watch?v={MA}")
    tt = _tao("https://www.tiktok.com/@nguoi.dung/video/7123456789012345678")
    assert yt["nen_tang"] == "youtube" and tt["nen_tang"] == "tiktok"
    assert models.claim_next_pending_job(db, lane="khac")["id"] == yt["id"]
    assert models.claim_next_pending_job(db, lane="khac") is None
    assert models.claim_next_pending_job(db, lane="tiktok")["id"] == tt["id"]


def test_tiktok_video_le_van_chiu_tran_ngay_cua_tiktok(tmp_path, monkeypatch):
    _dung_app(tmp_path, monkeypatch)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: "đã hết trần hôm nay")
    with pytest.raises(HTTPException) as e:
        _tao("https://www.tiktok.com/@nguoi.dung/video/7123456789012345678")
    assert e.value.status_code == 429
    # YouTube không chịu trần ngày của tài khoản TikTok (nó có trần IP riêng ở `web/pacer.py`).
    assert _tao(f"https://www.youtube.com/watch?v={MA}")["nen_tang"] == "youtube"


def test_ba_link_cung_nen_tang_la_mot_job_luu_nguyen_khoi(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    ba = [f"https://www.youtube.com/watch?v={MA}", "https://youtu.be/aaaaaaaaaaa",
          "https://www.youtube.com/shorts/bbbbbbbbbbb"]
    ra = _tao("\n  ".join(ba) + "\n\n" + ba[0])           # dòng trống và link trùng bị bỏ
    assert ra["nen_tang"] == "youtube"
    assert ra["url"].split("\n") == ba
    assert len(models.list_jobs(db, None)) == 1


def test_tron_nen_tang_la_400(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    chi_tiet = _loi400(f"https://www.youtube.com/watch?v={MA}\n"
                       "https://www.tiktok.com/@nguoi.dung/video/7123456789012345678")
    assert "cùng một nền tảng" in chi_tiet and "tiktok" in chi_tiet and "youtube" in chi_tiet
    assert models.list_jobs(db, None) == []


def test_nhieu_link_chi_nhan_link_le_khong_nhan_trang_tiktok_hay_url_la(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    yt = f"https://www.youtube.com/watch?v={MA}"
    for dong_la in ("https://www.tiktok.com/@nguoi.dung", "https://www.tiktok.com/tag/x",
                    "https://www.facebook.com/ads/library/?id=1", "https://example.com/a"):
        chi_tiet = _loi400(f"{yt}\n{dong_la}")
        assert "link thứ 2" in chi_tiet and "link video lẻ" in chi_tiet
        chi_tiet = _loi400(f"{dong_la}\n{yt}")
        assert "link thứ 1" in chi_tiet
    assert models.list_jobs(db, None) == []


def test_tran_50_link(tmp_path, monkeypatch):
    db = _dung_app(tmp_path, monkeypatch)
    def link(i):
        return f"https://www.youtube.com/watch?v={i:011d}"
    ra = _tao("\n".join(link(i) for i in range(50)))
    assert len(ra["url"].split("\n")) == 50
    chi_tiet = _loi400("\n".join(link(i) for i in range(51)))
    assert "50" in chi_tiet
    assert len(models.list_jobs(db, None)) == 1          # chỉ job 50 link được ghi


def test_than_yeu_cau_khong_lo_dai_dong_la_400_truoc_khi_tach(tmp_path, monkeypatch):
    _dung_app(tmp_path, monkeypatch)
    chi_tiet = _loi400("https://www.youtube.com/watch?v=" + "a" * (app_mod.MAX_KY_TU_O_LINK + 1))
    assert "50" in chi_tiet


def test_mot_url_la_van_400_nguyen_cau_cu(tmp_path, monkeypatch):
    _dung_app(tmp_path, monkeypatch)
    assert _loi400("khong-phai-url").startswith("url không được nhận. Link hỗ trợ: ")
    assert _loi400("   ").startswith("url không được nhận. Link hỗ trợ: ")


def test_mau_kiem_id_thumbnail_nhan_tien_to_link_le_va_van_chan_traversal():
    mau = app_mod._MAU_VIDEO_ID_TIEN_TO
    for ok in ("yt-dQw4w9WgXcQ", "ig-Cabc_1-x", "fbv-123", "x-1234567890123", "pin-1", "dy-7123",
               "bili-BV1xx411c7mD", "snap-W7_ED", "fb-1", "gd-abc"):
        assert mau.fullmatch(ok), ok
    for xau in ("yt-../etc/passwd", "yt-a/b", "zz-123", "yt-", "../yt-abc", "yt-a.b"):
        assert not mau.fullmatch(xau), xau


# --- giao diện: ô nhập nhiều dòng + nhãn nhiều link ------------------------

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


def test_o_nhap_la_textarea_nhieu_dong_va_van_dung_id_url():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<textarea id="url"' in html and 'type="url"' not in html
    assert 'document.getElementById("url").value.trim()' in (STATIC / "app.js").read_text(encoding="utf-8")


def test_nhan_url_job_nhieu_link_chay_that_qua_node():
    import shutil
    node = shutil.which("node")
    if node is None:
        pytest.skip("không có node")
    js = (STATIC / "bao-thieu.js").read_text(encoding="utf-8")
    kich_ban = (
        "global.window = {}; eval(process.argv[1]);"
        "const f = window.BaoThieu.nhanUrl;"
        "console.log(JSON.stringify([f('https://a/1'), f('https://a/1\\nhttps://a/2\\nhttps://a/3'), f(''), f(null)]));"
    )
    ra = subprocess.run([node, "-e", kich_ban, js], capture_output=True, text=True, timeout=30)
    assert ra.returncode == 0, ra.stderr
    import json
    assert json.loads(ra.stdout) == ["https://a/1", "https://a/1 (+2 link)", "", ""]
