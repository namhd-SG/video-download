"""Vòng worker không được chết + cổng đĩa lúc NHẬN job.

Đã xảy ra 7 lần trên mini (23–24/09): `sqlite3.OperationalError: disk I/O error` ở
`claim_next_pending_job` lọt ra `JobWorker._loop` ⇒ luồng `videodl-worker` chết im
lặng, web vẫn phục vụ, job kẹt 'pending' tới lần restart sau.

Chạy JobWorker THẬT trên DB tạm; chỉ thay chỗ ném lỗi và phép đo đĩa.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from web import models
from web import queue as queue_mod
from web.queue import JobWorker

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


@dataclass
class _Dia:
    ok: bool
    reason: str | None = None


def _cho(dieu_kien, giay=5.0):
    han = time.monotonic() + giay
    while time.monotonic() < han:
        if dieu_kien():
            return True
        time.sleep(0.02)
    return dieu_kien()


def _xong(db_path, job_id):
    def _f(db, _dl, _ck, job):
        models.finish_job(db, job["id"], "done")
    return _f


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "jobs.db"
    models.init_db(p)
    return p


def test_loi_o_claim_khong_giet_vong_job_sau_van_chay(db_path, tmp_path, monkeypatch):
    """Hai lần `OperationalError` ở claim ⇒ vòng vẫn sống, đếm lỗi, rồi job vẫn chạy.
    Đột biến bỏ try trong `_loop` ⇒ luồng chết ở lần ném đầu ⇒ job không bao giờ done ⇒ ĐỎ."""
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    that = models.claim_next_pending_job
    con_lai = {"n": 2}

    def claim_hong(p):
        if con_lai["n"] > 0:
            con_lai["n"] -= 1
            raise sqlite3.OperationalError("disk I/O error")
        return that(p)

    monkeypatch.setattr(models, "claim_next_pending_job", claim_hong)
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=_xong(db_path, job_id), disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: models.get_job(db_path, job_id)["trang_thai"] == "done")
        tt = w.trang_thai()
        assert tt["song"] is True
        assert tt["loi_lien_tiep"] == 0, "vòng thành công sau lỗi phải xoá bộ đếm"
        assert tt["loi_cuoi"] == "OperationalError"
    finally:
        w.stop()


def test_loi_lap_duoc_dem_va_hien_ra(db_path, tmp_path, monkeypatch):
    """Lỗi kéo dài ⇒ `trang_thai()` nói worker đang lỗi lặp N lần (N ≥ 2), luồng vẫn sống."""
    def claim_luon_hong(_p):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(models, "claim_next_pending_job", claim_luon_hong)
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.005,
                  disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: w.trang_thai()["loi_lien_tiep"] >= 2)
        assert w.trang_thai()["song"] is True
    finally:
        w.stop()


def test_job_do_danh_dau_interrupted_va_job_sau_van_chay(db_path, tmp_path):
    """`process_job` ném (vd `finish_job` trượt) khi job còn 'running' ⇒ ghi 'interrupted'
    cho đúng job đó, rồi job kế vẫn được nhận."""
    j1 = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    j2 = models.create_job(db_path, "https://www.tiktok.com/music/y-2", 1, "b")

    def xu_ly(db, _dl, _ck, job):
        if job["id"] == j1:
            raise sqlite3.OperationalError("database or disk is full")
        models.finish_job(db, job["id"], "done")

    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=xu_ly, disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: models.get_job(db_path, j2)["trang_thai"] == "done")
    finally:
        w.stop()
    assert models.get_job(db_path, j1)["trang_thai"] == "interrupted"


def test_dia_duoi_nguong_khong_nhan_job_roi_nhan_khi_co_cho(db_path, tmp_path):
    """Đĩa dưới ngưỡng ⇒ job ở lại 'pending' (không tự fail), `cho_dia` mang lý do;
    đĩa có chỗ lại ⇒ job chạy. Đột biến bỏ cổng ⇒ job chạy ngay khi đĩa cạn ⇒ ĐỎ."""
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    dia = {"ok": False}
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=_xong(db_path, job_id),
                  disk_guard_fn=lambda _p: _Dia(dia["ok"], None if dia["ok"] else "đĩa còn 120 MB"))
    w.start()
    try:
        assert _cho(lambda: w.trang_thai()["cho_dia"] == "đĩa còn 120 MB")
        time.sleep(0.2)
        assert models.get_job(db_path, job_id)["trang_thai"] == "pending"
        dia["ok"] = True
        assert _cho(lambda: models.get_job(db_path, job_id)["trang_thai"] == "done")
        assert w.trang_thai()["cho_dia"] is None
    finally:
        w.stop()


def test_cong_dia_mac_dinh_dung_nguong_cua_cong_tao_job():
    """Không có hằng mới: worker mặc định dùng đúng `check_disk_guard` (ngưỡng
    `DEFAULT_MIN_FREE_BYTES`) như cổng `POST /jobs`."""
    from web.lifecycle import check_disk_guard
    w = JobWorker(Path("/tmp/khong-can"), Path("/tmp/dl"), Path("/tmp/ck"))
    assert w._disk_guard_fn is check_disk_guard


def test_mark_job_interrupted_chi_doi_hang_con_running(db_path):
    j = models.create_job(db_path, "u", 1, "a")
    assert models.mark_job_interrupted(db_path, j) is False  # còn 'pending'
    with sqlite3.connect(db_path) as c:
        c.execute("UPDATE jobs SET trang_thai='running' WHERE id=?", (j,))
    assert models.mark_job_interrupted(db_path, j) is True
    models_row = models.get_job(db_path, j)
    assert models_row["trang_thai"] == "interrupted" and models_row["xong_luc"]


@pytest.mark.parametrize("tt, ma", [
    ({"song": False, "loi_lien_tiep": 0, "loi_cuoi": None, "cho_dia": None}, "chet"),
    ({"song": True, "loi_lien_tiep": 3, "loi_cuoi": "OperationalError", "cho_dia": None}, "loi_lap"),
    ({"song": True, "loi_lien_tiep": 0, "loi_cuoi": None, "cho_dia": "đĩa còn 1 MB"}, "cho_dia"),
    ({"song": True, "loi_lien_tiep": 0, "loi_cuoi": None, "cho_dia": None}, "ok"),
])
def test_healthz_mang_ma_worker_khong_mang_chi_tiet(monkeypatch, tt, ma):
    import web.app as app_mod
    monkeypatch.setattr(app_mod.worker, "trang_thai", lambda: tt)
    ra = app_mod.healthz()
    assert ra == {"status": "ok", "worker": ma}, "healthz không được lộ chữ lỗi/đường dẫn"


def test_chu_badge_worker_js():
    """`chuBadgeWorker` THẬT trích từ app.js (harness `tests/js/badge-worker.js`)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này KHÔNG chạy")
    r = subprocess.run([node, str(Path(__file__).parent / "js" / "badge-worker.js"),
                        str(STATIC / "app.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    do = json.loads(r.stdout)
    assert do["null"] == "" and do["ok"] == ""
    assert "đã dừng" in do["chet"]
    assert "3 lần" in do["loi"] and "OperationalError" in do["loi"]
    assert "đĩa còn 1 MB" in do["dia"]


def test_tran_nghi_loi_co_han():
    assert 0 < queue_mod.TRAN_NGHI_LOI_GIAY <= 300
