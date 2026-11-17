"""Tool tự giải captcha xoay (`captcha_xoay`, M5, cờ `VIDEODL_TU_GIAI_CAPTCHA` mặc định TẮT) — trang GIẢ:
captcha chỉ đóng khi nút được thả cách điểm nhấn đúng d = θ·(rãnh − nút)/180 (±3 px). Không mạng."""
from __future__ import annotations

import base64
import random
from types import SimpleNamespace

import pytest

from tiktok_music_downloader import captcha_xoay as cx
from tiktok_music_downloader import scraper as scraper_mod

RAY, NUT_W, NUT_X, NUT_Y = 348.0, 64.0, 466.0, 553.0
DATA = "data:image/webp;base64," + base64.b64encode(b"anh").decode()


class _Loc:
    def __init__(self, trang, sel):
        self.t, self.sel = trang, sel

    def count(self):
        if not self.t.con_captcha:
            return 0
        return {cx.SEL_NUT: 1, cx.SEL_ANH: 2, cx.SEL_HOP: 1}.get(self.sel, 0)

    def nth(self, _i):
        return self

    def get_attribute(self, _ten):
        return DATA

    def bounding_box(self):
        return {"x": NUT_X, "y": NUT_Y, "width": NUT_W, "height": 40.0}


class _Mouse:
    def __init__(self, trang):
        self.t = trang
        self.x = 0.0
        self.giu = False
        self.x_nhan = None

    def move(self, x, y, steps=1):
        assert isinstance(x, float) or isinstance(x, int)
        self.x = x
        if self.giu:
            self.t.dx_max = max(self.t.dx_max, x - self.x_nhan)

    def down(self):
        self.giu, self.x_nhan = True, self.x

    def up(self):
        self.giu = False
        self.t.lan_tha.append(self.x - self.x_nhan)
        if abs((self.x - self.x_nhan) - self.t.d_dung) <= 3.0:
            self.t.con_captcha = False


class _Trang:
    def __init__(self, theta_dung: float, co_captcha: bool = True):
        self.d_dung = theta_dung * (RAY - NUT_W) / 180.0
        self.con_captcha = co_captcha
        self.lan_tha: list[float] = []
        self.dx_max = 0.0
        self.mouse = _Mouse(self)
        self.cho_ms = 0

    def locator(self, sel):
        return _Loc(self, sel)

    def evaluate(self, _js, _arg=None):
        return RAY

    def wait_for_timeout(self, ms):
        self.cho_ms += ms


def _uoc(theta: float):
    """Bộ ước giả trả θ cố định; `khoang_keo_px` lấy bản THẬT để đột biến ở đó bị bắt."""
    from tiktok_music_downloader.captcha_xoay_uoc_goc import khoang_keo_px
    return lambda: SimpleNamespace(
        uoc_goc=lambda a, b: SimpleNamespace(lech_do=2 * theta, theta_do=theta, do_tin=5.0),
        khoang_keo_px=khoang_keo_px)


@pytest.mark.parametrize("theta", [10.0, 95.0704, 139.5, 175.0])
def test_keo_dung_khoang_thi_qua_ngay_lan_dau(theta):
    t = _Trang(theta)
    assert cx.thu_tu_giai(t, rng=random.Random(1), nap_uoc=_uoc(theta)) == cx.DA_QUA
    assert len(t.lan_tha) == 1 and t.lan_tha[0] == pytest.approx(t.d_dung, abs=1e-6)


def test_uoc_sai_thi_thu_du_so_lan_roi_tra_truot():
    t = _Trang(120.0)
    assert cx.thu_tu_giai(t, rng=random.Random(2), nap_uoc=_uoc(60.0)) == cx.TRUOT
    assert len(t.lan_tha) == cx.SO_LAN_THU


def test_khong_co_captcha_xoay_thi_khong_cham_chuot():
    t = _Trang(50.0, co_captcha=False)
    assert cx.thu_tu_giai(t, nap_uoc=_uoc(50.0)) == cx.KHONG_CO
    assert t.lan_tha == [] and t.mouse.x == 0.0


def test_loi_trong_luc_giai_tra_loi_khong_nem():
    t = _Trang(50.0)

    def hong():
        raise RuntimeError("cv2 hỏng")

    assert cx.thu_tu_giai(t, nap_uoc=hong) == cx.LOI


@pytest.mark.parametrize("hat", range(8))
def test_quy_dao_ket_thuc_dung_dich_khong_lui_qua_goc_vuot_it(hat):
    d = 137.0
    pts = cx.quy_dao_keo(d, random.Random(hat))
    assert pts[-1] == (d, 0.0)
    assert min(x for x, _ in pts) >= 0.0
    assert max(x for x, _ in pts) <= d * 1.04 + 1e-9
    assert all(abs(y) <= 1.5 for _, y in pts)
    assert len(pts) >= 20


def test_co_mac_dinh_tat(monkeypatch):
    monkeypatch.delenv(cx.ENV_TU_GIAI, raising=False)
    assert cx.tu_giai_dang_bat() is False
    monkeypatch.setenv(cx.ENV_TU_GIAI, "1")
    assert cx.tu_giai_dang_bat() is True


# --- nối vào scraper ---------------------------------------------------------------------------

def _dung_scraper(monkeypatch, ket_qua):
    goi = {"thu": 0, "reload": 0}

    def thu(_page):
        goi["thu"] += 1
        return ket_qua

    monkeypatch.setattr(cx, "thu_tu_giai", thu)
    monkeypatch.setattr(scraper_mod, "_cho_link", lambda p: True)
    page = SimpleNamespace(reload=lambda **k: goi.__setitem__("reload", goi["reload"] + 1))
    return page, goi


def test_scraper_co_tat_khong_thu_giai(monkeypatch):
    monkeypatch.delenv(cx.ENV_TU_GIAI, raising=False)
    page, goi = _dung_scraper(monkeypatch, cx.DA_QUA)
    scraper_mod._tu_giai_neu_bi_chan(page, {"rong": 1})
    assert goi == {"thu": 0, "reload": 0}


def test_scraper_da_co_feed_khong_thu_giai(monkeypatch):
    monkeypatch.setenv(cx.ENV_TU_GIAI, "1")
    page, goi = _dung_scraper(monkeypatch, cx.DA_QUA)
    scraper_mod._tu_giai_neu_bi_chan(page, {"co_du_lieu": 1})
    assert goi == {"thu": 0, "reload": 0}


@pytest.mark.parametrize("kq,reload", [(cx.DA_QUA, 1), (cx.TRUOT, 0), (cx.LOI, 0), (cx.KHONG_CO, 0)])
def test_scraper_qua_thi_tai_lai_mot_lan_con_lai_thi_khong(monkeypatch, kq, reload):
    monkeypatch.setenv(cx.ENV_TU_GIAI, "1")
    page, goi = _dung_scraper(monkeypatch, kq)
    scraper_mod._tu_giai_neu_bi_chan(page, {"rong": 1})
    assert goi == {"thu": 1, "reload": reload}
