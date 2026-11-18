"""Cờ `VIDEODL_PATCHRIGHT` (M4): tắt ⇒ `_open_context` y hệt trước; bật ⇒ Chrome thật, bỏ UA giả + stealth JS,
giữ viewport (worker captcha đổi toạ độ theo viewport). Gói patchright thiếu ⇒ quay về Playwright, không vỡ."""
from __future__ import annotations

import logging
import sys
import types
from types import SimpleNamespace

import pytest

from tiktok_music_downloader import scraper as scraper_mod
from tiktok_music_downloader import trinh_duyet_patchright as tdp


class _Ctx:
    def __init__(self):
        self.init_scripts: list = []

    def add_init_script(self, s):
        self.init_scripts.append(s)


class _Chromium:
    def __init__(self):
        self.goi: list[tuple[str, dict]] = []
        self.ctxs: list[_Ctx] = []

    def launch_persistent_context(self, **kw):
        self.goi.append(("persistent", kw))
        c = _Ctx()
        self.ctxs.append(c)
        return c

    def launch(self, **kw):
        self.goi.append(("launch", kw))
        chromium = self

        class _Browser:
            def new_context(self, **kw2):
                chromium.goi.append(("new_context", kw2))
                c = _Ctx()
                chromium.ctxs.append(c)
                return c

        return _Browser()


@pytest.fixture
def patchright_gia(monkeypatch):
    """Gói `patchright.sync_api` giả: `sync_playwright()` trả một vật đánh dấu."""
    goc = types.ModuleType("patchright")
    api = types.ModuleType("patchright.sync_api")
    api.sync_playwright = lambda: "PATCHRIGHT"
    goc.sync_api = api
    monkeypatch.setitem(sys.modules, "patchright", goc)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", api)


def _mo(tmp_path, profile: bool):
    ch = _Chromium()
    pw = SimpleNamespace(chromium=ch)
    d = tmp_path / "p" if profile else None
    scraper_mod._open_context(pw, headless=True, proxy=None, profile_dir=d, user_agent="UA-GIA")
    if d is not None:
        scraper_mod._nha_profile_dir(d)
    return ch


@pytest.mark.parametrize("profile", [True, False])
def test_co_tat_giu_nguyen_ua_stealth_khong_channel(monkeypatch, tmp_path, profile):
    monkeypatch.delenv(tdp.ENV_PATCHRIGHT, raising=False)
    ch = _mo(tmp_path, profile)
    kw_all = {k: v for _, kw in ch.goi for k, v in kw.items()}
    assert kw_all["user_agent"] == "UA-GIA"
    assert "channel" not in kw_all
    assert ch.ctxs[0].init_scripts == [scraper_mod.STEALTH_INIT_JS]


@pytest.mark.parametrize("profile", [True, False])
def test_co_bat_chrome_that_bo_ua_va_stealth_giu_viewport(monkeypatch, tmp_path, patchright_gia, profile):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    ch = _mo(tmp_path, profile)
    kw_all = {k: v for _, kw in ch.goi for k, v in kw.items()}
    assert kw_all["channel"] == "chrome"
    assert "user_agent" not in kw_all, "UA giả lệch Chrome thật là tín hiệu bất thường"
    assert kw_all["viewport"] == {"width": 1280, "height": 900}
    assert kw_all["locale"] == "en-US"
    assert ch.ctxs[0].init_scripts == []
    # channel thuộc lời gọi mở trình duyệt, không thuộc new_context (Playwright từ chối tham số lạ).
    assert all("channel" not in kw for loai, kw in ch.goi if loai == "new_context")


def test_sync_playwright_chon_patchright_khi_bat(monkeypatch, patchright_gia):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "on")
    assert scraper_mod.sync_playwright() == "PATCHRIGHT"


def test_sync_playwright_dung_playwright_khi_tat(monkeypatch, patchright_gia):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "0")
    monkeypatch.setattr(scraper_mod, "_sync_playwright_goc", lambda: "PLAYWRIGHT")
    assert scraper_mod.sync_playwright() == "PLAYWRIGHT"


def test_bat_ma_thieu_goi_thi_quay_ve_playwright_va_canh_bao(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv(tdp.ENV_PATCHRIGHT, "1")
    monkeypatch.setitem(sys.modules, "patchright", None)  # import ⇒ ImportError
    monkeypatch.setitem(sys.modules, "patchright.sync_api", None)
    monkeypatch.setattr(scraper_mod, "_sync_playwright_goc", lambda: "PLAYWRIGHT")
    with caplog.at_level(logging.WARNING, logger="ttmd"):
        assert scraper_mod.sync_playwright() == "PLAYWRIGHT"
        ch = _mo(tmp_path, True)
    assert ch.goi[0][1]["user_agent"] == "UA-GIA" and "channel" not in ch.goi[0][1]
    assert any("thiếu gói patchright" in r.getMessage() for r in caplog.records)
