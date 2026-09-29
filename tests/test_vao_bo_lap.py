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
    monkeypatch.delenv(app_mod.ENV_TAT_LAP_VAO_BO, raising=False)    # conftest đặt mặc định

    async def chay():
        async with app_mod._lifespan(app_mod.app):
            pass
    asyncio.run(chay())
    assert khoi == ["start", "stop"]

    khoi.clear()
    monkeypatch.setenv(app_mod.ENV_TAT_LAP_VAO_BO, "1")
    asyncio.run(chay())
    assert khoi == []


def test_moi_truong_test_mac_dinh_khong_khoi_thread(tmp_path, monkeypatch):
    """`conftest.py` đặt `VIDEODL_TAT_LAP_VAO_BO=1` từ lúc pytest khởi động ⇒ mọi app thật
    trong suite (kể cả fixture module của test trình duyệt) KHÔNG khởi bộ kiểm định kỳ."""
    import asyncio
    khoi = []
    monkeypatch.setattr(LapVaoBo, "start", lambda self: khoi.append("start"))
    monkeypatch.setattr(app_mod.worker, "start", lambda: None)
    monkeypatch.setattr(app_mod.worker, "stop", lambda: None)
    for k in ("DATA_DIR", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR"):
        monkeypatch.setattr(app_mod, k, tmp_path / k.lower())
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs.db")

    async def chay():
        async with app_mod._lifespan(app_mod.app):
            pass
    asyncio.run(chay())
    assert khoi == [], "không được khởi thread khi chạy dưới pytest"


def test_mot_luot_tron_an_roi_don_roi_xoa_anh(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODL_BAT_DON_NGAY7", "1")
    """Một lượt trọn theo đúng thứ tự: video có bản sao → ẩn (lượt kiểm), video đã ẩn đủ
    7 ngày → nguồn vào Thùng rác + ảnh bị xoá (lượt dọn), trong CÙNG một `chay_mot_luot`."""
    from datetime import datetime, timedelta, timezone
    from web import models_vao_bo
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 2, TOI)
    fid = lambda i: f"1Src{i:03d}_AbCdEfGhIjKl"  # noqa: E731
    for i in (1, 2):
        models.record_video(db, job_id=job, video_id=f"v{i}", url=f"https://t.co/{i}",
                            drive_file_id=fid(i), tao_luc=f"2026-09-01T00:00:0{i}+00:00")
    # v2 đã ẩn từ 8 ngày trước; v1 chưa ẩn nhưng đã có bản sao trên Drive.
    cu = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    models_vao_bo.ghi_da_vao_bo(db, "v2", TOI, [{"ban_copy_id": "ban2", "folder_id": "BO1",
                                                 "ma_bo": "N.1", "bang_chung": "properties"}], cu)
    d = DriveGia()
    d.dat_ten_thu_muc("BO1", "N.2809C - x")
    for i in (1, 2):
        d.them_nguon(fid(i))
        d.them_ban(f"ban{i}", fid(i), folder="BO1")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    (thumbs / "v2.webp").write_bytes(b"x")
    (thumbs / "v1.webp").write_bytes(b"x")

    assert LapVaoBo(db, lambda: d).chay_mot_luot() is True

    with models._connect(db) as c:
        vb = {r["video_id"]: dict(r) for r in c.execute("SELECT * FROM video_vao_bo")}
    assert vb["v1"]["an_luc"] and vb["v1"]["drive_don_luc"] is None, "v1 vừa ẩn, chưa đủ 7 ngày"
    assert vb["v2"]["drive_don_luc"], "v2 đã dọn"
    assert [a for t, a in d.goi if t == "bo_vao_thung_rac"] == [fid(2)]
    assert not (thumbs / "v2.webp").exists() and (thumbs / "v1.webp").exists()


def test_mot_buoc_hong_khong_chan_cac_buoc_sau(db, monkeypatch):
    from web import vao_bo_don, vao_bo_kiem, vao_bo_thumbs
    chay = []
    monkeypatch.setattr(vao_bo_kiem, "chay_luot_kiem",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kiểm hỏng")))
    monkeypatch.setattr(vao_bo_don, "chay_luot_don", lambda *a, **k: chay.append("don"))
    monkeypatch.setattr(vao_bo_thumbs, "don_thumbs", lambda *a, **k: chay.append("anh"))
    assert LapVaoBo(db, lambda: DriveGia()).chay_mot_luot() is True
    assert chay == ["don", "anh"]
