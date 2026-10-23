"""Worker thay logo (ĐP-1508): nhường lane tải, cổng đĩa, đi trọn 2 pha qua TIẾN TRÌNH CON thật, quét khởi động, tắt có trần."""
import json
import os
import shutil
import sqlite3
import sys
import threading
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

    def tai_len(p, job_id):
        da_len.append(p.read_bytes()[:4])
        return "drive-ra-1"
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(sys.path))
    w = tw.ThayLogoWorker(tmp_path / "log.db", _jobs_db(tmp_path, 0), tmp_path / "data", tai_ve=tai_ve, tai_len=tai_len,
                          ffmpeg=FFMPEG, nghi_giay=0.05)
    w.da_len = da_len
    monkeypatch.setattr(w, "ram_du", lambda: True)  # cổng RAM có test riêng; máy chạy test không phải mini
    return w


def _agy_tu_ground_truth(clip, hop, *job_vids):
    bang = {}
    for v in job_vids:  # relay gộp nhiều job vào một lô agy ⇒ cần bảng khung của mọi job trong lô
        bang.update(json.loads((hop.goc / str(v) / "khung.json").read_text()))

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

    def nop(self, j, kq, luot=1):
        self.hop.nop_ket_qua(j, kq, luot)

    def nop_loi(self, j, ma, luot=1):
        self.hop.nop_loi(j, ma, luot)


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
    assert not (worker.hop.goc / str(vid)).exists()  # hộp thư cũng dọn
    giu = worker.data / "thay_logo_video" / str(r["video_log_id"])  # video gốc + bản ra GIỮ lại cho người khoanh, ngoài scratch
    assert (giu / "goc.mp4").stat().st_size > 0 and (giu / "ra.mp4").stat().st_size > 0
    assert not (worker.data / "thay_logo" / str(r["video_log_id"]) / "goc.mp4").exists()  # không chung thư mục có trần dọn


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


def test_thieu_ram_thi_khong_chay_pha_nang(worker, clip_file, monkeypatch):
    clip, _ = clip_file
    vid = _tao(worker)
    worker.mot_luot()
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))
    monkeypatch.setattr(worker, "ram_du", lambda: False)
    assert worker.mot_luot() == "cho_ram" and _trang_thai(worker, vid)["trang_thai"] == "cho_agy"


@pytest.mark.parametrize("mp,sw,ky_vong", [
    ("System-wide memory free percentage: 63%", "total = 5120.00M  used = 3516.75M  free = 1603.25M", True),
    ("System-wide memory free percentage: 29%", "total = 5120.00M  used = 3516.75M  free = 1603.25M", False),
    ("System-wide memory free percentage: 63%", "total = 5120.00M  used = 4200.00M  free = 920.00M", True),   # RAM rộng ⇒ miễn swap
    ("System-wide memory free percentage: 60%", "total = 5120.00M  used = 4200.00M  free = 920.00M", True),   # mép miễn
    ("System-wide memory free percentage: 59%", "total = 5120.00M  used = 4200.00M  free = 920.00M", False),  # dưới mép: swap vẫn chặn
    ("System-wide memory free percentage: 45%", "total = 5120.00M  used = 4096.00M  free = 1024.00M", True),  # mép swap 1 GiB
    ("System-wide memory free percentage: 30%", "total = 0.00M  used = 0.00M  free = 0.00M", True),           # chưa cấp swap
    ("System-wide memory free percentage: 29%", "total = 0.00M  used = 0.00M  free = 0.00M", False),          # vế RAM không miễn
    ("System-wide memory free percentage: 74%", "total = 2048.00M  used = 648.12M  free = 1399.88M", True),   # số đo ca-n 19/10
    ("System-wide memory free percentage: 63%", "free = 2000.00M", False),                                     # thiếu total ⇒ không đo được
    ("rác không đọc được", "free = 2000.00M", False),
])
def test_cong_ram_doc_dung_so_mini(monkeypatch, mp, sw, ky_vong):
    import subprocess
    out = {"memory_pressure": mp, "sysctl": sw}
    monkeypatch.setattr(tw.subprocess, "run", lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, out[cmd[0]], ""))
    assert tw.ram_du() is ky_vong


def test_tat_co_tran_ke_ca_khi_tien_trinh_con_LO_SIGTERM_va_co_chau(worker, tmp_path):
    """Tiến trình con bỏ qua SIGTERM và sinh một tiến trình cháu (như ffmpeg): stop() phải giết CẢ NHÓM, có trần thời gian."""
    import subprocess
    worker.start()
    pid_chau = tmp_path / "chau.pid"
    ma = ("import signal, subprocess, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
          f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); open({str(pid_chau)!r}, 'w').write(str(c.pid)); "
          "time.sleep(60)")
    con = subprocess.Popen([sys.executable, "-c", ma], start_new_session=True)
    for _ in range(50):
        if pid_chau.exists() and pid_chau.read_text():
            break
        time.sleep(0.05)
    worker._con = con
    t = time.time()
    worker.stop(timeout=5)
    assert time.time() - t < 12
    assert con.poll() is not None  # tiến trình con đã chết dù lờ SIGTERM
    chau = int(pid_chau.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(chau, 0)  # cháu cũng chết, không mồ côi
    assert not worker._thread.is_alive()


# ---------------------------------------------------------------- các ca code-reviewer 09/10

def test_video_hong_khong_sap_tien_trinh_chinh_chi_dong_do_loi(worker, monkeypatch):
    """Giải mã video chạy trong TIẾN TRÌNH CON: file rác ⇒ dòng đó `loi` với chữ ngắn, worker vẫn sống."""
    def tai_rac(nguon, d):
        p = d / "goc.mp4"
        p.write_bytes(b"\x00" * 4096)
        return p
    monkeypatch.setattr(worker, "tai_ve", tai_rac)
    vid = _tao(worker)
    worker.mot_luot()
    r = _trang_thai(worker, vid)
    assert r["trang_thai"] == "loi" and "Traceback" not in r["loi_text"] and "/" not in r["loi_text"]
    assert not (worker.data / "thay_logo_scratch" / str(vid)).exists()


def test_mot_dong_hong_khong_chan_ca_hang_doi_pha_2(worker, clip_file):
    clip, _ = clip_file
    v1, v2 = _tao(worker), _tao(worker)
    worker.mot_luot()
    worker.mot_luot()
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, v1, v2))
    os.unlink(_trang_thai(worker, v1)["duong_dan_goc"])  # file gốc của dòng đầu biến mất
    assert worker.mot_luot() == "da_xu_ly"
    assert _trang_thai(worker, v1)["trang_thai"] == "loi"
    assert _trang_thai(worker, v1)["loi_text"] == "Máy không xử lý tiếp được video này."
    assert _trang_thai(worker, v2)["trang_thai"] == "xong"


def test_relay_tat_thi_khong_tai_truoc_qua_tran_cho_agy(worker, monkeypatch):
    monkeypatch.setattr(tw, "TRAN_CHO_AGY", 2)
    ids = [_tao(worker) for _ in range(4)]
    for _ in range(4):
        worker.mot_luot()
    tt = [_trang_thai(worker, v)["trang_thai"] for v in ids]
    assert tt.count("cho_agy") == 2 and tt.count("cho") == 2


@pytest.mark.parametrize("trang_thai", ["running", "dang_mo", "dang_giai"])
def test_nhuong_moi_trang_thai_ban_cua_lane_tai(tmp_path, trang_thai):
    p = tmp_path / "jobs.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, trang_thai TEXT)")
        c.execute("INSERT INTO jobs (trang_thai) VALUES (?)", (trang_thai,))
    assert tw.co_job_tai_dang_chay(p) is True


# ---------------------------------------------------------------- lời lỗi member đọc: câu thường, không tên exception / thuật ngữ kỹ sư

_MAU_KY_SU = __import__("re").compile(r"agy|khung|box|Error|Exception|\d+s\b", __import__("re").I)


def _loi_text(w, vid):
    ct = _trang_thai(w, vid)
    assert ct["trang_thai"] == "loi"
    assert not _MAU_KY_SU.search(ct["loi_text"]), ct["loi_text"]
    return ct["loi_text"]


def test_loi_tai_nguon_noi_cau_thuong_ten_exception_chi_o_log(worker, monkeypatch, caplog):
    class HttpError(Exception):
        pass

    def hong(nguon, d):
        raise HttpError("403 forbidden")
    monkeypatch.setattr(worker, "tai_ve", hong)
    vid = _tao(worker)
    with caplog.at_level("WARNING"):
        worker.mot_luot()
    assert _loi_text(worker, vid) == "Không tải được video nguồn từ Drive."
    assert "HttpError" in caplog.text and "403 forbidden" in caplog.text  # chi tiết kỹ sư vẫn ở log máy chủ


def test_loi_khong_doc_duoc_hinh_noi_cau_thuong(worker, monkeypatch):
    import subprocess as sp
    thuc = sp.run
    monkeypatch.setattr(tw.subprocess, "run", lambda cmd, **kw: sp.CompletedProcess(cmd, 0, stdout='{"n": 0}\n', stderr=""))
    vid = _tao(worker)
    worker.mot_luot()
    monkeypatch.setattr(tw.subprocess, "run", thuc)
    assert _loi_text(worker, vid) == "Không đọc được hình trong video."


def test_loi_qua_tran_thoi_gian_noi_cau_thuong(worker, clip_file, monkeypatch):
    clip, _ = clip_file
    vid = _tao(worker)
    worker.mot_luot()
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))
    monkeypatch.setattr(tw, "TRAN_GIAY_MIN", 0.01)
    monkeypatch.setattr(tw, "HE_SO_TRAN_GIAY", 0.0)
    worker.mot_luot()
    assert _loi_text(worker, vid) == "Xử lý quá lâu nên đã dừng."


def test_loi_tai_len_drive_noi_cau_thuong(worker, clip_file, monkeypatch, caplog):
    clip, _ = clip_file

    class HttpError(Exception):
        pass

    def hong(p, job_id):
        raise HttpError("quota")
    monkeypatch.setattr(worker, "tai_len", hong)
    vid = _tao(worker)
    worker.mot_luot()
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))
    with caplog.at_level("WARNING"):
        worker.mot_luot()
    assert _loi_text(worker, vid) == "Không tải được bản đã thay lên Drive."
    assert "HttpError" in caplog.text


# ---------------------------------------------------------------- nguồn "Đã vào bộ": md5 file tải phải khớp ảnh chụp lúc tạo lượt
def _tao_vao_bo(w, md5):
    conn = w._mo()
    try:
        j = hang_doi.tao_job(conn, "a@x", [{"kieu": "vao_bo", "video_id": "V1", "file_id": "BAN1", "folder_id": "F1", "ma_bo": "N.1",
                                           "md5": md5, "size": "1", "ten": "v.mp4"}])
        return conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (j,)).fetchone()[0]
    finally:
        conn.close()


def test_vao_bo_md5_lech_thi_loi_cau_thuong_khong_xu_ly(worker, clip_file):
    import hashlib
    _, goc = clip_file
    vid = _tao_vao_bo(worker, "0" * 32)  # ảnh chụp nói md5 khác file thật
    worker.mot_luot()
    r = _trang_thai(worker, vid)
    assert (r["trang_thai"], r["loi_text"]) == ("loi", tw.NGUON_DA_DOI_CAU) and r["duong_dan_goc"] is None
    assert not (worker.hop.goc / str(vid)).exists()  # chưa đặt việc cho agy: không xử lý
    # đối chứng cùng điều kiện: md5 ĐÚNG ⇒ đi tiếp sang chờ agy
    vid2 = _tao_vao_bo(worker, hashlib.md5(goc.read_bytes()).hexdigest())
    worker.mot_luot()
    assert _trang_thai(worker, vid2)["trang_thai"] == "cho_agy"


def test_nguon_vao_bo_thieu_md5_cung_bi_chan(worker):
    vid = _tao_vao_bo(worker, "")
    worker.mot_luot()
    assert _trang_thai(worker, vid)["trang_thai"] == "loi"


# ---------------------------------------------------------------- nguồn "Tải từ máy": thread `tl-don-phien` (riêng, không phụ thuộc cờ, không nằm trong `mot_luot`)
RA_DON = "RAFOLDER0000000000001"
VAO_DON = "VAOFOLDER000000000001"


def _phien_bo_do_cu(w):
    """Một phiên `mo` đã quá 24 h, KHÔNG có file trên Drive."""
    from tiktok_music_downloader.thay_logo import tai_len_phien

    conn = w._mo()
    try:
        tai_len_phien.khoi_tao(conn)
        t = time.time() - 25 * 3600
        conn.execute("INSERT INTO tl_phien_tai (token, email, ten, size, mime, thu_muc_id, tao_luc, cap_nhat_luc) VALUES (?,?,?,?,?,?,?,?)",
                     ("T" * 43, "a@x", "c.mp4", 10, "video/mp4", VAO_DON, t, t))
        conn.commit()
    finally:
        conn.close()


def _trang_thai_phien(w):
    conn = w._mo()
    try:
        return conn.execute("SELECT trang_thai FROM tl_phien_tai").fetchone()[0]
    finally:
        conn.close()


def _cho_phien(w, mong, giay=8.0):
    han = time.time() + giay
    while time.time() < han and _trang_thai_phien(w) != mong:
        time.sleep(0.05)
    return _trang_thai_phien(w)


@pytest.fixture
def worker_don(worker, monkeypatch):
    from drive_gia_thay_logo import DriveGiaTL
    drive = DriveGiaTL()
    drive.them_thu_muc(VAO_DON, "a@x")
    worker.drive_tl = drive
    monkeypatch.setattr(tw, "CHU_KY_DON_PHIEN_GIAY", 0.05)
    monkeypatch.delenv("TL_TAI_TU_MAY", raising=False)  # cờ TẮT: dọn vẫn phải chạy (tắt cờ để lui không được làm kẹt file)
    _phien_bo_do_cu(worker)
    yield worker
    worker.stop()


def test_don_phien_chay_thread_rieng_khi_cong_tai_tu_may_tat(worker_don):
    """Đột biến: gắn tác vụ dọn vào cờ `TL_TAI_TU_MAY` ⇒ tắt cờ thì phiên đọng `mo` ⇒ ĐỎ."""
    worker_don.start()
    assert _cho_phien(worker_don, "bo_do") == "bo_do"
    assert any(t.name == "tl-don-phien" and t.daemon for t in threading.enumerate())


def test_don_phien_van_chay_khi_het_dia(worker_don, monkeypatch):
    """Đột biến: GẮN DỌN VÀO `mot_luot` ⇒ `cho_dia` thoát sớm, dọn tắt âm thầm ⇒ ĐỎ."""
    monkeypatch.setattr(worker_don, "dia_trong_gb", lambda: 4.9)
    worker_don.start()
    assert _cho_phien(worker_don, "bo_do") == "bo_do"
    assert worker_don._lan_cuoi == "cho_dia"  # worker chính vẫn đang ở cổng đĩa suốt thời gian đó


def test_don_phien_van_chay_khi_nhuong_lane_tai(worker_don, tmp_path):
    """Đột biến: gắn dọn vào `mot_luot` ⇒ `nhuong_lane_tai` thoát sớm ⇒ ĐỎ."""
    _jobs_db(tmp_path, running=1)
    worker_don.start()
    assert _cho_phien(worker_don, "bo_do") == "bo_do"
    assert worker_don._lan_cuoi == "nhuong_lane_tai"


def test_don_phien_van_chay_khi_cong_creative_chua_qua(worker_don):
    """`_chay` không gọi `mot_luot` khi cổng Creative chưa qua — dọn vẫn phải chạy."""
    worker_don._cong, worker_don._cong_qua = (lambda: (_ for _ in ()).throw(RuntimeError("Drive chậm"))), False
    worker_don.start()
    assert _cho_phien(worker_don, "bo_do") == "bo_do"
    assert worker_don._lan_cuoi.startswith("cong_creative")


def test_don_phien_loi_mot_luot_khong_giet_thread(worker_don, monkeypatch):
    from tiktok_music_downloader.thay_logo import tai_len_phien
    that, goi = tai_len_phien.don_mot_luot, []

    def hong_roi_chay(conn, drive, *a, **k):
        goi.append(1)
        if len(goi) == 1:
            raise RuntimeError("lỗi tạm")
        return that(conn, drive, *a, **k)
    monkeypatch.setattr(tai_len_phien, "don_mot_luot", hong_roi_chay)
    worker_don.start()
    assert _cho_phien(worker_don, "bo_do") == "bo_do" and len(goi) >= 2


def test_khong_co_drive_thi_khong_dung_thread_don_phien(worker):
    worker.start()
    try:
        assert worker._thread_don_phien is None
    finally:
        worker.stop()


def test_tat_worker_dung_ca_thread_don_phien(worker_don):
    worker_don.start()
    t = worker_don._thread_don_phien
    assert t is not None and t.is_alive()
    worker_don.stop()
    t.join(timeout=3)
    assert not t.is_alive()


# ---------------------------------------------------------------- agy trượt / relay chết: không kẹt `cho_agy` vô hạn

def _den_cho_agy(w):
    vid = _tao(w)
    w.mot_luot()  # pha 1 ⇒ cho_agy
    assert _trang_thai(w, vid)["trang_thai"] == "cho_agy"
    return vid


def _lui_loi_dau(w, vid, giay):
    """Giả lập lỗi ĐẦU TIÊN đã xảy ra cách đây `giay` giây (hộp thư ghi giờ thật nên phải lùi tay)."""
    p = w.hop.thu_muc_luot(vid) / "loi_agy.json"
    d = json.loads(p.read_text())
    d["dau_luc"] = time.time() - giay
    p.write_text(json.dumps(d))


def test_loi_tam_thoi_3_lan_trong_1_phut_chua_ra_loi_du_thoi_gian_moi_ra_loi(worker):
    vid = _den_cho_agy(worker)
    for _ in range(tw.TRAN_LOI_AGY + 2):  # nhiều hơn 3 lần, nhưng dồn trong vài giây (relay nghỉ ~20 s/vòng)
        worker.hop.nop_loi(vid, "het_gio")
    worker.mot_luot()
    assert _trang_thai(worker, vid)["trang_thai"] == "cho_agy"  # lỗi tạm: video chờ rồi tự lành như trên main
    _lui_loi_dau(worker, vid, tw.GIAN_CACH_LOI_AGY_GIAY - 60)
    worker.mot_luot()
    assert _trang_thai(worker, vid)["trang_thai"] == "cho_agy"  # chưa đủ khoảng cách
    _lui_loi_dau(worker, vid, tw.GIAN_CACH_LOI_AGY_GIAY + 1)
    worker.mot_luot()
    r = _trang_thai(worker, vid)
    assert (r["trang_thai"], r["loi_text"]) == ("loi", tw.LY_DO_LOI_AGY["het_gio"])
    assert not (worker.hop.goc / str(vid)).exists()  # hộp thư dọn như mọi trạng thái cuối


def test_du_thoi_gian_ma_chua_du_so_lan_thi_chua_ra_loi(worker):
    vid = _den_cho_agy(worker)
    for _ in range(tw.TRAN_LOI_AGY - 1):
        worker.hop.nop_loi(vid, "het_gio")
    _lui_loi_dau(worker, vid, tw.GIAN_CACH_LOI_AGY_GIAY * 4)
    worker.mot_luot()
    assert _trang_thai(worker, vid)["trang_thai"] == "cho_agy"


def test_model_khong_nhan_ra_loi_ngay_lan_dau(worker):
    vid = _den_cho_agy(worker)
    worker.hop.nop_loi(vid, "model_khong_nhan")
    worker.mot_luot()
    r = _trang_thai(worker, vid)
    assert (r["trang_thai"], r["loi_text"]) == ("loi", tw.LY_DO_LOI_AGY["model_khong_nhan"])


def test_ma_loi_la_ngoai_bang_ly_do_thi_dung_cau_chung(worker):
    vid = _den_cho_agy(worker)
    for _ in range(tw.TRAN_LOI_AGY):
        worker.hop.nop_loi(vid, "thieu_anh")
    _lui_loi_dau(worker, vid, tw.GIAN_CACH_LOI_AGY_GIAY + 1)
    worker.mot_luot()
    assert _trang_thai(worker, vid)["trang_thai"] == "loi" and _trang_thai(worker, vid)["loi_text"] == tw.LY_DO_LOI_AGY_CHUNG


def test_ket_qua_den_sat_luc_chot_loi_thi_ket_qua_thang(worker, clip_file, monkeypatch):
    """Race: lúc quét chưa có kết quả, ngay trước `_ket_thuc` relay nộp xong ⇒ KHÔNG được ra `loi`."""
    clip, _ = clip_file
    vid = _den_cho_agy(worker)
    worker.hop.nop_loi(vid, "model_khong_nhan")
    that, so_lan = worker.hop.doc_ket_qua, []

    def doc(job_id, luot=1):
        so_lan.append(1)
        if len(so_lan) == 2:  # lần đọc lại ngay trước chốt: kết quả vừa tới
            relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid), le={})
        return that(job_id, luot)
    monkeypatch.setattr(worker.hop, "doc_ket_qua", doc)
    worker.mot_luot()
    assert _trang_thai(worker, vid)["trang_thai"] != "loi"


def test_video_dung_cho_agy_qua_han_ra_loi_relay_khong_phan_hoi_khac_ly_do_loi_agy(worker):
    vid = _den_cho_agy(worker)
    conn = worker._mo()
    hang_doi.dat(conn, vid, "cho_agy", cho_agy_tu=time.time() - tw.HAN_CHO_AGY_GIAY + 60)
    conn.close()
    worker.mot_luot()
    assert _trang_thai(worker, vid)["trang_thai"] == "cho_agy"  # chưa tới hạn
    conn = worker._mo()
    hang_doi.dat(conn, vid, "cho_agy", cho_agy_tu=time.time() - tw.HAN_CHO_AGY_GIAY - 60)
    conn.close()
    worker.mot_luot()
    r = _trang_thai(worker, vid)
    assert (r["trang_thai"], r["loi_text"]) == ("loi", tw.LY_DO_HET_HAN_AGY)
    assert tw.LY_DO_HET_HAN_AGY not in tw.LY_DO_LOI_AGY.values() and tw.LY_DO_HET_HAN_AGY != tw.LY_DO_LOI_AGY_CHUNG


def test_co_ket_qua_thi_thang_loi_va_qua_han(worker, clip_file):
    clip, _ = clip_file
    vid = _den_cho_agy(worker)
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))
    conn = worker._mo()
    hang_doi.dat(conn, vid, "cho_agy", cho_agy_tu=time.time() - tw.HAN_CHO_AGY_GIAY - 60)
    conn.close()
    assert worker.mot_luot() == "da_xu_ly"
    assert _trang_thai(worker, vid)["trang_thai"] == "xong"


def test_giu_video_loi_os_van_xong_job(worker, clip_file, monkeypatch):
    """Giữ video cho người khoanh là phụ: lỗi đĩa ở bước đó không được làm hỏng job đã tải bản ra lên Drive."""
    clip, _ = clip_file
    vid = _tao(worker)
    worker.mot_luot()
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))

    def hong(*a, **k):
        raise OSError("đĩa đầy")
    monkeypatch.setattr(tw.khoanh, "giu_video", hong)
    assert worker.mot_luot() == "da_xu_ly"
    assert _trang_thai(worker, vid)["trang_thai"] == "xong"


def test_chet_giua_giu_video_va_ket_thuc_khoi_dong_lai_van_chay_tiep(worker, clip_file, monkeypatch):
    """Video gốc đã dời sang thư mục giữ mà tiến trình chết trước `_ket_thuc` ⇒ khởi động lại, pha 2 lấy lại gốc từ thư mục giữ."""
    clip, _ = clip_file
    vid = _tao(worker)
    worker.mot_luot()
    relay_may_dev.mot_vong(_Mini(worker.hop), _agy_tu_ground_truth(clip, worker.hop, vid))
    that = worker._ket_thuc

    def chet(conn, v, trang_thai, **k):
        if trang_thai == "xong":
            raise RuntimeError("tiến trình chết")
        return that(conn, v, trang_thai, **k)
    monkeypatch.setattr(worker, "_ket_thuc", chet)
    with pytest.raises(RuntimeError):
        worker.mot_luot()
    monkeypatch.setattr(worker, "_ket_thuc", that)
    conn = worker._mo()
    try:
        hang_doi.quet_khoi_dong(conn)  # máy chủ khởi động lại: dang_chay ⇒ làm lại
    finally:
        conn.close()
    assert worker.mot_luot() == "da_xu_ly"
    assert _trang_thai(worker, vid)["trang_thai"] == "xong"
