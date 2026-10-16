"""Tự trả video Đạt về bộ gốc (`thay_logo/tu_ap_vao_bo.py`): đủ bốn điều kiện mới áp; Hoàn tác có hiệu lực (không tự áp lại); lỗi tạm thử
lại vòng sau, lỗi cố định báo một lần. Sân Drive GIẢ + DB file thật dùng lại `San` của test áp vào bộ."""
import time

from test_thay_logo_ap_vao_bo import F1, A, San, _chu

from tiktok_music_downloader.thay_logo import ap_vao_bo, hang_doi, nhat_ky, tu_ap_vao_bo

CHO = tu_ap_vao_bo.CHO_GIAY


def _thu(san, bay_gio, chu_cua=_chu, bo_qua=None, khoi_chay=None):
    goi = []
    conn = san.mo()
    try:
        kq = tu_ap_vao_bo.thu_tu_ap(conn, chu_cua, khoi_chay or goi.append, set() if bo_qua is None else bo_qua, bay_gio=bay_gio)
    finally:
        conn.close()
    return kq, goi


def _sau(giay):
    return time.time() + giay


def test_du_dieu_kien_va_qua_5_phut_thi_tu_ap_that(tmp_path):
    san = San(tmp_path)
    kq, goi = _thu(san, _sau(CHO + 5))
    assert kq == goi == [san.job]
    san.chay()
    assert len(san.ban_moi_trong_bo()) == 2 and san.vi_pham == []


def test_chua_qua_5_phut_sau_lan_cham_cuoi_thi_chua_ap(tmp_path):
    """ĐỘT BIẾN: bỏ điều kiện cửa sổ chờ ⇒ áp ngay ⇒ ĐỎ."""
    san = San(tmp_path)
    kq, goi = _thu(san, _sau(CHO - 30))
    assert kq == goi == [] and san.hang() == []


def test_da_hoan_tac_thi_khong_tu_ap_lai(tmp_path):
    """Chốt L1: lượt đã có dòng `tl_ap_bo` (áp rồi Hoàn tác) ⇒ máy KHÔNG tự áp lại; chỉ nút tay. ĐỘT BIẾN: bỏ `NOT EXISTS tl_ap_bo` ⇒ ĐỎ."""
    san = San(tmp_path)
    san.ap(); san.chay(); san.hoan_tac(); san.chay()
    conn = san.mo()
    try:
        assert ap_vao_bo.trang_thai(conn, san.job)["trang_thai"] == "chua_ap"  # đúng trạng thái agy chỉ ra
    finally:
        conn.close()
    kq, goi = _thu(san, _sau(CHO * 10))
    assert kq == goi == []


def test_con_video_chua_cham_thi_chua_ap(tmp_path):
    san = San(tmp_path)
    conn = san.mo()
    try:  # video 2: xong nhưng CHƯA chấm (bản ghi nhật ký mới, không có đánh giá)
        log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
        hang_doi.dat(conn, san.vids[1], "xong", video_log_id=log_id)
    finally:
        conn.close()
    assert _thu(san, _sau(CHO * 10)) == ([], [])


def test_con_video_dang_cho_may_thi_chua_ap(tmp_path):
    san = San(tmp_path)
    conn = san.mo()
    try:
        hang_doi.dat(conn, san.vids[1], "cho_agy", cho_agy_tu=time.time())
    finally:
        conn.close()
    assert _thu(san, _sau(CHO * 10)) == ([], [])


def test_video_cuoi_ket_thuc_loi_muon_tinh_5_phut_tu_luc_do(tmp_path):
    """Video 1 Đạt từ lâu; video 2 kết thúc `loi` muộn (không có lần chấm mới) ⇒ mốc là lúc video 2 cập nhật. Chưa đủ 5 phút sau đó ⇒
    chưa áp; đủ ⇒ áp (video Đạt còn lại). ĐỘT BIẾN: chỉ lấy mốc chấm ⇒ ca 'chưa đủ' áp sớm ⇒ ĐỎ."""
    san = San(tmp_path)
    conn = san.mo()
    try:
        conn.execute("UPDATE tl_danh_gia SET luc = luc - 3600")
        conn.execute("UPDATE tl_job_video SET cap_nhat_luc = cap_nhat_luc - 3600")
        conn.commit()
        hang_doi.dat(conn, san.vids[1], "loi", loi_text="x")  # cập nhật_lúc = bây giờ
    finally:
        conn.close()
    assert _thu(san, _sau(60)) == ([], [])
    kq, _ = _thu(san, _sau(CHO + 5))
    assert kq == [san.job]


def test_bo_dang_khoa_la_loi_tam_vong_sau_thu_lai(tmp_path):
    san = San(tmp_path)
    conn = san.mo()
    try:
        ap_vao_bo.khoi_tao(conn)
        conn.execute("INSERT INTO tl_ap_bo_khoa (folder_id, job_id, luc) VALUES (?, 999, ?)", (F1, time.time()))
        conn.commit()
    finally:
        conn.close()
    bo_qua: set[int] = set()
    assert _thu(san, _sau(CHO + 5), bo_qua=bo_qua) == ([], []) and bo_qua == set()
    conn = san.mo()
    try:
        conn.execute("DELETE FROM tl_ap_bo_khoa")
        conn.commit()
    finally:
        conn.close()
    kq, _ = _thu(san, _sau(CHO + 5), bo_qua=bo_qua)
    assert kq == [san.job]


def test_sai_chu_la_loi_co_dinh_bao_mot_lan_khong_thu_lai_moi_vong(tmp_path):
    san = San(tmp_path)
    dem = []

    def chu_khac(ids):
        dem.append(1)
        return {i: ("khac@x", "khac@x") for i in ids}
    bo_qua: set[int] = set()
    assert _thu(san, _sau(CHO + 5), chu_cua=chu_khac, bo_qua=bo_qua)[0] == [] and bo_qua == {san.job}
    _thu(san, _sau(CHO + 5), chu_cua=chu_khac, bo_qua=bo_qua)
    assert len(dem) == 1 and san.hang() == []


def test_khoi_chay_hong_thi_nha_khoa_bo(tmp_path):
    san = San(tmp_path)

    def hong(_):
        raise RuntimeError("không khởi được thread")
    kq, _ = _thu(san, _sau(CHO + 5), khoi_chay=hong)
    assert kq == []
    conn = san.mo()
    try:
        assert conn.execute("SELECT count(*) FROM tl_ap_bo_khoa").fetchone()[0] == 0
    finally:
        conn.close()


def test_luot_khong_phai_vao_bo_khong_bao_gio_tu_ap(tmp_path):
    san = San(tmp_path)
    conn = san.mo()
    try:
        j = hang_doi.tao_job(conn, A, [{"kieu": "drive", "file_id": "LIBFILE00001" + "z" * 8}], ten_bo="thư viện")
        vid = conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (j,)).fetchone()[0]
        log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
        nhat_ky.ghi_danh_gia(conn, log_id, A, "dat")
        hang_doi.dat(conn, vid, "xong", video_log_id=log_id, drive_file_id_ra="RAFILE0009" + "q" * 10)
        assert j not in tu_ap_vao_bo.moc_cac_luot(conn)
    finally:
        conn.close()


def _worker_tren_san(san, tmp_path, monkeypatch, bat=True):
    from web import thay_logo_worker as tw
    monkeypatch.setattr(ap_vao_bo, "dang_bat", lambda: bat)
    monkeypatch.setattr(tu_ap_vao_bo, "CHO_GIAY", -1)  # bỏ cửa sổ chờ trong test vòng worker (cửa sổ có test riêng ở trên)
    monkeypatch.setattr(tu_ap_vao_bo.thu_tu_ap, "__defaults__", (None, -1))
    jobs = tmp_path / "jobs.db"
    jobs.touch()
    w = tw.ThayLogoWorker(san.db, jobs, tmp_path / "data", tai_ve=lambda n, d: d, tai_len=lambda p, j: "x", ffmpeg="ffmpeg",
                          nghi_giay=0.01, drive_tl=san.drive)
    w.goi_ap = []
    monkeypatch.setattr(w, "_chu_cua", _chu)
    monkeypatch.setattr(w, "bat_dau_ap", w.goi_ap.append)
    monkeypatch.setattr(w, "dia_trong_gb", lambda: 0.0)  # ĐĨA ĐẦY: `mot_luot` trả "cho_dia" ngay
    goc = w.mot_luot

    def mot_luot_roi_dung():
        try:
            return goc()
        finally:
            w._dung.set()
    monkeypatch.setattr(w, "mot_luot", mot_luot_roi_dung)
    return w


def test_vong_worker_tu_ap_ca_khi_dia_day(tmp_path, monkeypatch):
    """Tự áp chạy ở đầu vòng, TRƯỚC cổng đĩa / nhường lane tải. ĐỘT BIẾN: dời `_tu_ap()` vào sau cổng ⇒ đĩa đầy thì không áp ⇒ ĐỎ."""
    san = San(tmp_path)
    w = _worker_tren_san(san, tmp_path, monkeypatch)
    w._chay()
    assert w._lan_cuoi == "cho_dia" and w.goi_ap == [san.job]


def test_vong_worker_co_tat_thi_khong_tu_ap(tmp_path, monkeypatch):
    san = San(tmp_path)
    w = _worker_tren_san(san, tmp_path, monkeypatch, bat=False)
    w._chay()
    conn = san.mo()
    try:  # cờ tắt ⇒ không đụng DB áp vào bộ (bảng `tl_ap_bo` thậm chí không được tạo — như route khi cờ tắt)
        assert w.goi_ap == [] and conn.execute("SELECT count(*) FROM sqlite_master WHERE name='tl_ap_bo'").fetchone()[0] == 0
    finally:
        conn.close()


# ------------------------------------------------------------------ /bo: giờ tự trả về bộ, số đã trả, chờ máy định vị (P5)
class _HopGia:
    def __init__(self, co_ket_qua):
        self.co = set(co_ket_qua)

    def doc_ket_qua(self, vid, luot=1):
        return {"ok": 1} if vid in self.co else None


def _app_bo(san, monkeypatch, hop, bat=True):
    import types

    import pytest
    pytest.importorskip("fastapi")
    from fastapi import FastAPI, Request
    from test_thay_logo_relay import _Client
    from thay_logo_may_chu import MayChu

    from web import thay_logo_routes
    monkeypatch.setattr(ap_vao_bo, "dang_bat", lambda: bat)
    w = types.SimpleNamespace(drive_tl=san.drive, ly_do_khong_nhan=None, hop=hop)

    def require_user(request: Request) -> str:
        return request.headers["x-user"]
    app = FastAPI()
    thay_logo_routes.dang_ky_route_member(app, lambda: san.db, require_user, lambda e: False, lambda: w, lambda e, ids: set())
    mc = MayChu(app)
    return mc, _Client(mc)


def _bo_cua(c, job):
    return next(b for b in c.get("/api/thay-logo/bo", headers={"x-user": A}).json()["bo"] if b["job_id"] == job)


def test_bo_tra_gio_tu_ap_va_so_da_tra(tmp_path, monkeypatch):
    san = San(tmp_path)
    mc, c = _app_bo(san, monkeypatch, _HopGia([]))
    try:
        b = _bo_cua(c, san.job)
        assert b["tu_ap_luc"] is not None and abs(b["tu_ap_luc"] - (time.time() + CHO)) < 30 and b["da_tra_bo"] == 0
        san.ap(); san.chay()
        b = _bo_cua(c, san.job)
        assert b["tu_ap_luc"] is None and b["da_tra_bo"] == 2  # đã có dòng tl_ap_bo ⇒ hết hẹn giờ tự áp
    finally:
        mc.dung()


def test_bo_co_tat_khong_tra_gio_tu_ap(tmp_path, monkeypatch):
    san = San(tmp_path)
    mc, c = _app_bo(san, monkeypatch, _HopGia([]), bat=False)
    try:
        b = _bo_cua(c, san.job)
        assert b["tu_ap_luc"] is None and b["da_tra_bo"] == 0
    finally:
        mc.dung()


def test_cho_dinh_vi_chi_tinh_video_chua_co_ket_qua(tmp_path, monkeypatch):
    """Video `cho_agy` đã có kết quả trong hộp thư (đang xếp hàng render) KHÔNG tính là "máy định vị chưa phản hồi".
    ĐỘT BIẾN: bỏ kiểm `doc_ket_qua` ⇒ lượt có kết quả vẫn báo chờ ⇒ ĐỎ."""
    san = San(tmp_path)
    conn = san.mo()
    try:
        hang_doi.dat(conn, san.vids[0], "cho_agy", cho_agy_tu=time.time() - 1200)
        hang_doi.dat(conn, san.vids[1], "cho_agy", cho_agy_tu=time.time() - 600)
    finally:
        conn.close()
    mc, c = _app_bo(san, monkeypatch, _HopGia([san.vids[0]]))  # video 1 đã có kết quả, video 2 chưa
    try:
        assert 590 <= _bo_cua(c, san.job)["cho_dinh_vi_giay"] <= 700
    finally:
        mc.dung()
    mc, c = _app_bo(san, monkeypatch, _HopGia(san.vids))  # cả hai đã có kết quả ⇒ không báo
    try:
        assert _bo_cua(c, san.job)["cho_dinh_vi_giay"] is None
    finally:
        mc.dung()
