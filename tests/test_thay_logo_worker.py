"""Worker thay logo (ĐP-1508): nhường lane tải, cổng đĩa, đi trọn 2 pha qua TIẾN TRÌNH CON thật, quét khởi động, tắt có trần."""
import json
import os
import shutil
import sqlite3
import sys
import time

import pytest

cv2 = pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

from thay_logo_tong_hop import tao_clip  # noqa: E402

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky, relay_may_dev  # noqa: E402
from tiktok_music_downloader.watermark import find_ffmpeg  # noqa: E402
from web import thay_logo_worker as tw  # noqa: E402

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="không tìm thấy ffmpeg")


@pytest.fixture(scope="module")
def clip_file(tmp_path_factory):
    d = tmp_path_factory.mktemp("w")
    clip = tao_clip(n=40)
    p = d / "goc.mp4"
    out = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (360, 640))
    for i in range(40):
        out.write(cv2.cvtColor(clip.nguon.doc(i), cv2.COLOR_GRAY2BGR))
    out.release()
    return clip, p


def _jobs_db(tmp_path, running: int):
    p = tmp_path / "jobs.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, trang_thai TEXT)")
        c.execute("DELETE FROM jobs")
        c.executemany("INSERT INTO jobs (trang_thai) VALUES (?)", [("running",)] * running + [("done",)])
    return p


@pytest.fixture
def worker(tmp_path, clip_file, monkeypatch):
    _, goc = clip_file
    da_len = []

    def tai_ve(nguon, d):
        p = d / "goc.mp4"
        shutil.copy(goc, p)
        return p

    def tai_len(p):
        da_len.append(p.read_bytes()[:4])
        return "drive-ra-1"
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(sys.path))
    w = tw.ThayLogoWorker(tmp_path / "log.db", _jobs_db(tmp_path, 0), tmp_path / "data", tai_ve=tai_ve, tai_len=tai_len,
                          ffmpeg=FFMPEG, nghi_giay=0.05)
    w.da_len = da_len
    return w


def _agy_tu_ground_truth(clip, hop, job_vid):
    bang = json.loads((hop.goc / str(job_vid) / "khung.json").read_text())

    def agy(anh):
        items = []
        for p in anh:
            x, y, w, h = clip.hop_that[bang[p.stem]["khung"]]
            items.append({"file": str(p), "endcard": False, "watermarks": [
                {"label": "x", "box_2d": [y * 1000 // 640, x * 1000 // 360, (y + h) * 1000 // 640, (x + w) * 1000 // 360]}]})
        return {"items": items}
    return agy


class _Mini:
    def __init__(self, hop):
        self.hop = hop

    def viec(self):
        return self.hop.viec_cho()

    def anh(self, u):
        return self.hop.doc_anh(u)

    def nop(self, j, kq):
        self.hop.nop_ket_qua(j, kq)


def _trang_thai(w, vid):
    conn = w._mo()
    try:
        return dict(conn.execute("SELECT * FROM tl_job_video WHERE id=?", (vid,)).fetchone())
    finally:
        conn.close()


def _tao(w):
    conn = w._mo()
    try:
        j = hang_doi.tao_job(conn, "a@x", [{"kieu": "drive", "file_id": "F1"}])
        return conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (j,)).fetchone()[0]
    finally:
        conn.close()


def test_di_tron_hai_pha_qua_tien_trinh_con(worker, clip_file):
    clip, _ = clip_file
    vid = _tao(worker)
    assert worker.mot_luot() == "ranh"  # pha 1 xong, chưa có toạ độ
    r = _trang_thai(worker, vid)
    assert r["trang_thai"] == "cho_agy" and r["cho_agy_tu"] is not None
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))
    assert worker.mot_luot() == "da_xu_ly"
    r = _trang_thai(worker, vid)
    assert (r["trang_thai"], r["drive_file_id_ra"]) == ("xong", "drive-ra-1") and worker.da_len
    conn = nhat_ky.mo(worker.log_db)
    v = conn.execute("SELECT trang_thai, drive_file_id_ra FROM tl_video WHERE id=?", (r["video_log_id"],)).fetchone()
    assert tuple(v) == ("render", "drive-ra-1")
    assert not (worker.data / "thay_logo_scratch" / str(vid)).exists()  # scratch dọn sau trạng thái cuối


def test_nhuong_lane_tai_khi_co_job_running(worker, tmp_path, clip_file):
    clip, _ = clip_file
    vid = _tao(worker)
    worker.mot_luot()
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))
    _jobs_db(tmp_path, running=1)
    assert worker.mot_luot() == "nhuong_lane_tai"
    assert _trang_thai(worker, vid)["trang_thai"] == "cho_agy"  # pha nặng không chạy
    _jobs_db(tmp_path, running=0)
    assert worker.mot_luot() == "da_xu_ly"


def test_jobs_db_khong_doc_duoc_thi_nhuong(tmp_path):
    assert tw.co_job_tai_dang_chay(tmp_path / "khong-co.db") is True


def test_cong_dia_khong_nhat_viec(worker, monkeypatch):
    vid = _tao(worker)
    monkeypatch.setattr(worker, "dia_trong_gb", lambda: 4.9)
    assert worker.mot_luot() == "cho_dia"
    assert _trang_thai(worker, vid)["trang_thai"] == "cho"


def test_quet_khoi_dong_lam_lai_roi_het_luot(worker):
    vid = _tao(worker)
    conn = worker._mo()
    hang_doi.dat(conn, vid, "dang_chay")
    assert hang_doi.quet_khoi_dong(conn) == {"lam_lai": 1, "het_luot": 0}
    assert _trang_thai(worker, vid)["trang_thai"] == "cho_agy"
    for _ in range(2):
        hang_doi.dat(conn, vid, "dang_chay", so_lan_thu=_trang_thai(worker, vid)["so_lan_thu"])
        hang_doi.quet_khoi_dong(conn)
    conn.close()
    assert _trang_thai(worker, vid)["trang_thai"] == "loi"


def test_tat_co_tran_ke_ca_khi_tien_trinh_con_treo(worker):
    import subprocess
    worker.start()
    con = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    worker._con = con
    t = time.time()
    worker.stop(timeout=5)
    assert time.time() - t < 12
    assert con.poll() is not None  # tiến trình con đã chết, không mồ côi
    assert not worker._thread.is_alive()
