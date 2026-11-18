"""Lane A 18/11 (ĐP-bc gật (1)+(3)):
(1) `_open_context` ghi INFO `[trinh-duyet] duong=…` — tín hiệu DƯƠNG đường nào đang chạy, không URL/cookie.
(3) `VIDEODL_PATCHRIGHT` bật mà thiếu gói patchright / thiếu Chrome ⇒ log ERROR lúc khởi động + /healthz 503.
Cờ tắt ⇒ /healthz y hệt trước (200, đúng 3 khoá)."""
from __future__ import annotations

import logging
import sys
import types
from types import SimpleNamespace

import pytest

from tiktok_music_downloader import scraper as scraper_mod
from tiktok_music_downloader import trinh_duyet_patchright as tdp


class _Ctx:
    def add_init_script(self, s):
        pass


class _Chromium:
    def launch_persistent_context(self, **kw):
        return _Ctx()

    def launch(self, **kw):
        return SimpleNamespace(new_context=lambda **kw2: _Ctx())


@pytest.fixture
def co_goi(monkeypatch):
    api = types.ModuleType("patchright.sync_api")
    goc = types.ModuleType("patchright")
    goc.sync_api = api
    monkeypatch.setitem(sys.modules, "patchright", goc)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", api)


@pytest.fixture
def thieu_goi(monkeypatch):
    monkeypatch.setitem(sys.modules, "patchright", None)  # import ⇒ ImportError
    monkeypatch.setitem(sys.modules, "patchright.sync_api", None)


@pytest.fixture
def co_chrome(monkeypatch, tmp_path):
    f = tmp_path / "chrome"
    f.write_text("")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(tdp._DUONG_CHROME, "darwin", str(f))


@pytest.fixture
def thieu_chrome(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setitem(tdp._DUONG_CHROME, "darwin", str(tmp_path / "khong-co"))


def _dong_trinh_duyet(caplog, tmp_path, headless, profile):
    pw = SimpleNamespace(chromium=_Chromium())
    d = tmp_path / "p" if profile else None
    with caplog.at_level(logging.INFO, logger="ttmd"):
        scraper_mod._open_context(pw, headless=headless, proxy=None, profile_dir=d,
                                  user_agent="UA-GIA")
    if d is not None:
        scraper_mod._nha_profile_dir(d)
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("[trinh-duyet]")]


# ---- (1) log INFO đường mở ----

@pytest.mark.parametrize("profile", [True, False])
def test_log_patchright_khi_bat_va_co_goi(monkeypatch, tmp_path, caplog, co_goi, profile):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    dong = _dong_trinh_duyet(caplog, tmp_path, headless=True, profile=profile)
    assert dong == ["[trinh-duyet] duong=patchright+chrome headless=True profile=%s"
                    % ("co" if profile else "khong")]


def test_log_headless_shell_khi_thieu_goi(monkeypatch, tmp_path, caplog, thieu_goi):
    """Đúng ca prod lặng lẽ lùi: phải thấy được tên headless-shell trong log."""
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    dong = _dong_trinh_duyet(caplog, tmp_path, headless=True, profile=True)
    assert dong == ["[trinh-duyet] duong=pw-headless-shell headless=True profile=co"]


@pytest.mark.parametrize("headless,duong", [(True, "pw-headless-shell"), (False, "pw-chromium")])
def test_log_khi_co_tat(monkeypatch, tmp_path, caplog, headless, duong):
    monkeypatch.delenv(tdp.ENV_PATCHRIGHT, raising=False)
    dong = _dong_trinh_duyet(caplog, tmp_path, headless=headless, profile=False)
    assert dong == [f"[trinh-duyet] duong={duong} headless={headless} profile=khong"]


def test_log_khong_lo_url_ua_hay_duong_profile(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv(tdp.ENV_PATCHRIGHT, raising=False)
    dong = _dong_trinh_duyet(caplog, tmp_path, headless=True, profile=True)
    assert dong and "UA-GIA" not in dong[0] and str(tmp_path) not in dong[0]


# ---- (3) kiem_cau_hinh ----

def test_kiem_cau_hinh_tat(monkeypatch, thieu_goi, thieu_chrome):
    monkeypatch.delenv(tdp.ENV_PATCHRIGHT, raising=False)
    assert tdp.kiem_cau_hinh() == tdp.MA_TAT


def test_kiem_cau_hinh_thieu_goi(monkeypatch, thieu_goi, co_chrome):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    assert tdp.kiem_cau_hinh() == tdp.MA_THIEU_GOI


def test_kiem_cau_hinh_thieu_chrome(monkeypatch, co_goi, thieu_chrome):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    assert tdp.kiem_cau_hinh() == tdp.MA_THIEU_CHROME


def test_kiem_cau_hinh_ok(monkeypatch, co_goi, co_chrome):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    assert tdp.kiem_cau_hinh() == tdp.MA_OK


def test_kiem_cau_hinh_khong_ghi_log(monkeypatch, thieu_goi, caplog):
    """/healthz gọi mỗi lượt thăm dò — không được tràn log."""
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    with caplog.at_level(logging.DEBUG, logger="ttmd"):
        tdp.kiem_cau_hinh()
    assert caplog.records == []


# ---- (3) /healthz + log khởi động ----

_TT_OK = {"song": True, "loi_lien_tiep": 0, "cho_dia": False}


@pytest.fixture
def app_mod(monkeypatch):
    import web.app as m
    monkeypatch.setattr(m.worker, "trang_thai", lambda: _TT_OK)
    monkeypatch.setattr(m, "worker_khac", SimpleNamespace(trang_thai=lambda: _TT_OK))
    return m


def test_healthz_co_tat_y_het_truoc(monkeypatch, app_mod):
    monkeypatch.delenv(tdp.ENV_PATCHRIGHT, raising=False)
    ra = app_mod.healthz()
    assert ra == {"status": "ok", "worker": "ok", "lanes": {"tiktok": "ok", "khac": "ok"}}


def test_healthz_co_bat_du_goi_va_chrome_y_het_truoc(monkeypatch, app_mod, co_goi, co_chrome):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    assert app_mod.healthz() == {"status": "ok", "worker": "ok", "lanes": {"tiktok": "ok", "khac": "ok"}}


@pytest.mark.parametrize("fx,ma", [("thieu_goi", "thieu_goi"), ("thieu_chrome", "thieu_chrome")])
def test_healthz_503_khi_co_bat_ma_thieu(monkeypatch, request, app_mod, co_chrome, fx, ma):
    if fx == "thieu_goi":
        request.getfixturevalue("thieu_goi")
    else:
        request.getfixturevalue("co_goi")
        request.getfixturevalue("thieu_chrome")
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    import json
    # Cổng deploy đọc MÃ HTTP, không đọc dict ⇒ phải là Response mang 503.
    r = app_mod.healthz()
    assert r.status_code == 503
    assert json.loads(r.body) == {"status": "loi_cau_hinh", "trinh_duyet": ma, "worker": "ok",
                        "lanes": {"tiktok": "ok", "khac": "ok"}}


def test_log_khoi_dong_error_khi_thieu_goi(monkeypatch, app_mod, thieu_goi, caplog):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    with caplog.at_level(logging.INFO):
        assert app_mod._bao_cau_hinh_trinh_duyet() == tdp.MA_THIEU_GOI
    loi = [r for r in caplog.records if r.levelno == logging.ERROR and "[trinh-duyet]" in r.getMessage()]
    assert len(loi) == 1 and "thieu_goi" in loi[0].getMessage()


def test_log_khoi_dong_im_khi_co_tat(monkeypatch, app_mod, caplog):
    monkeypatch.delenv(tdp.ENV_PATCHRIGHT, raising=False)
    with caplog.at_level(logging.DEBUG):
        assert app_mod._bao_cau_hinh_trinh_duyet() == tdp.MA_TAT
    assert not [r for r in caplog.records if "[trinh-duyet]" in r.getMessage()]


def test_lifespan_goi_bao_cau_hinh():
    """Khởi động thật phải gọi bước báo — bỏ dòng gọi trong `_lifespan` thì test này đỏ."""
    import inspect
    import web.app as m
    assert "_bao_cau_hinh_trinh_duyet()" in inspect.getsource(m._lifespan)
