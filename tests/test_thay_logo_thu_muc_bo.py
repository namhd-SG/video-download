"""Thư mục đầu ra theo bộ + cột `ten_bo`/`thu_muc_ra_id` + cổng cấu hình `Creative` — Drive GIẢ (`drive_gia_thay_logo`), không mạng."""
import logging
import sqlite3
import time
from pathlib import Path

import pytest
from drive_gia_thay_logo import DriveGiaTL

from tiktok_music_downloader.thay_logo import drive_tl, hang_doi, nhat_ky, thu_muc_bo

# Schema CŨ của hàng đợi (origin/main be759b8), trước khi có `ten_bo` / `thu_muc_ra_id`.
SCHEMA_CU = """
CREATE TABLE IF NOT EXISTS tl_job (
  id INTEGER PRIMARY KEY, nguoi_tao TEXT NOT NULL, tao_luc REAL NOT NULL, ghi_chu TEXT);
CREATE TABLE IF NOT EXISTS tl_job_video (
  id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES tl_job(id), nguon TEXT NOT NULL,
  trang_thai TEXT NOT NULL DEFAULT 'cho'
    CHECK (trang_thai IN ('cho', 'cho_agy', 'dang_chay', 'xong', 'cho_nguoi', 'loi')),
  so_lan_thu INTEGER NOT NULL DEFAULT 0, cho_agy_tu REAL, cap_nhat_luc REAL NOT NULL, video_log_id INTEGER,
  duong_dan_goc TEXT, thong_so TEXT, drive_file_id_ra TEXT, loi_text TEXT);
CREATE INDEX IF NOT EXISTS ix_tl_job_video_tt ON tl_job_video(trang_thai, id);
CREATE INDEX IF NOT EXISTS ix_tl_job_nguoi_tao ON tl_job(nguoi_tao);
"""


def _drive(**kw):
    d = DriveGiaTL()
    d.them_thu_muc("GOC", "Thay logo - đầu ra", "VT")  # gốc đầu ra nằm dưới "video-tool"
    d.them_thu_muc("VT", "video-tool")
    for (ten, cha), fid in kw.get("co_san", {}).items():
        d.them_thu_muc(fid, ten, cha)
    return d


def _conn(tmp_path):
    conn = nhat_ky.mo(tmp_path / "l.db")
    hang_doi.khoi_tao(conn)
    return conn


def _job(conn, ten=None):
    return hang_doi.tao_job(conn, "a@x", [{"kieu": "drive", "file_id": "A" * 20}], "", ten)


def test_alter_db_cu_co_hang_chay_hai_lan_cot_co_hang_con(tmp_path):
    p = tmp_path / "cu.db"
    with sqlite3.connect(p) as c:
        c.executescript(SCHEMA_CU)
        c.execute("INSERT INTO tl_job (nguoi_tao, tao_luc, ghi_chu) VALUES ('a@x', 1, 'cũ')")
        c.execute("INSERT INTO tl_job_video (job_id, nguon, cap_nhat_luc) VALUES (1, '{\"file_id\": \"A\"}', 1)")
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    hang_doi.khoi_tao(conn)
    hang_doi.khoi_tao(conn)  # `khoi_tao` chạy mỗi kết nối: lần hai không được lỗi
    assert {"ten_bo", "thu_muc_ra_id"} <= {r[1] for r in conn.execute("PRAGMA table_info(tl_job)")}
    r = conn.execute("SELECT ghi_chu, ten_bo, thu_muc_ra_id FROM tl_job").fetchone()
    assert tuple(r) == ("cũ", None, None)  # hàng cũ còn nguyên, không tên
    assert conn.execute("SELECT count(*) FROM tl_job_video").fetchone()[0] == 1
    assert hang_doi.ten_bo_hien_thi(1, r["ten_bo"]) == "Lượt #1"
    j = hang_doi.tao_job(conn, "a@x", [{"kieu": "drive", "file_id": "A" * 20}], "", "Bộ mới")
    assert conn.execute("SELECT ten_bo FROM tl_job WHERE id=?", (j,)).fetchone()[0] == "Bộ mới"


def test_alter_bat_duplicate_column_khi_tien_trinh_khac_vua_them(tmp_path):
    """Hai tiến trình (web + worker) cùng `khoi_tao`: một bên vừa ALTER xong giữa lúc bên kia kiểm và ALTER ⇒ không được nổ."""
    p = tmp_path / "dua.db"
    with sqlite3.connect(p) as c:
        c.executescript(SCHEMA_CU)

    class Dua(sqlite3.Connection):
        da_chen = False

        def execute(self, sql, *a):
            if sql.startswith("ALTER TABLE tl_job ADD COLUMN ten_bo") and not Dua.da_chen:
                Dua.da_chen = True
                super().execute(sql)  # "tiến trình kia" thêm cột trước
            return super().execute(sql, *a)

    conn = sqlite3.connect(p, factory=Dua)
    hang_doi.khoi_tao(conn)  # ALTER của ta gặp `duplicate column name` ⇒ phải nuốt đúng lỗi đó
    assert Dua.da_chen and {"ten_bo", "thu_muc_ra_id"} <= {r[1] for r in conn.execute("PRAGMA table_info(tl_job)")}


def test_ten_bo_hien_thi():
    assert hang_doi.ten_bo_hien_thi(7, None) == "Lượt #7" and hang_doi.ten_bo_hien_thi(7, "") == "Lượt #7"
    assert hang_doi.ten_bo_hien_thi(7, "X") == "X"


def test_tao_thu_muc_con_dung_ten_luu_id_dung_lai_lan_hai(tmp_path):
    conn, d = _conn(tmp_path), _drive()
    j = _job(conn, "Bộ 09/10")
    assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "NEW1"
    assert d.muc["NEW1"]["name"] == f"Bộ 09/10 (#{j})" and d.muc["NEW1"]["parents"] == ["GOC"]
    assert conn.execute("SELECT thu_muc_ra_id FROM tl_job WHERE id=?", (j,)).fetchone()[0] == "NEW1"
    assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "NEW1"  # video thứ hai: chỉ kiểm lại id đã lưu, không tìm/tạo
    assert d.so_lan("lay_muc") == 1 and d.so_lan("tim_con_theo_ten") == 1 and d.so_lan("tao_thu_muc") == 1


def test_thu_muc_da_co_tren_drive_thi_dung_lai_khong_tao(tmp_path):
    conn = _conn(tmp_path)
    j = _job(conn, "B")
    d = _drive(co_san={(f"B (#{j})", "GOC"): "CO_SAN"})
    assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "CO_SAN" and d.so_lan("tao_thu_muc") == 0


def test_job_cu_khong_ten_va_hai_bo_cung_ten_ra_hai_thu_muc(tmp_path):
    conn, d = _conn(tmp_path), _drive()
    j0, j1, j2 = _job(conn), _job(conn, "Trùng"), _job(conn, "Trùng")
    ids = {thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) for j in (j0, j1, j2)}
    assert len(ids) == 3 and d.muc[thu_muc_bo.tim_hoac_tao(conn, j0, "GOC", d)]["name"] == f"Lượt #{j0} (#{j0})"


def test_drive_loi_thi_nem_len_va_khong_ghi_moc(tmp_path):
    conn, d = _conn(tmp_path), _drive()
    j = _job(conn, "B")
    d.loi[("tao_thu_muc", "*")] = RuntimeError("503")
    with pytest.raises(RuntimeError):
        thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d)
    assert conn.execute("SELECT thu_muc_ra_id FROM tl_job WHERE id=?", (j,)).fetchone()[0] is None  # lượt sau còn thử lại được


def test_ten_thu_muc_bo_ky_tu_dieu_khien():
    assert thu_muc_bo.ten_thu_muc(3, " a\x00b\n ") == "ab (#3)"


def test_thu_muc_cua_bo_trong_worker_tra_thu_muc_bo_va_khong_roi_ve_goc(tmp_path):
    from web import thay_logo_worker as tw
    db = tmp_path / "l.db"
    conn = _conn(tmp_path)
    j = _job(conn, "B")
    conn.close()
    d = _drive()
    assert tw.thu_muc_cua_bo(db, j, "GOC", d) == "NEW1"
    assert tw.thu_muc_cua_bo(db, j, "GOC", d) == "NEW1" and d.so_lan("tao_thu_muc") == 1
    with pytest.raises(LookupError):  # không tra được bộ ⇒ ném (worker đánh `loi`), KHÔNG đổ vào thư mục gốc
        tw.thu_muc_cua_bo(db, 9999, "GOC", d)


def test_thu_muc_bo_da_cache_bi_xoa_thung_rac_hoac_doi_cha_thi_dung_lai(tmp_path, caplog):
    conn, d = _conn(tmp_path), _drive()
    d.them_thu_muc("KHAC", "Chỗ khác")
    j = _job(conn, "B")
    assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "NEW1"
    assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "NEW1"  # còn sống ⇒ giữ
    d.muc["NEW1"]["trashed"] = True  # (a) vào thùng rác
    with caplog.at_level(logging.WARNING):
        assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "NEW2"
    assert "tạo lại" in caplog.text
    d.muc["NEW2"]["parents"] = ["KHAC"]  # (b) bị dời ra khỏi thư mục ra
    assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "NEW3"
    del d.muc["NEW3"]  # (c) xoá hẳn (404)
    assert thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d) == "NEW4"
    assert conn.execute("SELECT thu_muc_ra_id FROM tl_job WHERE id=?", (j,)).fetchone()[0] == "NEW4"


def test_thu_muc_bo_cache_loi_drive_tam_thoi_thi_nem_khong_xoa_id(tmp_path):
    conn, d = _conn(tmp_path), _drive()
    j = _job(conn, "B")
    thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d)
    d.loi[("lay_muc", "NEW1")] = RuntimeError("503")
    with pytest.raises(RuntimeError):
        thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d)
    assert conn.execute("SELECT thu_muc_ra_id FROM tl_job WHERE id=?", (j,)).fetchone()[0] == "NEW1"  # chưa đo được ≠ đã mất


def test_tim_con_theo_ten_nhieu_ket_qua_thi_log_canh_bao(caplog):
    class Svc:
        def files(self): return self
        def list(self, **kw): return self
        def execute(self): return {"files": [{"id": "A"}, {"id": "B"}]}

    class Up:
        def _build_service(self): return Svc()

    with caplog.at_level(logging.WARNING):
        assert len(drive_tl.DriveTLThat(Up()).tim_con_theo_ten("GOC", "x")) == 2
    assert "2 thư mục trùng tên" in caplog.text


# ---------------------------------------------------------------- cổng cấu hình: thư mục ra không được nằm trong cây `Creative`

def test_cong_creative_thu_muc_ra_binh_thuong_duoc_qua():
    d = _drive()
    assert drive_tl.duong_dan_ten(d, "GOC") == ["Thay logo - đầu ra", "video-tool"]
    assert drive_tl.ly_do_creative(d, "GOC") is None


def test_cong_creative_chan_o_bat_ky_cap_nao():
    d = DriveGiaTL()
    d.them_thu_muc("C", "Creative")
    d.them_thu_muc("M", "Mùa hè", "C")
    d.them_thu_muc("RA", "Thay logo - đầu ra", "M")
    for fid in ("C", "M", "RA"):
        assert "Creative" in drive_tl.ly_do_creative(d, fid)
    d.them_thu_muc("c2", "creative ", None)  # khác hoa-thường / dấu cách thừa vẫn bị chặn
    assert drive_tl.ly_do_creative(d, "c2")


def test_cong_creative_khong_do_duoc_thi_nem_len_de_nguoi_goi_phan_biet():
    d = _drive()
    d.loi[("lay_muc", "VT")] = RuntimeError("403")
    with pytest.raises(RuntimeError):
        drive_tl.ly_do_creative(d, "GOC")
    with pytest.raises(drive_tl.DriveTLKhongThay):
        drive_tl.ly_do_creative(DriveGiaTL(), "KHONG_CO")


def test_cong_creative_vong_cha_khong_treo():
    d = DriveGiaTL()
    d.them_thu_muc("A", "a", "B")
    d.them_thu_muc("B", "b", "A")
    with pytest.raises(RuntimeError):
        drive_tl.ly_do_creative(d, "A")


@pytest.fixture
def moi_truong_bat(monkeypatch, tmp_path):
    """`dung_tu_env` với mọi phụ thuộc ngoài được thay: không Drive thật, không ffmpeg/cv thật."""
    from tiktok_music_downloader import gdrive_upload, watermark
    from web import thay_logo_worker as tw

    class Up:
        def is_configured(self):
            return True

    gia = {"d": _drive()}
    monkeypatch.setenv(tw.ENV_BAT, "1")
    monkeypatch.setenv(tw.ENV_THU_MUC_RA, "GOC")
    monkeypatch.setattr(tw, "_cv", lambda: None)
    monkeypatch.setattr(gdrive_upload, "DriveUploader", Up)
    monkeypatch.setattr(watermark, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(drive_tl, "DriveTLThat", lambda up: gia["d"])
    return tw, gia, tmp_path


def test_dung_tu_env_khong_goi_drive_luc_dung(moi_truong_bat):
    tw, gia, tmp = moi_truong_bat
    assert tw.dung_tu_env(tmp, tmp / "jobs.db") is not None
    assert gia["d"].goi == []  # lifespan của app không được chờ Drive


def _chay_het(w, n=1):
    """Chạy đúng như thread worker nhưng đồng bộ: n vòng của `_chay` (không ngủ)."""
    w.nghi = 0
    lan = []
    w.mot_luot = lambda: lan.append(1) or "da_chay"
    for _ in range(n):
        if w._cho_cong():
            w.mot_luot()
    return len(lan)


def test_worker_thu_muc_ra_trong_creative_khong_nhan_viec_va_bao_ly_do(moi_truong_bat, caplog):
    tw, gia, tmp = moi_truong_bat
    gia["d"].them_thu_muc("CR", "Creative")
    gia["d"].muc["VT"]["parents"] = ["CR"]  # video-tool nằm trong Creative ⇒ GOC cũng nằm trong
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    with caplog.at_level(logging.WARNING):
        assert _chay_het(w, 3) == 0  # không chạy `mot_luot` lần nào
    assert w._lan_cuoi.startswith("cong_creative: ") and "Creative" in w._lan_cuoi
    assert w.trang_thai()["luot_cuoi"] == w._lan_cuoi
    n = gia["d"].so_lan("lay_muc")
    _chay_het(w, 3)
    assert gia["d"].so_lan("lay_muc") == n  # cấm thật ⇒ dừng hẳn, không dò lại mỗi nhịp
    assert "Creative" in caplog.text


def test_worker_thu_muc_ra_binh_thuong_qua_cong_va_chay(moi_truong_bat):
    tw, gia, tmp = moi_truong_bat
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    assert _chay_het(w, 3) == 3
    n = gia["d"].so_lan("lay_muc")
    _chay_het(w, 2)
    assert gia["d"].so_lan("lay_muc") == n  # qua rồi thì không kiểm lại


def test_worker_drive_loi_tam_thoi_thi_thu_lai_co_nhip(moi_truong_bat):
    tw, gia, tmp = moi_truong_bat
    gia["d"].loi[("lay_muc", "*")] = ConnectionError("mạng")
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    w.nhip_cong = 0.2
    assert _chay_het(w, 2) == 0
    assert w._lan_cuoi.startswith("cong_creative: chua_kiem_duoc")
    n = gia["d"].so_lan("lay_muc")
    _chay_het(w, 3)
    assert gia["d"].so_lan("lay_muc") == n  # chưa tới nhịp ⇒ chưa gọi lại
    del gia["d"].loi[("lay_muc", "*")]
    time.sleep(0.25)
    assert _chay_het(w, 1) == 1 and w._cong_qua


def test_dung_tu_env_tai_len_vao_thu_muc_cua_bo(moi_truong_bat):
    tw, gia, tmp = moi_truong_bat
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    j = _job(conn, "Bộ tải")
    conn.close()
    assert w.tai_len(Path("/x/thay-logo-5.mp4"), j).startswith("FILE")
    assert gia["d"].da_tai_len == [("thay-logo-5.mp4", "NEW1")] and gia["d"].muc["NEW1"]["name"] == f"Bộ tải (#{j})"
    with pytest.raises(LookupError):
        w.tai_len(Path("/x/thay-logo-5.mp4"), 9999)  # bộ không tồn tại ⇒ ném, không đổ vào thư mục gốc


def test_video_desk_van_boot_va_phuc_vu_khi_drive_treo(monkeypatch, tmp_path):
    """Lifespan THẬT của app với Drive giả TREO ở `lay_muc`: /healthz vẫn 200 trong vài giây; chỉ worker thay logo chưa nhận việc."""
    import socket
    import threading
    import urllib.request

    import uvicorn
    import web.app as app_mod
    from tiktok_music_downloader import gdrive_upload, watermark
    from web import thay_logo_worker as tw

    treo = threading.Event()

    class DriveTreo(DriveGiaTL):
        def lay_muc(self, file_id):
            self.goi.append(("lay_muc", file_id))
            treo.wait(60)  # không bao giờ được set trong lúc test
            raise TimeoutError

    class Up:
        def is_configured(self):
            return True

    cu = {k: getattr(app_mod, k) for k in ("DATA_DIR", "DB_PATH")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp_path, tmp_path / "jobs.db"
    monkeypatch.setenv(tw.ENV_BAT, "1")
    monkeypatch.setenv(tw.ENV_THU_MUC_RA, "GOC")
    monkeypatch.setenv(app_mod.ENV_TAT_LAP_VAO_BO, "1")
    monkeypatch.setattr(tw, "_cv", lambda: None)
    monkeypatch.setattr(gdrive_upload, "DriveUploader", Up)
    monkeypatch.setattr(watermark, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(drive_tl, "DriveTLThat", lambda up: DriveTreo())
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        han = time.time() + 8
        while not server.started and time.time() < han:
            time.sleep(0.05)
        assert server.started, "app KHÔNG boot được khi Drive treo (cổng Creative chặn lifespan)"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            assert r.status == 200
        assert app_mod.worker_thay_logo is not None and app_mod.worker_thay_logo._lan_cuoi != "chua_chay"
    finally:
        app_mod.worker_thay_logo = None
        treo.set()  # nhả thread worker đang treo để tắt máy chủ không chờ trần join
        server.should_exit = True
        t.join(timeout=20)
        app_mod.worker.start, app_mod.worker.stop = start, stop
        for k, v in cu.items():
            setattr(app_mod, k, v)


def test_cong_kiem_ngay_lan_dau_ke_ca_khi_monotonic_nho(moi_truong_bat, monkeypatch):
    tw, gia, tmp = moi_truong_bat
    monkeypatch.setattr(tw.time, "monotonic", lambda: 5.0)  # máy vừa bật: 5 - 0.0 < 60 từng làm bỏ qua lần kiểm đầu
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    assert w._cho_cong() is True and gia["d"].so_lan("lay_muc") >= 1


def test_ly_do_khong_nhan_chi_khi_cam_vinh_vien(moi_truong_bat):
    tw, gia, tmp = moi_truong_bat
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    assert w.ly_do_khong_nhan is None  # chưa kiểm xong
    gia["d"].loi[("lay_muc", "*")] = ConnectionError("mạng")
    w._cho_cong()
    assert w.ly_do_khong_nhan is None  # lỗi tạm ⇒ vẫn nhận
    del gia["d"].loi[("lay_muc", "*")]
    w.nhip_cong = 0
    assert w._cho_cong() and w.ly_do_khong_nhan is None
    w.dat_cam("lý do X")
    assert w.ly_do_khong_nhan == "lý do X" and w._cho_cong() is False


def test_tao_thu_muc_moi_kiem_lai_creative_cam_thi_khong_tao_va_dat_cam(moi_truong_bat):
    tw, gia, tmp = moi_truong_bat
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    assert w._cho_cong()
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    j = _job(conn, "B")
    conn.close()
    gia["d"].them_thu_muc("CR", "Creative")
    gia["d"].muc["VT"]["parents"] = ["CR"]  # SAU khi đã qua cổng: cấu hình bị đổi
    with pytest.raises(thu_muc_bo.CongCreativeCam):
        w.tai_len(Path("/x/a.mp4"), j)
    assert gia["d"].so_lan("tao_thu_muc") == 0 and gia["d"].da_tai_len == []
    assert w.ly_do_khong_nhan and "Creative" in w.ly_do_khong_nhan and w._cho_cong() is False


def test_tao_thu_muc_moi_kiem_lai_loi_tam_thi_thi_khong_upload_va_khong_go_co_qua(moi_truong_bat):
    tw, gia, tmp = moi_truong_bat
    w = tw.dung_tu_env(tmp, tmp / "jobs.db")
    assert w._cho_cong()
    conn = nhat_ky.mo(tmp / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    j = _job(conn, "B")
    conn.close()
    gia["d"].loi[("lay_muc", "*")] = ConnectionError("mạng")
    with pytest.raises(ConnectionError):
        w.tai_len(Path("/x/a.mp4"), j)
    assert gia["d"].so_lan("tao_thu_muc") == 0 and gia["d"].da_tai_len == [] and w._cong_qua and w.ly_do_khong_nhan is None


def test_thu_muc_bo_cu_da_cache_khong_kiem_lai_creative(tmp_path):
    conn, d = _conn(tmp_path), _drive()
    j = _job(conn, "B")
    thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d)
    thu_muc_bo.tim_hoac_tao(conn, j, "GOC", d, lambda: "phải không được gọi")  # chỉ kiểm khi sắp TẠO mới
