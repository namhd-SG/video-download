"""Nguồn tìm Chrome: URL, đọc DOM, hâm phiên, ngân sách, luôn đóng cửa sổ. Không mở Chrome thật: trang được thay bằng giả."""
from __future__ import annotations

import pytest

from tiktok_music_downloader.tim_trend import nguon_tim
from tiktok_music_downloader.tim_trend.nguon_tim import ChromeTim, HetLuot, tu_dom, url_cua
from tiktok_music_downloader.tim_trend.truy_van import TruyVan

DOM_GD1 = [  # rút từ DOM thật GĐ1 (S7 "7 pose ai trend", 22/10)
    {"url": "https://www.tiktok.com/@saaart3/video/7697969447553813778?is_from_webapp=1", "cover": "https://p16/a.jpeg",
     "caption": "AI collage 7 poses"},
    {"url": "https://www.tiktok.com/@saaart3/video/7697969447553813778", "cover": "https://p16/a.jpeg", "caption": "trùng"},
    {"url": "https://www.tiktok.com/@lovinglylov3ly0/video/7699072089201921301", "cover": "https://p16/b.jpeg",
     "caption": "Tren AI ubah foto menjadi kolase 7 pose"},
    {"url": "https://www.tiktok.com/@x/photo/7699000000000000000", "cover": "https://p16/c.jpeg", "caption": "ảnh, không phải video"},
    {"url": "https://www.tiktok.com/@y/video/7699000000000000001", "cover": "", "caption": "không ảnh bìa"},
]


def test_url_cua():
    assert url_cua(TruyVan("7 pose ai trend", "cau_truc", "en")) == "https://www.tiktok.com/search/video?q=7%20pose%20ai%20trend"
    assert url_cua(TruyVan("#aicatwalk", "mo_rong", "goc", loai="tag")) == "https://www.tiktok.com/tag/aicatwalk"


def test_tu_dom_chi_giu_link_video_chuan():
    ra = tu_dom(DOM_GD1, "7 pose ai trend")
    assert [(u.video_id, u.tac_gia) for u in ra] == [("7697969447553813778", "saaart3"),
                                                     ("7699072089201921301", "lovinglylov3ly0")]
    assert ra[0].url == "https://www.tiktok.com/@saaart3/video/7697969447553813778"


class _TrangGia:
    def __init__(self, ket_qua):
        self.ket_qua = list(ket_qua)
        self.da_goto = []

    def goto(self, url, **k):
        self.da_goto.append(url)

    def wait_for_selector(self, *a, **k):
        pass

    def wait_for_timeout(self, *a):
        pass

    def evaluate(self, _js):
        return self.ket_qua.pop(0)


def _tim(monkeypatch, ket_qua, tran=6):
    monkeypatch.setattr(nguon_tim.time, "sleep", lambda s: None)
    t = ChromeTim(tran_luot=tran, gian_cach=0, bao=lambda s: None)
    t._page = _TrangGia(ket_qua)
    return t


def test_ham_phien_khi_luot_dau_rong_va_dem_ca_luot_ham(monkeypatch):
    t = _tim(monkeypatch, [[], DOM_GD1])
    ra, ghi_chu = t.tim(TruyVan("kolase 7 pose", "mo_rong", "goc"))
    assert len(ra) == 2 and ghi_chu == "ham phien" and t.da_mo == 2


def test_rong_sau_ham_phien_duoc_ghi_ro(monkeypatch):
    t = _tim(monkeypatch, [[], []])
    ra, ghi_chu = t.tim(TruyVan("x", "cau_truc", "en"))
    assert ra == [] and "feed rong" in ghi_chu


def test_het_luot_tinh_ca_luot_ham(monkeypatch):
    t = _tim(monkeypatch, [[], DOM_GD1, DOM_GD1], tran=2)
    t.tim(TruyVan("a", "cau_truc", "en"))
    with pytest.raises(HetLuot):
        t.tim(TruyVan("b", "cau_truc", "en"))


def test_luon_dong_cua_so_khi_loi(monkeypatch):
    dong = []

    class _Ctx:
        def new_page(self):
            raise RuntimeError("trang hỏng")

        def close(self):
            dong.append("ctx")

    class _Chromium:
        def launch_persistent_context(self, *a, **k):
            return _Ctx()

    class _Pw:
        chromium = _Chromium()

        def stop(self):
            dong.append("pw")

    class _Sync:
        def start(self):
            return _Pw()

    import playwright.sync_api as api
    monkeypatch.setattr(api, "sync_playwright", lambda: _Sync())
    bao = []
    with pytest.raises(RuntimeError):
        with ChromeTim(6, 0, bao=bao.append):
            pass
    assert dong == ["ctx", "pw"] and bao and "cửa sổ Chrome" in bao[0]
