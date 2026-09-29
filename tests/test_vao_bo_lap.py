"""Thread định kỳ của bộ kiểm "đã vào bộ": trễ lượt đầu, thoát sạch, sống sót lỗi."""
from __future__ import annotations

import threading
import time

import pytest

from drive_gia_vao_bo import DriveGia
from web import app as app_mod
from web import models
from web.vao_bo_lap import CHU_KY_GIAY, TRE_LUOT_DAU_GIAY, LapVaoBo

TOI = "toi@astronex.ai"


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "jobs.db"
    models.init_db(p)
    return p


def test_luot_dau_tre_khoang_60_giay():
    assert TRE_LUOT_DAU_GIAY == 60.0
    assert CHU_KY_GIAY >= 60.0


def test_stop_truoc_khi_het_do_tre_thoat_ngay_va_khong_cham_drive(db):
    goi = []
    lap = LapVaoBo(db, lambda: goi.append("drive") or DriveGia(), tre_dau=30.0, chu_ky=30.0)
    lap.start()
    t0 = time.monotonic()
    lap.stop(timeout=5)
    assert time.monotonic() - t0 < 2.0
    assert goi == [] and not lap._thread.is_alive()


def test_chay_sau_do_tre_roi_dinh_ky_va_song_sot_loi(db):
    dem = {"n": 0}
    xong = threading.Event()

    def tao():
        dem["n"] += 1
        if dem["n"] == 1:
            raise RuntimeError("Drive sập lượt đầu")
        if dem["n"] >= 3:
            xong.set()
        return DriveGia()
    lap = LapVaoBo(db, tao, tre_dau=0.0, chu_ky=0.02)
    lap.start()
    assert xong.wait(5), "thread phải sống sót lỗi ở lượt 1 và chạy tiếp"
    lap.stop()
    assert dem["n"] >= 3


def test_drive_chua_cau_hinh_thi_bo_qua_va_tra_false(db):
    d = DriveGia()
    d.cau_hinh = False
    lap = LapVaoBo(db, lambda: d)
    assert lap.chay_mot_luot() is False and d.goi == []


def test_lifespan_khoi_va_dung_thread_va_env_tat_duoc(tmp_path, monkeypatch):
    import asyncio
    khoi = []
    monkeypatch.setattr(LapVaoBo, "start", lambda self: khoi.append("start"))
    monkeypatch.setattr(LapVaoBo, "stop", lambda self, timeout=5.0: khoi.append("stop"))
    monkeypatch.setattr(app_mod.worker, "start", lambda: None)
    monkeypatch.setattr(app_mod.worker, "stop", lambda: None)
    for k in ("DATA_DIR", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR"):
        monkeypatch.setattr(app_mod, k, tmp_path / k.lower())
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs.db")

    async def chay():
        async with app_mod._lifespan(app_mod.app):
            pass
    asyncio.run(chay())
    assert khoi == ["start", "stop"]

    khoi.clear()
    monkeypatch.setenv(app_mod.ENV_TAT_LAP_VAO_BO, "1")
    asyncio.run(chay())
    assert khoi == []
