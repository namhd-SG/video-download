"""Bộ chuyển `PhienFB` với trình duyệt GIẢ (không mạng, không Chrome): ẩn danh khi không cookie, bắt XHR theo whitelist, đọc
thẻ script / hộp thoại, dọn profile tạm ở mọi lối ra, log không có URL, mặc định headless."""
from __future__ import annotations

import json
import logging
import os
import time

import pytest

from tiktok_music_downloader import fb_trinh_duyet as bd
from tiktok_music_downloader.fb_quet_cuon import DauDomFB

GIA_TRI = "GIA-TRI-BI-MAT-987654"
TEN_OK = "CometProfilePlusVideosRootQuery"


def _jar(tmp_path) -> str:
    cs = [{"name": "c_user", "value": GIA_TRI, "domain": ".facebook.com", "path": "/", "secure": True,
           "httpOnly": True, "sameSite": "no_restriction", "expirationDate": time.time() + 86400 * 30.5}]
    p = tmp_path / "jar.json"
    p.write_text(json.dumps(cs), encoding="utf-8")
    return str(p)


class _Req:
    def __init__(self, post, headers=None):
        self.post_data, self.headers = post, headers or {}


class _Resp:
    def __init__(self, url, post, body=b"{}", status=200, loi_body=False, headers=None):
        self.url, self.request, self.status, self._b, self._loi = url, _Req(post, headers), status, body, loi_body

    def body(self):
        if self._loi:
            raise RuntimeError("Target closed")
        return self._b


class _Loc:
    def __init__(self, n, loi_click=None):
        self._n, self._loi = n, loi_click
        self.first = self

    def count(self):
        return self._n

    def click(self, timeout=None):
        if self._loi:
            raise self._loi


class _Page:
    def __init__(self, hop_thoai=False, nut_dong=False, loi_goto=None, loi_click=None, scripts=("{}",)):
        self.handlers, self.url, self.cuon = {}, "https://www.facebook.com/x/videos", []
        self.mouse = self
        self.hop_thoai, self.nut_dong, self._loi_goto, self._loi_click, self._scripts = (
            hop_thoai, nut_dong, loi_goto, loi_click, list(scripts))

    def on(self, ten, fn):
        self.handlers[ten] = fn

    def wheel(self, dx, dy):
        self.cuon.append(dy)

    def locator(self, sel):
        if sel == bd._CHON_HOP_THOAI:
            return _Loc(1 if self.hop_thoai else 0)
        if sel == bd._CHON_NUT_DONG:
            return _Loc(1 if self.nut_dong else 0, self._loi_click)
        return _Loc(0)

    def eval_on_selector_all(self, sel, js):
        assert "application/json" in sel
        return self._scripts

    def goto(self, url, **kw):
        if self._loi_goto:
            raise self._loi_goto
        self.url = url
        return type("R", (), {"status": 200})()


class _Ctx:
    def __init__(self, page):
        self.page, self.pages, self.cookies, self.dong = page, [page], None, False
        self.so_lan_them_cookie = 0

    def add_cookies(self, c):
        self.so_lan_them_cookie += 1
        self.cookies = c

    def new_page(self):
        return self.page

    def close(self):
        self.dong = True


class _Pw:
    def __init__(self):
        self.dung = False

    def stop(self):
        self.dung = True


def _khoi_dong_gia(luu: dict, page=None):
    def kd(thu_muc, *, headless, proxy):
        luu.update(thu_muc=thu_muc, headless=headless, proxy=proxy, page=page or _Page())
        assert os.path.isdir(thu_muc)
        luu["ctx"], luu["pw"] = _Ctx(luu["page"]), _Pw()
        return luu["pw"], luu["ctx"]
    return kd


# ------------------------------------------------------------------------------- ẩn danh / cookie

def test_khong_cookie_la_an_danh_khong_doc_tep_khong_them_cookie_va_dong_don_profile():
    luu = {}
    with bd.PhienFB(None, headless=True, khoi_dong=_khoi_dong_gia(luu)) as t:
        assert luu["ctx"].so_lan_them_cookie == 0 and luu["ctx"].cookies is None
        assert t.mo("https://www.facebook.com/x/videos") == 200
        t.cuon()
        assert luu["page"].cuon == [bd._CUON_PIXEL]
    assert luu["ctx"].dong and luu["pw"].dung and not os.path.exists(luu["thu_muc"])   # profile tạm bị xoá


def test_mac_dinh_tham_so_cookie_la_none_va_gia_tri_co_duong_dan_thi_nap_cookie(tmp_path):
    luu = {}
    with bd.PhienFB(khoi_dong=_khoi_dong_gia(luu)):                    # không truyền gì ⇒ ẩn danh
        assert luu["ctx"].so_lan_them_cookie == 0
    luu = {}
    with bd.PhienFB(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu)):    # chỗ dành cho Đường B
        ck = {c["name"]: c for c in luu["ctx"].cookies}
        assert ck["c_user"]["sameSite"] == "None" and ck["c_user"]["domain"] == ".facebook.com"


def test_mac_dinh_headless_headful_khi_dat_bien_moi_truong(monkeypatch):
    monkeypatch.delenv(bd.ENV_FB_HEADFUL, raising=False)
    assert bd.headless_dang_bat() is True
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu)):
        assert luu["headless"] is True
    monkeypatch.setenv(bd.ENV_FB_HEADFUL, "1")
    assert bd.headless_dang_bat() is False
    assert bd.ENV_FB_HEADFUL == "VIDEODL_FB_HEADFUL"


def test_proxy_duoc_chuyen_cho_trinh_duyet():
    luu = {}
    with bd.PhienFB(None, proxy="http://p:1", khoi_dong=_khoi_dong_gia(luu)):
        assert luu["proxy"] == "http://p:1"


# ------------------------------------------------------------------------------- XHR

def test_chi_bat_xhr_whitelist_va_lay_xhr_rut_can():
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu)) as t:
        h = luu["page"].handlers["response"]
        g = "https://www.facebook.com/api/graphql/"
        h(_Resp(g, f"fb_api_req_friendly_name={TEN_OK}", b'{"a": 1}'))
        h(_Resp(g, "fb_api_req_friendly_name=useInstreamAdsHaloFetcherQuery", b"{}"))            # quảng cáo: loại
        h(_Resp(g, "fb_api_req_friendly_name=CometChannelTabVideoPreviewRootQuery", b"{}"))       # xem trước: loại
        h(_Resp(g, "", b'{"b": 2}', headers={"x-fb-friendly-name": TEN_OK}))                       # tên ở header
        h(_Resp("https://www.facebook.com/static/x.js", "", b"//"))
        h(_Resp(g, f"fb_api_req_friendly_name={TEN_OK}", status=429, loi_body=True))              # thân đọc lỗi
        xs = t.lay_xhr()
        assert [(x.status, x.body) for x in xs] == [(200, '{"a": 1}'), (200, '{"b": 2}'), (429, "")]
        assert t.lay_xhr() == []


def test_than_nhieu_dong_duoc_giu_nguyen():
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu)) as t:
        luu["page"].handlers["response"](_Resp("https://www.facebook.com/api/graphql/",
                                               f"fb_api_req_friendly_name={TEN_OK}", b'{"a":1}\n{"b":2}'))
        assert t.lay_xhr()[0].body == '{"a":1}\n{"b":2}'


# ------------------------------------------------------------------------------- script + hộp thoại

def test_lay_script_json_tra_noi_dung_cac_the_va_loi_doc_khong_nem():
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu, page=_Page(scripts=['{"a":1}', "{}"]))) as t:
        assert t.lay_script_json() == ['{"a":1}', "{}"]
        luu["page"].eval_on_selector_all = lambda *a: (_ for _ in ()).throw(RuntimeError("navigating"))
        assert t.lay_script_json() == []


@pytest.mark.parametrize("hop,nut,mong", [
    (False, False, DauDomFB()),
    (True, False, DauDomFB(co_hop_thoai_dang_nhap=True, co_nut_dong=False)),
    (True, True, DauDomFB(co_hop_thoai_dang_nhap=True, co_nut_dong=True)),
])
def test_dau_dom_la_co_dung_sai_hop_thoai_va_nut_dong(hop, nut, mong):
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu, page=_Page(hop_thoai=hop, nut_dong=nut))) as t:
        assert t.dau_dom() == mong


def test_dau_dom_loi_doc_khong_phai_tuong():
    luu = {}
    page = _Page()
    page.locator = lambda sel: (_ for _ in ()).throw(RuntimeError("navigating"))
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu, page=page)) as t:
        assert t.dau_dom() == DauDomFB()


def test_bam_dong_true_khi_bam_duoc_false_khi_nut_bien_mat():
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu, page=_Page(hop_thoai=True, nut_dong=True))) as t:
        assert t.bam_dong() is True
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(
            luu, page=_Page(hop_thoai=True, nut_dong=True, loi_click=TimeoutError("gone")))) as t:
        assert t.bam_dong() is False


# ------------------------------------------------------------------------------- dọn dẹp + log

def test_loi_giua_chung_van_dong_trinh_duyet_va_xoa_profile():
    luu = {}
    with pytest.raises(RuntimeError):
        with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu, page=_Page(loi_goto=RuntimeError("x")))) as t:
            t.mo("https://www.facebook.com/x/videos")
    assert luu["ctx"].dong and luu["pw"].dung and not os.path.exists(luu["thu_muc"])


def test_thieu_tep_cookie_no_truoc_khi_mo_chrome(tmp_path):
    goi = []
    with pytest.raises(Exception):
        with bd.PhienFB(str(tmp_path / "khong-co.json"), khoi_dong=lambda *a, **k: goi.append(1)):
            pass
    assert goi == []


def test_log_cua_phien_khong_chua_url_hay_ten_page(caplog):
    """ĐỘT BIẾN: ghi URL / tên page vào log ở `PhienFB` ⇒ ĐỎ."""
    caplog.set_level(logging.DEBUG)
    luu = {}
    with bd.PhienFB(None, khoi_dong=_khoi_dong_gia(luu, page=_Page(hop_thoai=True, nut_dong=True,
                                                                  loi_click=TimeoutError("ten-page-gia")))) as t:
        t.mo("https://www.facebook.com/ten-page-gia/videos")
        luu["page"].handlers["response"](_Resp("https://www.facebook.com/api/graphql/",
                                               f"fb_api_req_friendly_name={TEN_OK}", b"{}", loi_body=True))
        t.dau_dom()
        t.bam_dong()
    tat_ca = "\n".join(r.getMessage() for r in caplog.records)
    for tu in ("ten-page-gia", "facebook.com/", GIA_TRI):
        assert tu not in tat_ca


def test_thieu_patchright_bao_loi_ro(monkeypatch):
    from tiktok_music_downloader import ig_trinh_duyet as ig

    def hong():
        raise ImportError("khong co")
    monkeypatch.setattr(ig, "sync_playwright_patchright", hong)
    with pytest.raises(RuntimeError, match="patchright"):
        bd.khoi_dong_patchright("/tmp/x", headless=True, proxy=None)
