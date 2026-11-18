"""Bộ chuyển `PhienIG` với trình duyệt GIẢ (không mạng, không Chrome): nạp cookie Cookie-Editor đúng dạng, bắt XHR đích
theo tên, dọn profile tạm ở mọi lối ra, log không có cookie/URL, và mặc định headless."""
from __future__ import annotations

import json
import logging
import os
import time

import pytest

from tiktok_music_downloader import ig_trinh_duyet as bd
from tiktok_music_downloader import ig_xhr_phan_tich as ph

GIA_TRI = "GIA-TRI-BI-MAT-987654"


def _jar(tmp_path) -> str:
    cs = [{"name": "sessionid", "value": GIA_TRI, "domain": ".instagram.com", "path": "/", "secure": True,
           "httpOnly": True, "sameSite": "no_restriction", "expirationDate": time.time() + 86400 * 30.5,
           "hostOnly": False, "session": False, "storeId": "0", "id": 1},
          {"name": "ig_did", "value": "abc", "domain": ".instagram.com", "path": "/", "sameSite": "lax", "session": True}]
    p = tmp_path / "jar.json"
    p.write_text(json.dumps(cs), encoding="utf-8")
    return str(p)


class _Req:
    def __init__(self, post):
        self.post_data = post


class _Resp:
    def __init__(self, url, post, body=b"{}", status=200, loi_body=False):
        self.url, self.request, self.status, self._b, self._loi = url, _Req(post), status, body, loi_body

    def body(self):
        if self._loi:
            raise RuntimeError("Target closed")
        return self._b


class _Loc:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n


class _Page:
    def __init__(self, loi_goto=None):
        self.handlers, self.url, self.cuon = {}, "https://www.instagram.com/x/reels/", []
        self.mouse = self
        self._loi_goto = loi_goto

    def on(self, ten, fn):
        self.handlers[ten] = fn

    def wheel(self, dx, dy):
        self.cuon.append(dy)

    def title(self):
        return "Instagram"

    def inner_text(self, _s):
        return "Something went wrong"

    def locator(self, sel):
        return _Loc(1 if "username" in sel else 0)

    def goto(self, url, **kw):
        if self._loi_goto:
            raise self._loi_goto
        self.url = url
        return type("R", (), {"status": 200})()


class _Ctx:
    def __init__(self, page):
        self.page, self.pages, self.cookies, self.dong = page, [page], None, False

    def add_cookies(self, c):
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


def _khoi_dong_gia(luu: dict, page=None, loi_them_cookie=False):
    def kd(thu_muc, *, headless, proxy):
        luu.update(thu_muc=thu_muc, headless=headless, proxy=proxy, page=page or _Page())
        assert os.path.isdir(thu_muc)
        luu["ctx"], luu["pw"] = _Ctx(luu["page"]), _Pw()
        if loi_them_cookie:
            def hong(_c):
                raise RuntimeError("them cookie hong")
            luu["ctx"].add_cookies = hong
        return luu["pw"], luu["ctx"]
    return kd


def test_nap_cookie_cookie_editor_dung_dang_playwright_va_dong_don_profile(tmp_path):
    luu = {}
    with bd.PhienIG(_jar(tmp_path), headless=True, khoi_dong=_khoi_dong_gia(luu)) as t:
        ck = {c["name"]: c for c in luu["ctx"].cookies}
        assert ck["sessionid"]["sameSite"] == "None" and ck["ig_did"]["sameSite"] == "Lax"   # "no_restriction" ⇒ "None"
        assert isinstance(ck["sessionid"]["expires"], int) and ck["sessionid"]["domain"] == ".instagram.com"
        assert "storeId" not in ck["sessionid"] and "hostOnly" not in ck["sessionid"]
        assert t.mo("https://www.instagram.com/x/reels/") == 200
        t.cuon()
        assert luu["page"].cuon == [2500]
    assert luu["ctx"].dong and luu["pw"].dung and not os.path.exists(luu["thu_muc"])   # profile tạm bị xoá


def test_mac_dinh_headless_headful_khi_dat_bien_moi_truong(monkeypatch, tmp_path):
    monkeypatch.delenv(bd.ENV_IG_HEADFUL, raising=False)
    assert bd.headless_dang_bat() is True
    luu = {}
    with bd.PhienIG(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu)):
        assert luu["headless"] is True
    monkeypatch.setenv(bd.ENV_IG_HEADFUL, "1")
    assert bd.headless_dang_bat() is False


def test_chi_bat_xhr_dich_va_lay_xhr_rut_can(tmp_path):
    luu = {}
    with bd.PhienIG(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu)) as t:
        h = luu["page"].handlers["response"]
        h(_Resp("https://www.instagram.com/graphql/query", "fb_api_req_friendly_name=PolarisProfileReelsTabContentQuery",
                b'{"a": 1}'))
        h(_Resp("https://www.instagram.com/api/v1/clips/music/", "max_id=1", b'for (;;);{"items": []}'))
        h(_Resp("https://www.instagram.com/graphql/query", "fb_api_req_friendly_name=Khac", b"{}"))
        h(_Resp("https://www.instagram.com/static/x.js", "", b"//"))
        h(_Resp("https://www.instagram.com/api/v1/clips/music/", "", status=429, loi_body=True))   # thân đọc lỗi
        xs = t.lay_xhr()
        assert [(x.status, x.size) for x in xs] == [(200, 8), (200, 22), (429, 0)]
        assert xs[1].body.startswith("for (;;);")                                  # giữ NGUYÊN, bóc ở lớp phân tích
        assert t.lay_xhr() == []


def test_dau_dom_la_co_dung_sai_khong_chua_chu_trang(tmp_path):
    luu = {}
    with bd.PhienIG(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu)) as t:
        d = t.dau_dom()
        assert d == ph.DauDom(co_o_ten_dang_nhap=True, co_nut_dang_nhap=False, tieu_de_loi=False, chu_loi=True)


def test_dau_dom_lien_ket_accounts_login_la_nut_dang_nhap(tmp_path):
    """Smoke thật 18/11: trang audio thiếu sessionid chỉ lộ mất phiên qua `a[href*='/accounts/login']`."""
    class _PageLienKet(_Page):
        def locator(self, sel):
            return _Loc(1 if sel == "a[href*='/accounts/login']" else 0)

    luu = {}
    with bd.PhienIG(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu, page=_PageLienKet())) as t:
        assert t.dau_dom().co_nut_dang_nhap is True


def test_loi_giua_chung_van_dong_trinh_duyet_va_xoa_profile(tmp_path):
    luu = {}
    with pytest.raises(RuntimeError):
        with bd.PhienIG(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu, page=_Page(loi_goto=RuntimeError("x")))) as t:
            t.mo("https://www.instagram.com/x/reels/")
    assert luu["ctx"].dong and luu["pw"].dung and not os.path.exists(luu["thu_muc"])


def test_nap_cookie_truot_van_don_dep_va_thieu_jar_no_truoc_khi_mo_chrome(tmp_path):
    luu = {}
    with pytest.raises(RuntimeError, match="them cookie hong"):
        with bd.PhienIG(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu, loi_them_cookie=True)):
            pass
    assert luu["ctx"].dong and luu["pw"].dung and not os.path.exists(luu["thu_muc"])
    goi = []
    with pytest.raises(Exception):
        with bd.PhienIG(str(tmp_path / "khong-co.json"), khoi_dong=lambda *a, **k: goi.append(1)):
            pass
    assert goi == []                                                              # chưa mở Chrome


def test_log_cua_phien_khong_chua_cookie_url(tmp_path, caplog):
    """ĐỘT BIẾN: ghi cookie vào log ở `PhienIG` ⇒ ĐỎ."""
    caplog.set_level(logging.DEBUG)
    luu = {}
    with bd.PhienIG(_jar(tmp_path), khoi_dong=_khoi_dong_gia(luu)) as t:
        t.mo("https://www.instagram.com/ten.gia/reels/")
        luu["page"].handlers["response"](_Resp("https://www.instagram.com/api/v1/clips/music/", "", b"{}", loi_body=True))
        t.dau_dom()
    tat_ca = "\n".join(r.getMessage() for r in caplog.records)
    for tu in (GIA_TRI, "sessionid", "ten.gia", "instagram.com/"):
        assert tu not in tat_ca


def test_thieu_patchright_bao_loi_ro(monkeypatch):
    def hong():
        raise ImportError("khong co")
    monkeypatch.setattr(bd, "sync_playwright_patchright", hong)
    with pytest.raises(RuntimeError, match="patchright"):
        bd.khoi_dong_patchright("/tmp/x", headless=True, proxy=None)
