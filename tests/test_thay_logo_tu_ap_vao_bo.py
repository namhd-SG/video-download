"""Tự trả video Đạt về bộ gốc (`thay_logo/tu_ap_vao_bo.py`): đủ bốn điều kiện mới áp; Hoàn tác có hiệu lực (không tự áp lại); lỗi tạm thử
lại vòng sau, lỗi cố định báo một lần. Sân Drive GIẢ + DB file thật dùng lại `San` của test áp vào bộ."""
import time

from test_thay_logo_ap_vao_bo import F1, A, San, _chu

from tiktok_music_downloader.thay_logo import ap_vao_bo, hang_doi, nhat_ky, tu_ap_vao_bo

CHO = tu_ap_vao_bo.CHO_GIAY


def _thu(san, bay_gio, chu_cua=_chu, khoi_chay=None):
    goi = []
    conn = san.mo()
    try:
        kq = tu_ap_vao_bo.thu_tu_ap(conn, chu_cua, khoi_chay or goi.append, bay_gio=bay_gio)
    finally:
        conn.close()
    return kq, goi


def _san(tmp_path, **kw):
    """Sân với mốc bật tính năng = 0 (lượt của sân tạo TRƯỚC lúc lớp tự áp chạy lần đầu; test mốc cắt có riêng ở dưới)."""
    san = San(tmp_path, **kw)
    _dat_moc(san, 0)
    return san


def _dat_moc(san, gia_tri):
    conn = san.mo()
    try:
        tu_ap_vao_bo.khoi_tao(conn)
        conn.execute("UPDATE tl_tu_ap_moc SET gia_tri=? WHERE khoa='bat_dau'", (gia_tri,))
        conn.commit()
    finally:
        conn.close()


def _da_xet(san):
    conn = san.mo()
    try:
        tu_ap_vao_bo.khoi_tao(conn)
        return {r[0]: r[1] for r in conn.execute("SELECT job_id, ly_do FROM tl_tu_ap_da_xet")}
    finally:
        conn.close()


def _sau(giay):
    return time.time() + giay


def test_du_dieu_kien_va_qua_5_phut_thi_tu_ap_that(tmp_path):
    san = _san(tmp_path)
    kq, goi = _thu(san, _sau(CHO + 5))
    assert kq == goi == [san.job]
    san.chay()
    assert len(san.ban_moi_trong_bo()) == 2 and san.vi_pham == []


def test_chua_qua_5_phut_sau_lan_cham_cuoi_thi_chua_ap(tmp_path):
    """ĐỘT BIẾN: bỏ điều kiện cửa sổ chờ ⇒ áp ngay ⇒ ĐỎ."""
    san = _san(tmp_path)
    kq, goi = _thu(san, _sau(CHO - 30))
    assert kq == goi == [] and san.hang() == []


def test_da_hoan_tac_thi_khong_tu_ap_lai(tmp_path):
    """Chốt L1: lượt đã có dòng `tl_ap_bo` (áp rồi Hoàn tác) ⇒ máy KHÔNG tự áp lại; chỉ nút tay. ĐỘT BIẾN: bỏ `NOT EXISTS tl_ap_bo` ⇒ ĐỎ."""
    san = _san(tmp_path)
    san.ap(); san.chay(); san.hoan_tac(); san.chay()
    conn = san.mo()
    try:
        assert ap_vao_bo.trang_thai(conn, san.job)["trang_thai"] == "chua_ap"  # đúng trạng thái agy chỉ ra
    finally:
        conn.close()
    kq, goi = _thu(san, _sau(CHO * 10))
    assert kq == goi == []


def test_con_video_chua_cham_thi_chua_ap(tmp_path):
    san = _san(tmp_path)
    conn = san.mo()
    try:  # video 2: xong nhưng CHƯA chấm (bản ghi nhật ký mới, không có đánh giá)
        log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
        hang_doi.dat(conn, san.vids[1], "xong", video_log_id=log_id)
    finally:
        conn.close()
    assert _thu(san, _sau(CHO * 10)) == ([], [])


def test_con_video_dang_cho_may_thi_chua_ap(tmp_path):
    san = _san(tmp_path)
    conn = san.mo()
    try:
        hang_doi.dat(conn, san.vids[1], "cho_agy", cho_agy_tu=time.time())
    finally:
        conn.close()
    assert _thu(san, _sau(CHO * 10)) == ([], [])


def test_video_cuoi_ket_thuc_loi_muon_tinh_5_phut_tu_luc_do(tmp_path):
    """Video 1 Đạt từ lâu; video 2 kết thúc `loi` muộn (không có lần chấm mới) ⇒ mốc là lúc video 2 cập nhật. Chưa đủ 5 phút sau đó ⇒
    chưa áp; đủ ⇒ áp (video Đạt còn lại). ĐỘT BIẾN: chỉ lấy mốc chấm ⇒ ca 'chưa đủ' áp sớm ⇒ ĐỎ."""
    san = _san(tmp_path)
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
    san = _san(tmp_path)
    conn = san.mo()
    try:
        ap_vao_bo.khoi_tao(conn)
        conn.execute("INSERT INTO tl_ap_bo_khoa (folder_id, job_id, luc) VALUES (?, 999, ?)", (F1, time.time()))
        conn.commit()
    finally:
        conn.close()
    assert _thu(san, _sau(CHO + 5)) == ([], []) and _da_xet(san) == {}  # lỗi TẠM: không ghi mốc ⇒ vòng sau còn thử
    conn = san.mo()
    try:
        conn.execute("DELETE FROM tl_ap_bo_khoa")
        conn.commit()
    finally:
        conn.close()
    kq, _ = _thu(san, _sau(CHO + 5))
    assert kq == [san.job] and _da_xet(san) == {san.job: "tu_ap"}


def test_sai_chu_la_loi_co_dinh_bao_mot_lan_khong_thu_lai_moi_vong(tmp_path):
    san = _san(tmp_path)
    dem = []

    def chu_khac(ids):
        dem.append(1)
        return {i: ("khac@x", "khac@x") for i in ids}
    assert _thu(san, _sau(CHO + 5), chu_cua=chu_khac)[0] == [] and _da_xet(san)[san.job].startswith("loi 403")
    _thu(san, _sau(CHO + 5), chu_cua=chu_khac)  # vòng sau — cũng như sau khởi động lại: mốc nằm trong DB, không nằm trong bộ nhớ
    assert len(dem) == 1 and san.hang() == []


def test_khoi_chay_hong_thi_nha_khoa_bo(tmp_path):
    san = _san(tmp_path)

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
    san = _san(tmp_path)
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
    san = _san(tmp_path)
    w = _worker_tren_san(san, tmp_path, monkeypatch)
    w._chay()
    assert w._lan_cuoi == "cho_dia" and w.goi_ap == [san.job]


def test_vong_worker_co_tat_thi_khong_tu_ap(tmp_path, monkeypatch):
    san = _san(tmp_path)
    w = _worker_tren_san(san, tmp_path, monkeypatch, bat=False)
    w._chay()
    conn = san.mo()
    try:  # cờ tắt ⇒ không đặt lịch, không ghi dòng áp nào
        assert w.goi_ap == [] and conn.execute("SELECT count(*) FROM tl_ap_bo").fetchone()[0] == 0
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
    w = types.SimpleNamespace(drive_tl=san.drive, ly_do_khong_nhan=None, hop=hop, bat_dau_ap=lambda j: None)

    def require_user(request: Request) -> str:
        return request.headers["x-user"]
    app = FastAPI()
    thay_logo_routes.dang_ky_route_member(app, lambda: san.db, require_user, lambda e: False, lambda: w, lambda e, ids: set())
    mc = MayChu(app)
    return mc, _Client(mc)


def _bo_cua(c, job):
    return next(b for b in c.get("/api/thay-logo/bo", headers={"x-user": A}).json()["bo"] if b["job_id"] == job)


def test_bo_tra_gio_tu_ap_va_so_da_tra(tmp_path, monkeypatch):
    san = _san(tmp_path)
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
    san = _san(tmp_path)
    mc, c = _app_bo(san, monkeypatch, _HopGia([]), bat=False)
    try:
        b = _bo_cua(c, san.job)
        assert b["tu_ap_luc"] is None and b["da_tra_bo"] == 0
    finally:
        mc.dung()


def test_cho_dinh_vi_chi_tinh_video_chua_co_ket_qua(tmp_path, monkeypatch):
    """Video `cho_agy` đã có kết quả trong hộp thư (đang xếp hàng render) KHÔNG tính là "máy định vị chưa phản hồi".
    ĐỘT BIẾN: bỏ kiểm `doc_ket_qua` ⇒ lượt có kết quả vẫn báo chờ ⇒ ĐỎ."""
    san = _san(tmp_path)
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


# ------------------------------------------------------------------ hồi quy từ review độc lập PR2
def _luot_b_cung_video(san):
    """Lượt B cho CÙNG các video (cùng bản trong bộ) với lượt A, đã xong + Đạt."""
    import json

    from test_thay_logo_ap_vao_bo import RA
    conn = san.mo()
    try:
        nguon = [json.loads(r[0]) for r in conn.execute("SELECT nguon FROM tl_job_video WHERE job_id=? ORDER BY id", (san.job,))]
        job_b = hang_doi.tao_job(conn, A, nguon, ten_bo="N.1AAAA")
        for i, (vid,) in enumerate(conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (job_b,)).fetchall(), 1):
            lid = nhat_ky.bat_dau_video(conn, nguon_video="x")
            nhat_ky.ghi_danh_gia(conn, lid, A, "dat")
            hang_doi.dat(conn, vid, "xong", video_log_id=lid, drive_file_id_ra=RA[i])
    finally:
        conn.close()
    return job_b


def _hoan_tac_luot(san, job):
    goc, san.job = san.job, job
    try:
        san.hoan_tac(); san.chay()
    finally:
        san.job = goc


def test_hoan_tac_luot_moi_khong_lam_luot_cu_bi_ap_lai(tmp_path):
    """H1 (review PR2, tái hiện được): A tự áp → Hoàn tác A → lượt B cùng video tự áp (dòng tl_ap_bo DỜI sang B, A còn 0 dòng) →
    Hoàn tác B → vòng sau (≈ khởi động lại) máy KHÔNG được áp lại A. ĐỘT BIẾN: bỏ điều kiện mốc `tl_tu_ap_da_xet` ⇒ A bị áp lại ⇒ ĐỎ."""
    san = _san(tmp_path)
    job_a = san.job
    assert _thu(san, _sau(CHO + 5))[0] == [job_a]
    san.chay()
    _hoan_tac_luot(san, job_a)
    job_b = _luot_b_cung_video(san)
    assert _thu(san, _sau(CHO + 5))[0] == [job_b]  # lượt MỚI do người dùng chấm Đạt: tự áp là đúng
    san.job = job_b; san.chay(); san.job = job_a
    _hoan_tac_luot(san, job_b)
    assert _thu(san, _sau(CHO * 100)) == ([], [])


def test_ap_tay_roi_hoan_tac_cung_khong_bi_ap_lai_qua_luot_khac(tmp_path):
    """Như trên nhưng A được áp TAY (route ghi mốc "ap_tay")."""
    san = _san(tmp_path)
    job_a = san.job
    san.ap()
    conn = san.mo()
    try:
        tu_ap_vao_bo.danh_dau(conn, job_a, "ap_tay")  # đúng việc route POST …/ap làm sau dat_lich_ap
    finally:
        conn.close()
    san.chay()
    _hoan_tac_luot(san, job_a)
    job_b = _luot_b_cung_video(san)
    assert _thu(san, _sau(CHO + 5))[0] == [job_b]
    san.job = job_b; san.chay(); san.job = job_a
    _hoan_tac_luot(san, job_b)
    assert _thu(san, _sau(CHO * 100)) == ([], [])


def test_luot_tao_truoc_moc_bat_tinh_nang_khong_tu_ap(tmp_path):
    """H2: bật cờ trên prod KHÔNG tự áp hàng loạt lượt cũ (tạo trước lúc lớp tự áp chạy lần đầu). ĐỘT BIẾN: bỏ điều kiện `tao_luc >= bat_dau`
    ⇒ lượt cũ bị áp ⇒ ĐỎ."""
    san = San(tmp_path)  # lượt tạo TRƯỚC; lớp tự áp chưa từng chạy
    conn = san.mo()
    try:
        tu_ap_vao_bo.khoi_tao(conn)  # lần chạy đầu ⇒ mốc bat_dau = bây giờ (sau lượt)
        moc = conn.execute("SELECT gia_tri FROM tl_tu_ap_moc WHERE khoa='bat_dau'").fetchone()[0]
        tu_ap_vao_bo.khoi_tao(conn)  # gọi lại không dời mốc
        assert conn.execute("SELECT gia_tri FROM tl_tu_ap_moc WHERE khoa='bat_dau'").fetchone()[0] == moc
    finally:
        conn.close()
    assert _thu(san, _sau(CHO * 100)) == ([], [])
    job_b = _luot_b_cung_video(san)  # lượt tạo SAU mốc ⇒ được tự áp
    assert _thu(san, _sau(CHO + 5))[0] == [job_b]


def test_hoan_tac_dang_do_o_luot_khac_la_loi_tam(tmp_path):
    """M1: 409 do hàng của lượt khác / hoàn tác đang dở trên cùng bản là trạng thái TỰ HẾT ⇒ không ghi mốc, vòng sau còn thử."""
    san = _san(tmp_path)
    job_b = _luot_b_cung_video(san)
    san.ap()  # lượt A áp (dở: chưa chạy Drive) ⇒ bản trong bộ đang có hàng của A
    kq, _ = _thu(san, _sau(CHO + 5))
    assert job_b not in kq and job_b not in _da_xet(san)


def test_route_hoan_tac_ghi_moc_va_het_hen_gio(tmp_path, monkeypatch):
    """Route POST …/hoan-tac ghi mốc "hoan_tac" ⇒ lượt không bao giờ được tự áp lại. (POST …/ap ghi "ap_tay" cùng chỗ; ca đó cần jobs.db
    thật để kiểm chủ nên kiểm qua `danh_dau` ở test trên.)"""
    san = _san(tmp_path)
    san.ap(); san.chay()
    mc, c = _app_bo(san, monkeypatch, _HopGia([]))
    try:
        san.drive.cau_hinh = True  # worker giả: `bat_dau_ap` không khởi thread Drive
        assert c.post(f"/api/thay-logo/bo/{san.job}/hoan-tac", headers={"x-user": A}).status_code == 202
        assert _da_xet(san).get(san.job) == "hoan_tac"
    finally:
        mc.dung()
    san.chay()
    assert _thu(san, _sau(CHO * 100)) == ([], [])


def test_bo_khong_hen_gio_cho_nguoi_khong_phai_chu(tmp_path, monkeypatch):
    """M2: admin/ người khác xem lượt ⇒ không có `tu_ap_luc` (máy không áp thay, không hứa, không nút "Trả ngay")."""
    import types

    import pytest
    pytest.importorskip("fastapi")
    from fastapi import FastAPI, Request
    from test_thay_logo_relay import _Client
    from thay_logo_may_chu import MayChu

    from web import thay_logo_routes
    san = _san(tmp_path)
    monkeypatch.setattr(ap_vao_bo, "dang_bat", lambda: True)
    w = types.SimpleNamespace(drive_tl=san.drive, ly_do_khong_nhan=None, hop=_HopGia([]))
    app = FastAPI()

    def require_user(request: Request) -> str:
        return request.headers["x-user"]
    thay_logo_routes.dang_ky_route_member(app, lambda: san.db, require_user, lambda e: e == "sep@x", lambda: w, lambda e, ids: set())
    mc = MayChu(app)
    c = _Client(mc)
    try:
        b = next(x for x in c.get("/api/thay-logo/bo", headers={"x-user": "sep@x"}).json()["bo"] if x["job_id"] == san.job)
        assert b["tu_ap_luc"] is None
    finally:
        mc.dung()
