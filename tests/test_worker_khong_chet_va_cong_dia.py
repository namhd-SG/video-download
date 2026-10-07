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

    def claim_hong(p, **kw):
        if con_lai["n"] > 0:
            con_lai["n"] -= 1
            raise sqlite3.OperationalError("disk I/O error")
        return that(p, **kw)

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
    assert ra["status"] == "ok" and ra["worker"] == ma and ra["lanes"]["tiktok"] == ma, \
        "healthz không được lộ chữ lỗi/đường dẫn"
    assert set(ra) == {"status", "worker", "lanes"}


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
    assert "2 job kẹt" in do["ket"]
    # Badge nhiều lane: vắng `lanes` ⇒ y như cũ; lane `khac` chết/lỗi hiện riêng, không bị lane TikTok che.
    assert do["cacLaneNull"] == "" and do["cacLaneOk"] == ""
    assert do["cacLaneKhongLanes"] == do["dia"]
    assert "Lane nền tảng khác" in do["cacLaneKhacChet"] and "đã dừng" in do["cacLaneKhacChet"]
    assert "đĩa 1 MB" in do["cacLaneCaHai"] and "lặp 2 lần" in do["cacLaneCaHai"]


def test_tran_nghi_loi_co_han():
    assert 0 < queue_mod.TRAN_NGHI_LOI_GIAY <= 300


def test_song_do_bang_thread_that_truoc_start_sau_stop(db_path, tmp_path):
    """Mã "chet" của healthz đọc `thread.is_alive()` THẬT: chưa start / đã stop ⇒ False.
    `_loop` giờ không chết vì `Exception`, nhưng luồng vẫn có thể không chạy (chưa start,
    đã stop, hay một `BaseException` như SystemExit lọt ra) — chính các ca đó phải hiện ra."""
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  disk_guard_fn=lambda _p: _Dia(True))
    assert w.trang_thai()["song"] is False
    w.start()
    try:
        assert w.trang_thai()["song"] is True
    finally:
        w.stop()
    assert _cho(lambda: w.trang_thai()["song"] is False)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_base_exception_lot_ra_thi_song_false(db_path, tmp_path, monkeypatch):
    """Chỉ `Exception` được bắt (cố ý: `stop`/Ctrl-C vẫn phải dừng được luồng). Một
    `BaseException` lọt ra giết luồng ⇒ `song` phải thành False, tức healthz nói "chet"."""
    def claim_thoat(_p, **_kw):
        raise SystemExit("mô phỏng luồng bị giết")

    monkeypatch.setattr(models, "claim_next_pending_job", claim_thoat)
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: w.trang_thai()["song"] is False)
    finally:
        w.stop()


@pytest.fixture
def may_chu(tmp_path):
    """App THẬT qua HTTP (uvicorn, cổng ngẫu nhiên), worker tắt, danh tính đổi được."""
    import socket
    import threading as th

    import uvicorn

    import web.app as app_mod
    from web.auth import require_user

    cu = {k: getattr(app_mod, k) for k in ("DATA_DIR", "DB_PATH")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp_path, tmp_path / "jobs.db"
    models.init_db(app_mod.DB_PATH)
    models.moi_admin_tu_env(app_mod.DB_PATH, ["sep@astronex.ai"])
    ai = {"email": "nguoi-thuong@astronex.ai"}
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: ai["email"]
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    t = th.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", ai
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)


def _get(url):
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def test_admin_worker_qua_http_nguoi_thuong_403_admin_200(may_chu):
    """Miễn trừ trong lưới route (`KHONG_CAN_KIEM_CHU`) chỉ đúng nếu route THẬT SỰ chặn ở
    server: người thường ⇒ 403, quản trị ⇒ 200 kèm chi tiết. Đo qua HTTP, không gọi hàm."""
    goc, ai = may_chu
    ma, _ = _get(goc + "/admin/worker")
    assert ma == 403
    ai["email"] = "sep@astronex.ai"
    ma, than = _get(goc + "/admin/worker")
    assert ma == 200 and set(than) == {"song", "loi_lien_tiep", "loi_cuoi", "cho_dia", "job_ket", "lanes",
                                                  "nen_tang_tat"}
    assert set(than["lanes"]) == {"tiktok", "khac"}
    ma, than = _get(goc + "/healthz")
    assert ma == 200 and set(than) == {"status", "worker", "lanes"}, "healthz chỉ có mã, không chi tiết"
    assert set(than["lanes"]) == {"tiktok", "khac"}


def test_job_dang_do_ma_danh_dau_cung_truot_thi_thu_lai_toi_khi_ghi_duoc(db_path, tmp_path, monkeypatch):
    """`process_job` ném VÀ `mark_job_interrupted` cũng trượt (DB hỏng hai lần) ⇒ id nằm
    trong `job_ket` (healthz "loi_lap"), rồi được ghi 'interrupted' ở vòng sau khi DB lành.
    Đột biến bỏ vòng thử lại ⇒ hàng kẹt 'running' mãi ⇒ ĐỎ."""
    j1 = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    that = models.mark_job_interrupted
    hong = {"con": 1}

    def danh_dau(p, jid):
        if hong["con"] > 0:
            hong["con"] -= 1
            raise sqlite3.OperationalError("disk I/O error")
        return that(p, jid)

    def xu_ly(db, _dl, _ck, job):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(models, "mark_job_interrupted", danh_dau)
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=xu_ly, disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: models.get_job(db_path, j1)["trang_thai"] == "interrupted")
        assert _cho(lambda: w.trang_thai()["job_ket"] == [])
    finally:
        w.stop()


def test_log_cho_dia_mot_lan_du_so_mb_doi_moi_vong(db_path, tmp_path, caplog):
    """Lý do chờ mang số MB đổi từng giây ⇒ log WARNING chỉ khi BƯỚC VÀO trạng thái chờ,
    nhưng `cho_dia` vẫn mang số mới nhất. Đột biến so theo chuỗi lý do ⇒ mỗi vòng một dòng ⇒ ĐỎ."""
    models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    dem = {"n": 0}

    def dia(_p):
        dem["n"] += 1
        return _Dia(False, f"đĩa còn {300 - dem['n']} MB")

    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.005, disk_guard_fn=dia)
    with caplog.at_level("WARNING", logger="videodl.web"):
        w.start()
        try:
            assert _cho(lambda: dem["n"] >= 10)
        finally:
            w.stop()
    cho = [r for r in caplog.records if "CHỜ" in r.getMessage()]
    assert len(cho) == 1, [r.getMessage() for r in cho]
    assert w.trang_thai()["cho_dia"] != "đĩa còn 299 MB", "cho_dia phải mang số mới nhất"


def test_nghi_lui_dan_va_co_tran(db_path, tmp_path, monkeypatch):
    """Nghỉ sau lỗi: poll, 2×, 4×… rồi kẹp ở trần. Đo cả hàm lẫn LỆNH NGHỈ THẬT của vòng
    (spy lên `_stop.wait`). Đột biến `wait(0)` hoặc bỏ trần ⇒ ĐỎ."""
    monkeypatch.setattr(queue_mod, "TRAN_NGHI_LOI_GIAY", 0.08)
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  disk_guard_fn=lambda _p: _Dia(True))
    assert [w.nghi_sau_loi(n) for n in (1, 2, 3, 4, 5)] == [0.01, 0.02, 0.04, 0.08, 0.08]
    assert w.nghi_sau_loi(10_000) == 0.08, "lỗi lặp rất lâu không được tràn số"

    def claim_luon_hong(_p):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(models, "claim_next_pending_job", claim_luon_hong)
    cho = []
    that = w._stop.wait
    w._stop.wait = lambda t=None: (cho.append(t), that(t))[1]
    w.start()
    try:
        assert _cho(lambda: len(cho) >= 5)
    finally:
        w.stop()
    assert cho[:5] == [0.01, 0.02, 0.04, 0.08, 0.08]


def test_claim_duoc_ma_xu_ly_hong_lien_tuc_van_nghi_lui_dan(db_path, tmp_path):
    """Nhận được job mà xử lý hỏng liên tục ⇒ vẫn nghỉ lùi dần (bộ đếm nghỉ chỉ xoá khi CẢ
    vòng trót lọt), không dội vào DB mỗi nhịp poll."""
    for i in range(6):
        models.create_job(db_path, f"https://www.tiktok.com/music/x-{i}", 1, "a")

    def xu_ly(db, _dl, _ck, job):
        raise sqlite3.OperationalError("database or disk is full")

    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.005,
                  process_job_fn=xu_ly, disk_guard_fn=lambda _p: _Dia(True))
    cho, bao = [], []
    that = w._stop.wait
    # Ghi số BÁO RA ngay lúc nghỉ (trong nhánh lỗi) — đọc sau `stop()` thì phụ thuộc giờ dừng.
    w._stop.wait = lambda t=None: (cho.append(t), bao.append(w._loi_lien_tiep), that(t))[2]
    w.start()
    try:
        assert _cho(lambda: len(cho) >= 3)
    finally:
        w.stop()
    assert cho[:3] == [0.005, 0.01, 0.02]
    assert bao[:3] == [1, 2, 3], "chuỗi lỗi phải được báo đúng số, không kẹt ở 1"


def test_mot_loi_thoang_qua_khong_bao_loi_lap_suot_job_lanh_ke_tiep(db_path, tmp_path):
    """Job A hỏng một lần (DB khoá thoáng qua) rồi job B chạy lành và LÂU ⇒ trong lúc B
    chạy, healthz không được báo "lỗi lặp". Đột biến xoá bộ đếm báo-ra sau khi xử lý xong
    (thay vì ngay khi nhận được job) ⇒ ĐỎ."""
    import threading
    ja = models.create_job(db_path, "https://www.tiktok.com/music/a-1", 1, "a")
    jb = models.create_job(db_path, "https://www.tiktok.com/music/b-2", 1, "b")
    b_dang_chay, tha_b = threading.Event(), threading.Event()

    def xu_ly(db, _dl, _ck, job):
        if job["id"] == ja:
            raise sqlite3.OperationalError("database is locked")
        b_dang_chay.set()
        tha_b.wait(5)
        models.finish_job(db, job["id"], "done")

    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=xu_ly, disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert b_dang_chay.wait(5)
        assert w.trang_thai()["loi_lien_tiep"] == 0
        tha_b.set()
        assert _cho(lambda: models.get_job(db_path, jb)["trang_thai"] == "done")
    finally:
        tha_b.set()
        w.stop()
    assert models.get_job(db_path, ja)["trang_thai"] == "interrupted"


def test_id_ket_vinh_vien_khong_chan_hang_doi(db_path, tmp_path, monkeypatch):
    """Ghi 'interrupted' cho job A trượt MÃI (trang DB hỏng cục bộ) ⇒ A nằm ở `job_ket`,
    nhưng job B vẫn được nhận và chạy xong. Đột biến đưa vòng thử lại vào trong đường
    nhận job (ném trước claim) ⇒ B không bao giờ chạy ⇒ ĐỎ."""
    ja = models.create_job(db_path, "https://www.tiktok.com/music/a-1", 1, "a")
    jb = models.create_job(db_path, "https://www.tiktok.com/music/b-2", 1, "b")
    that = models.mark_job_interrupted

    def danh_dau(p, jid):
        if jid == ja:
            raise sqlite3.DatabaseError("database disk image is malformed")
        return that(p, jid)

    def xu_ly(db, _dl, _ck, job):
        if job["id"] == ja:
            raise sqlite3.OperationalError("disk I/O error")
        models.finish_job(db, job["id"], "done")

    monkeypatch.setattr(models, "mark_job_interrupted", danh_dau)
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=xu_ly, disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: models.get_job(db_path, jb)["trang_thai"] == "done")
        assert w.trang_thai()["job_ket"] == [ja]
    finally:
        w.stop()


def test_cho_dia_lau_thi_nhac_lai_theo_nhip_khong_moi_vong(db_path, tmp_path, caplog, monkeypatch):
    """Chờ đĩa kéo dài ⇒ nhắc lại theo nhịp `NHAC_CHO_DIA_GIAY` (không im sau dòng đầu),
    nhưng vẫn ít hơn hẳn số vòng. Đột biến bỏ nhắc lại ⇒ chỉ 1 dòng ⇒ ĐỎ."""
    monkeypatch.setattr(queue_mod, "NHAC_CHO_DIA_GIAY", 0.05)
    models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    dem = {"n": 0}

    def dia(_p):
        dem["n"] += 1
        return _Dia(False, f"đĩa còn {300 - dem['n'] % 200} MB")

    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.002, disk_guard_fn=dia)
    with caplog.at_level("WARNING", logger="videodl.web"):
        w.start()
        try:
            time.sleep(0.3)
        finally:
            w.stop()
    cho = [r for r in caplog.records if "CHỜ" in r.getMessage()]
    assert 2 <= len(cho) < dem["n"] / 5, (len(cho), dem["n"])


@pytest.mark.parametrize("loi", [KeyboardInterrupt, SystemExit])
def test_base_exception_trong_process_job_ghi_interrupted_roi_nem_lai(db_path, tmp_path, monkeypatch, loi):
    """Cờ TẮT, job thường: BaseException giữa job ⇒ vẫn ném ra (không nuốt) NHƯNG job đã thành
    'interrupted' — không kẹt 'running' tới lần khởi động sau. Ngoại lệ có chủ đích của "cờ TẮT y
    như main": chỉ trên nhánh BaseException. Đột biến bỏ `except BaseException` ⇒ 'running' ⇒ ĐỎ."""
    monkeypatch.delenv("VIDEODL_PROFILE_CAPTCHA", raising=False)
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    job = models.claim_next_pending_job(db_path)

    def fetch_thoat(*a, **k):
        raise loi("mô phỏng")

    monkeypatch.setattr(queue_mod, "_fetch_refs", fetch_thoat)
    with pytest.raises(loi):
        queue_mod.process_job(db_path, tmp_path / "dl", tmp_path / "ck", job)
    assert models.get_job(db_path, job_id)["trang_thai"] == "interrupted"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_base_exception_tu_process_job_fn_luong_chet_va_job_interrupted(db_path, tmp_path):
    """`process_job_fn` tiêm vào ném SystemExit sau khi đã nhận job ⇒ luồng vẫn chết (`song`
    False, như test ở trên chốt) VÀ job đã 'interrupted'. Đột biến bỏ `except BaseException` ở
    `_loop` ⇒ job kẹt 'running' ⇒ ĐỎ."""
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")

    def thoat(_db, _dl, _ck, _job):
        raise SystemExit("mô phỏng luồng bị giết giữa job")

    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=thoat, disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: w.trang_thai()["song"] is False)
    finally:
        w.stop()
    assert models.get_job(db_path, job_id)["trang_thai"] == "interrupted"



def test_base_exception_process_job_ghi_db_hong_van_nem_loi_goc(db_path, tmp_path, monkeypatch):
    """Lỗi DB khi ghi trạng thái (nhánh BaseException) KHÔNG được đè lỗi gốc: ra ngoài vẫn là
    KeyboardInterrupt. Đột biến bỏ try/except trong `_ghi_khi_base_exception` ⇒ OperationalError ⇒ ĐỎ."""
    monkeypatch.delenv("VIDEODL_PROFILE_CAPTCHA", raising=False)
    models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    job = models.claim_next_pending_job(db_path)

    def fetch_thoat(*a, **k):
        raise KeyboardInterrupt("mô phỏng")

    def ghi_hong(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(queue_mod, "_fetch_refs", fetch_thoat)
    monkeypatch.setattr(models, "mark_job_interrupted", ghi_hong)
    with pytest.raises(KeyboardInterrupt):
        queue_mod.process_job(db_path, tmp_path / "dl", tmp_path / "ck", job)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_base_exception_loop_ghi_db_hong_luong_chet_vi_loi_goc(db_path, tmp_path, monkeypatch):
    """Như trên cho `_loop`: luồng phải chết vì ĐÚNG SystemExit gốc, không vì OperationalError của lần
    ghi trạng thái. Đột biến bỏ try/except trong `_ghi_khi_base_exception` ⇒ ĐỎ."""
    import threading
    models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    loai = []
    monkeypatch.setattr(threading, "excepthook", lambda a: loai.append(a.exc_type))

    def thoat(_db, _dl, _ck, _job):
        raise SystemExit("mô phỏng")

    def ghi_hong(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(models, "mark_job_interrupted", ghi_hong)
    w = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck", poll_interval=0.01,
                  process_job_fn=thoat, disk_guard_fn=lambda _p: _Dia(True))
    w.start()
    try:
        assert _cho(lambda: w.trang_thai()["song"] is False)
    finally:
        w.stop()
    assert loai == [SystemExit], loai
