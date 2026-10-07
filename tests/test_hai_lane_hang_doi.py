"""Hai hàng đợi (lane `tiktok` / `khac`), hai worker cùng tiến trình.

Toàn bộ chạy trên `jobs.db` file thật trong tmp_path và `JobWorker` thật; chỉ `process_job_fn`
(thân việc tải) được thay bằng hàm giả có kiểm soát.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import time

import pytest

from web import app as app_mod
from web import models
from web import profile_theo_job
from web import queue as queue_mod
from web.queue import JobWorker

POLL = 0.05


class _Dia:
    ok = True
    reason = ""


def _dia_ok(_p):
    return _Dia()


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "jobs.db"
    models.init_db(p)
    return p


def _job(db, nen_tang):
    return models.create_job(db, f"https://x/{nen_tang}", 1, "a@x.vn", nen_tang=nen_tang)


def _trang_thai(db, jid):
    return models.get_job(db, jid)["trang_thai"]


def _cho(dieu_kien, giay=5.0):
    han = time.monotonic() + giay
    while time.monotonic() < han:
        if dieu_kien():
            return True
        time.sleep(0.01)
    return dieu_kien()


def _worker(db, tmp_path, lane, fn, **kw):
    return JobWorker(db, tmp_path / "dl", tmp_path / "ck", poll_interval=POLL,
                     process_job_fn=fn, disk_guard_fn=_dia_ok, lane=lane, **kw)


def _xong(db):
    def fn(db_path, _dl, _ck, job):
        with sqlite3.connect(db_path) as c:
            c.execute("UPDATE jobs SET trang_thai='done' WHERE id=?", (job["id"],))
    return fn


# --- T2: claim tách --------------------------------------------------------

def test_t2_claim_tach_hai_lane(db):
    yt, tt, ig = _job(db, "youtube"), _job(db, "tiktok"), _job(db, "instagram")
    # Lane khác nhặt yt rồi ig — KHÔNG BAO GIỜ tiktok, dù tiktok nằm giữa hàng.
    assert models.claim_next_pending_job(db, lane="khac")["id"] == yt
    assert models.claim_next_pending_job(db, lane="khac")["id"] == ig
    assert models.claim_next_pending_job(db, lane="khac") is None
    assert models.claim_next_pending_job(db, lane="tiktok")["id"] == tt
    assert models.claim_next_pending_job(db, lane="tiktok") is None


def test_t2_lane_tiktok_bo_qua_job_khac_dung_truoc(db):
    yt, tt = _job(db, "youtube"), _job(db, "tiktok")
    assert models.claim_next_pending_job(db, lane="tiktok")["id"] == tt
    assert _trang_thai(db, yt) == "pending"


def test_t2_lane_khac_bo_qua_nen_tang_bi_loai_tru(db):
    yt, ig = _job(db, "youtube"), _job(db, "instagram")
    assert models.claim_next_pending_job(db, lane="khac", loai_tru=("youtube",))["id"] == ig
    assert models.claim_next_pending_job(db, lane="khac", loai_tru=("youtube",)) is None
    assert _trang_thai(db, yt) == "pending"


def test_khong_truyen_lane_la_hanh_vi_cu_mot_hang_chung(db):
    yt, tt = _job(db, "youtube"), _job(db, "tiktok")
    assert models.claim_next_pending_job(db)["id"] == yt
    assert models.claim_next_pending_job(db)["id"] == tt


def test_lane_la_bi_tu_choi(db):
    with pytest.raises(ValueError):
        models.claim_next_pending_job(db, lane="lung-tung")


# --- T3: lane khác không bao giờ nhặt cho_giai ----------------------------

def _dat_cho_giai(db, jid):
    with sqlite3.connect(db) as c:
        c.execute("UPDATE jobs SET trang_thai='cho_giai', vao_trang_thai_luc='2026-01-01T00:00:00' "
                  "WHERE id=?", (jid,))


def test_t3_claim_khac_khong_nhat_cho_giai_nen_tang_khac(db):
    yt = _job(db, "youtube")
    _dat_cho_giai(db, yt)
    assert models.claim_next_pending_job(db, lane="khac") is None
    assert _trang_thai(db, yt) == "cho_giai"


def test_t3_worker_khac_voi_co_giai_bat_van_khong_nhat_cho_giai(db, tmp_path, monkeypatch):
    """Cờ giải captcha BẬT: lane TikTok sẽ truyền `uu_tien_cho_giai=True`; lane `khac` thì KHÔNG
    được. Worker thật, hàng có một dòng `cho_giai` của nền tảng khác (dòng tiktok sẽ không phân
    định vì bộ lọc nền tảng đã chặn trước)."""
    monkeypatch.setattr(profile_theo_job, "profile_captcha_dang_bat", lambda: True)
    yt = _job(db, "youtube")
    _dat_cho_giai(db, yt)
    da_goi = []
    w = _worker(db, tmp_path, "khac", lambda *a: da_goi.append(a))
    w.start()
    try:
        time.sleep(POLL * 8)
    finally:
        w.stop()
    assert da_goi == [] and _trang_thai(db, yt) == "cho_giai"


# --- T1: cách ly độ trễ ----------------------------------------------------

def test_t1_job_dai_o_lane_khac_khong_chan_tiktok(db, tmp_path):
    chan = threading.Event()
    khac_dang_chay = threading.Event()
    a_da_xu_ly: list[tuple[int, str]] = []

    def fn_khac(_db, _dl, _ck, job):
        khac_dang_chay.set()
        chan.wait(30)                              # job dài giả: giữ lane khác bận
        with sqlite3.connect(db) as c:
            c.execute("UPDATE jobs SET trang_thai='done' WHERE id=?", (job["id"],))

    def fn_tiktok(_db, _dl, _ck, job):
        a_da_xu_ly.append((job["id"], job["nen_tang"]))
        if job["nen_tang"] != "tiktok":            # lane A mà nhặt job khác ⇒ kẹt như hàng chung
            chan.wait(30)
        with sqlite3.connect(db) as c:
            c.execute("UPDATE jobs SET trang_thai='done' WHERE id=?", (job["id"],))

    yt1 = _job(db, "youtube")
    wb = _worker(db, tmp_path, "khac", fn_khac)
    wb.start()
    try:
        assert khac_dang_chay.wait(5) and _trang_thai(db, yt1) == "running"
        yt2 = _job(db, "youtube")                  # cũ hơn job tiktok, đang chờ sau yt1
        tt = _job(db, "tiktok")
        wa = _worker(db, tmp_path, "tiktok", fn_tiktok)
        t0 = time.monotonic()
        wa.start()
        try:
            assert _cho(lambda: _trang_thai(db, tt) != "pending", giay=2.0)
            tre = time.monotonic() - t0
            assert tre <= 2 * POLL + 0.5, f"tiktok chờ {tre:.2f}s sau job dài của lane khác"
            assert _cho(lambda: _trang_thai(db, tt) == "done")
            assert a_da_xu_ly == [(tt, "tiktok")]
            assert _trang_thai(db, yt2) == "pending"
        finally:
            chan.set()
            wa.stop()
    finally:
        chan.set()
        wb.stop()


# --- T9: boot sweep đúng một lần ------------------------------------------

def test_t9_khoi_dong_lane_khac_khong_danh_interrupted_job_dang_chay_cua_lane_tiktok(db, tmp_path):
    tt = _job(db, "tiktok")
    assert models.claim_next_pending_job(db, lane="tiktok")["id"] == tt   # lane A đang chạy nó
    assert _trang_thai(db, tt) == "running"
    w = _worker(db, tmp_path, "khac", lambda *a: None)
    w.start()
    try:
        time.sleep(POLL * 6)
        assert _trang_thai(db, tt) == "running"
    finally:
        w.stop()
    # Còn boot sweep thật thì vẫn đánh được: nó là việc của `quet_khoi_dong`.
    assert queue_mod.quet_khoi_dong(db) == 1 and _trang_thai(db, tt) == "interrupted"


def test_t9_lifespan_quet_dung_mot_lan_truoc_moi_worker(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    su_kien: list[str] = []

    class WorkerGia:
        def __init__(self, *a, lane="tiktok", **k):
            self.lane = lane

        def start(self):
            su_kien.append(f"start-{self.lane}")

        def stop(self):
            su_kien.append(f"stop-{self.lane}")

    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "DOWNLOADS_DIR", tmp_path / "downloads")
    monkeypatch.setattr(app_mod, "COOKIES_DIR", tmp_path / "cookies")
    monkeypatch.setattr(app_mod, "COOKIE_TMP_DIR", tmp_path / "tmp")
    monkeypatch.setattr(app_mod, "JobWorker", WorkerGia)
    monkeypatch.setattr(app_mod, "worker", WorkerGia(lane="tiktok"))
    monkeypatch.setattr(app_mod, "quet_khoi_dong", lambda p: su_kien.append("quet") or 0)
    monkeypatch.setenv(app_mod.ENV_TAT_LAP_VAO_BO, "1")

    async def chay():
        async with app_mod._lifespan(app_mod.app):
            pass

    asyncio.run(chay())
    assert su_kien.count("quet") == 1
    assert su_kien.index("quet") < su_kien.index("start-tiktok")
    assert su_kien.index("quet") < su_kien.index("start-khac")


# --- T7: healthz từng lane -------------------------------------------------

def test_t7_healthz_lane_khac_chet_thi_tiktok_van_ok(db, tmp_path, monkeypatch):
    wa = _worker(db, tmp_path, "tiktok", lambda *a: None)
    wb = _worker(db, tmp_path, "khac", lambda *a: None)       # chưa start = chết
    monkeypatch.setattr(app_mod, "worker", wa)
    monkeypatch.setattr(app_mod, "worker_khac", wb)
    wa.start()
    try:
        ra = app_mod.healthz()
        assert ra["lanes"] == {"tiktok": "ok", "khac": "chet"}
        assert ra["worker"] == "ok"                           # trường cũ = lane tiktok
        chi_tiet = app_mod.admin_worker(nguoi_tao="sep@astronex.ai")
        assert chi_tiet["lanes"]["tiktok"]["song"] is True
        assert chi_tiet["lanes"]["khac"]["song"] is False
        assert chi_tiet["song"] is True                       # trường phẳng cũ = lane tiktok
    finally:
        wa.stop()


def test_t7_healthz_lane_tiktok_chet_thi_khac_van_ok(db, tmp_path, monkeypatch):
    wa = _worker(db, tmp_path, "tiktok", lambda *a: None)
    wb = _worker(db, tmp_path, "khac", lambda *a: None)
    monkeypatch.setattr(app_mod, "worker", wa)
    monkeypatch.setattr(app_mod, "worker_khac", wb)
    wb.start()
    try:
        ra = app_mod.healthz()
        assert ra["lanes"] == {"tiktok": "chet", "khac": "ok"} and ra["worker"] == "chet"
    finally:
        wb.stop()


# --- T8: vị trí hàng -------------------------------------------------------

def test_t8_vi_tri_dem_trong_lane_cua_job(db):
    yt, tt = _job(db, "youtube"), _job(db, "tiktok")
    assert models.claim_next_pending_job(db, lane="khac")["id"] == yt     # yt đang chạy
    assert models.vi_tri_hang_doi(db, [tt]) == {tt: 1}                    # không đợi yt


def test_t8_vi_tri_khong_dem_cheo_chieu_nguoc_va_trong_cung_lane(db):
    tt1, tt2 = _job(db, "tiktok"), _job(db, "tiktok")
    yt1, yt2 = _job(db, "youtube"), _job(db, "youtube")
    models.claim_next_pending_job(db, lane="tiktok")                      # tt1 đang chạy
    assert models.vi_tri_hang_doi(db, [tt2, yt1, yt2]) == {tt2: 2, yt1: 1, yt2: 2}


def test_t8_cho_giai_nen_tang_khac_khong_co_vi_tri(db):
    yt = _job(db, "youtube")
    _dat_cho_giai(db, yt)                         # lane khác không bao giờ nhặt ⇒ không có chỗ trong hàng
    assert models.vi_tri_hang_doi(db, [yt]) == {}


# --- smoke SQLite hai luồng ------------------------------------------------

GIAY_SMOKE = float(os.environ.get("VIDEODL_SMOKE_GIAY", "10"))


def test_smoke_hai_luong_claim_va_cap_nhat_khong_loi_khoa_db(db):
    """Hai luồng claim+update trên cùng file DB trong `GIAY_SMOKE` giây, một luồng sản xuất job.
    0 `OperationalError`, và không job nào bị cả hai lane nhận."""
    dung = threading.Event()
    loi: list[BaseException] = []
    nhan: dict[str, list[int]] = {"tiktok": [], "khac": []}

    def san_xuat():
        i = 0
        try:
            while not dung.is_set():
                _job(db, "tiktok" if i % 2 == 0 else "youtube")
                i += 1
                time.sleep(0.002)
        except BaseException as e:  # noqa: BLE001
            loi.append(e)

    def tieu_thu(lane):
        try:
            while not dung.is_set():
                job = models.claim_next_pending_job(db, lane=lane)
                if job is None:
                    time.sleep(0.001)
                    continue
                nhan[lane].append(job["id"])
                models.set_job_pages(db, job["id"], 1)
                with sqlite3.connect(db, timeout=30) as c:
                    c.execute("UPDATE jobs SET trang_thai='done' WHERE id=?", (job["id"],))
        except BaseException as e:  # noqa: BLE001
            loi.append(e)

    luong = [threading.Thread(target=san_xuat)] + [threading.Thread(target=tieu_thu, args=(l,))
                                                   for l in ("tiktok", "khac")]
    for t in luong:
        t.start()
    time.sleep(GIAY_SMOKE)
    dung.set()
    for t in luong:
        t.join(timeout=30)
    assert not loi, f"{type(loi[0]).__name__}: {loi[0]}"
    assert nhan["tiktok"] and nhan["khac"]
    assert not set(nhan["tiktok"]) & set(nhan["khac"])
    with sqlite3.connect(db) as c:
        nen = dict(c.execute("SELECT id, nen_tang FROM jobs"))
    assert all(nen[i] == "tiktok" for i in nhan["tiktok"])
    assert all(nen[i] != "tiktok" for i in nhan["khac"])


# --- migration -------------------------------------------------------------

def _dem_moi_bang(path):
    with sqlite3.connect(path) as c:
        bang = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {b: c.execute(f'SELECT COUNT(*) FROM "{b}"').fetchone()[0] for b in bang}


def test_migration_chay_hai_lan_khong_mat_dong_va_khong_null(tmp_path):
    """jobs.db đời cũ (chưa có `nen_tang`, có 5 hàng jobs): chạy `init_db` hai lần ⇒
    số dòng MỌI bảng trước = sau, cột có mặt, 0 hàng NULL, hàng cũ thành 'tiktok'."""
    path = tmp_path / "jobs.db"
    cu = models._SCHEMA.replace(",\n    nen_tang TEXT NOT NULL DEFAULT 'tiktok'", "")
    assert "nen_tang" not in cu
    with sqlite3.connect(path) as c:
        c.execute(cu)
        c.execute(models._VIDEOS_SCHEMA)
        for i in range(5):
            c.execute("INSERT INTO jobs (url, tao_luc) VALUES (?, '2026-01-01T00:00:00')", (f"u{i}",))
        cot = [r[1] for r in c.execute("PRAGMA table_info(jobs)")]
        assert "nen_tang" not in cot
    models.init_db(path)
    truoc = _dem_moi_bang(path)
    assert truoc["jobs"] == 5
    models.init_db(path)
    assert _dem_moi_bang(path) == truoc
    with sqlite3.connect(path) as c:
        assert "nen_tang" in [r[1] for r in c.execute("PRAGMA table_info(jobs)")]
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE nen_tang IS NULL").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE nen_tang = 'tiktok'").fetchone()[0] == 5
