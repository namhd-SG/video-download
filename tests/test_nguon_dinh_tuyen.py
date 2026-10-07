"""Bảng nguồn: URL nào vào nguồn nào, cổng `POST /jobs` và nhánh liệt kê đi qua nó, và
`TikTokCollection` bọc ĐÚNG lời gọi cũ (cùng hàm, cùng kwargs).

Chạy trên DB file thật (tmp_path); không mock DB.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from tiktok_music_downloader import nguon as nguon_mod
from tiktok_music_downloader.nguon import (
    NGUON, DriveFolder, FbAdsLibrary, LinkLe, TikTokCollection, chon_nguon, mo_ta_cac_nguon)
from web import app as app_mod
from web import models
from web import queue as queue_mod

CAC_URL_TIKTOK = [
    "https://www.tiktok.com/music/original-sound-7374515087526136619",
    "https://www.tiktok.com/tag/ai80slook",
    "https://www.tiktok.com/search?q=ai",
    "https://www.tiktok.com/@nguoi.dung",
]
CAC_URL_LA = [
    "https://example.com/tag/x",
    "https://www.youtube.com/@mot.kenh",              # kênh/playlist/tab: chưa nhận
    "https://www.tiktok.com/@nguoi.dung/photo/123",   # không có id video để dùng
    "khong-phai-url",
]
THONG_BAO_400 = ("url không được nhận. Link hỗ trợ: trang TikTok music/tag/search/profile, "
                 "trang Facebook Ads Library, thư mục Google Drive công khai, "
                 "link video lẻ (YouTube, TikTok, Instagram, Facebook, X, Pinterest, Douyin, Bilibili, Snapchat)")


def test_bang_nguon_gom_tiktok_fb_ads_drive_va_link_le():
    assert [type(n) for n in NGUON] == [TikTokCollection, FbAdsLibrary, DriveFolder, LinkLe]
    assert mo_ta_cac_nguon() == THONG_BAO_400.split("Link hỗ trợ: ")[1]


@pytest.mark.parametrize("url", CAC_URL_TIKTOK)
def test_chon_nguon_nhan_trang_tiktok(url):
    n = chon_nguon(url)
    assert n is not None and n.ten == "tiktok"


@pytest.mark.parametrize("url", CAC_URL_LA)
def test_chon_nguon_tu_choi_url_khong_thuoc_nguon_nao(url):
    assert chon_nguon(url) is None


def test_nguon_gia_nhan_moi_url_bi_phat_hien(monkeypatch):
    """Một nguồn nhận mọi URL đặt TRƯỚC TikTok sẽ cướp cả URL TikTok: bảng phải trả nó ra,
    nên nhãn `nen_tang` của job đổi theo — test tuyến đường bắt được điều đó."""
    class NhanHet:
        ten = "gia"
        mo_ta_url = "gia"
        def nhan(self, url): return True
        def loai_log(self, url): return "gia"
        def liet_ke(self, url, **kw): return []

    monkeypatch.setattr(nguon_mod, "NGUON", (NhanHet(),) + nguon_mod.NGUON)
    assert chon_nguon(CAC_URL_TIKTOK[0]).ten == "gia"          # bằng chứng test này có sức phân định
    monkeypatch.undo()
    assert chon_nguon(CAC_URL_TIKTOK[0]).ten == "tiktok"


def test_loai_log_khong_mang_url():
    n = chon_nguon(CAC_URL_TIKTOK[3])
    assert n.loai_log(CAC_URL_TIKTOK[3]) == "profile"
    assert "tiktok.com" not in n.loai_log(CAC_URL_TIKTOK[1])


# --- cổng POST /jobs ------------------------------------------------------

def _dung_app(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    monkeypatch.setattr(app_mod, "daily_cap_rejection", lambda **kw: None)
    return db


@pytest.mark.parametrize("url", CAC_URL_LA)
def test_cong_400_giu_nguyen_chu_va_khong_ghi_job(tmp_path, monkeypatch, url):
    db = _dung_app(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as e:
        app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=5), nguoi_tao="a@x.vn")
    assert e.value.status_code == 400 and e.value.detail == THONG_BAO_400
    assert models.list_jobs(db, None) == []


@pytest.mark.parametrize("url", CAC_URL_TIKTOK)
def test_cong_nhan_trang_tiktok_va_ghi_nen_tang(tmp_path, monkeypatch, url):
    db = _dung_app(tmp_path, monkeypatch)
    ra = app_mod.create_job(app_mod.CreateJobRequest(url=url, so_luong=5), nguoi_tao="a@x.vn")
    assert ra["nen_tang"] == "tiktok" and ra["trang_thai"] == "pending"
    assert models.get_job(db, ra["id"])["nen_tang"] == "tiktok"


# --- nhánh liệt kê: kwargs y hệt cũ ---------------------------------------

def _cb():
    return dict(already_have=lambda ids: set(), on_skip=lambda r: None, on_stop=lambda s: None,
                on_pages=lambda n: None, dem_trang=lambda: None)


def test_liet_ke_hashtag_goi_enumerate_hashtag_dung_kwargs(monkeypatch):
    goi = []
    monkeypatch.setattr(nguon_mod, "enumerate_hashtag",
                        lambda tag, **kw: goi.append((tag, kw)) or ["ref"])
    monkeypatch.setattr(nguon_mod, "scrape_music_page_multi",
                        lambda *a, **k: pytest.fail("hashtag không được đi trình quét trình duyệt"))
    cb = _cb()
    ra = TikTokCollection().liet_ke(CAC_URL_TIKTOK[1], max_videos=7, proxy="p", cookies_path="ck",
                                    passes=3, max_seconds=9.0, kw_profile={"profile_dir": None}, **cb)
    assert ra == ["ref"]
    assert goi == [("ai80slook", {"max_videos": 7, "proxy": "p", "already_have": cb["already_have"],
                                  "on_skip": cb["on_skip"], "on_stop": cb["on_stop"],
                                  "on_pages": cb["on_pages"]})]


def test_liet_ke_music_goi_scrape_multi_dung_kwargs(monkeypatch):
    goi = []
    monkeypatch.setattr(nguon_mod, "scrape_music_page_multi",
                        lambda url, **kw: goi.append((url, kw)) or ["ref"])
    monkeypatch.setattr(nguon_mod, "enumerate_hashtag",
                        lambda *a, **k: pytest.fail("music không được đi chỉ mục hashtag"))
    cb = _cb()
    kw_profile = {"profile_dir": None}
    TikTokCollection().liet_ke(CAC_URL_TIKTOK[0], max_videos=7, proxy="p", cookies_path="ck",
                               passes=3, max_seconds=9.0, kw_profile=kw_profile, **cb)
    assert goi == [(CAC_URL_TIKTOK[0], {
        "passes": 3, "max_videos": 7, "max_seconds": 9.0, "already_have": cb["already_have"],
        "on_skip": cb["on_skip"], "on_stop": cb["on_stop"], "cookies_path": "ck", "proxy": "p",
        "dem_trang": cb["dem_trang"], "profile_dir": None})]


def test_fetch_refs_di_qua_bang_nguon(monkeypatch, tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    goi = []

    class GhiLai:
        ten = "tiktok"
        mo_ta_url = ""
        def nhan(self, url): return True
        def loai_log(self, url): return "x"
        def liet_ke(self, url, **kw):
            goi.append((url, kw))
            return []

    monkeypatch.setattr(queue_mod, "chon_nguon", lambda url: GhiLai())
    queue_mod._fetch_refs(CAC_URL_TIKTOK[0], max_videos=4, cookies_path=None, db_path=db)
    assert len(goi) == 1 and goi[0][0] == CAC_URL_TIKTOK[0]
    assert goi[0][1]["max_videos"] == 4 and goi[0][1]["kw_profile"] == {"profile_dir": None}
    assert goi[0][1]["passes"] == queue_mod.SO_VONG_DAO_SAU
    assert goi[0][1]["max_seconds"] == queue_mod.TRAN_GIAY_MOT_LUOT
