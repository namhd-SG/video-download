"""Khoanh chỗ lộ (pha 1a): quy đổi toạ độ, dải đỏ/vàng, tự gán loại lỗi 5 nhánh, giữ/dọn video để sửa, route khoanh."""
import gzip
import json
import time

import pytest

from tiktok_music_downloader.thay_logo import hang_doi, khoanh, nhat_ky


# ---------------------------------------------------------------- toạ độ
def test_quy_doi_ti_le_sang_px_khung_goc():
    assert khoanh.quy_doi({"x": 0.5, "y": 0.25, "w": 0.1, "h": 0.05}, 720, 1280) == (360, 320, 72, 64)


@pytest.mark.parametrize("vung", [{"x": -0.1, "y": 0, "w": 0.2, "h": 0.2}, {"x": 0.9, "y": 0, "w": 0.2, "h": 0.2},
                                  {"x": 0, "y": 0, "w": 0.001, "h": 0.2}, {"x": "a", "y": 0, "w": 0.2, "h": 0.2}, {"x": 0.1}])
def test_quy_doi_tu_choi_vung_sai(vung):
    with pytest.raises(ValueError):
        khoanh.quy_doi(vung, 720, 1280)


# ---------------------------------------------------------------- dải thời gian
def _e(f, state, **k):
    return {"frame": f, "state": state, "x": 10, "y": 10, "w": 50, "h": 20, **k}


def test_dai_do_la_lo_trong_doi_vet_vang_la_de_du_bi_chan_khong_to_noi_suy():
    vet = [_e(0, "detected"), _e(1, "hidden_sub"), _e(2, "hidden_sub"), _e(3, "detected", de_khi_biet=True),
           _e(4, "filled"), _e(5, "detected"), _e(20, "hidden")]  # khung 20 ngoài đời sống vết (sau khung đè cuối) ⇒ không đỏ
    doan = khoanh.dai_thoi_gian([vet], {0: "render"})
    assert doan == [{"loai": "do", "tu": 1, "den": 2}, {"loai": "vang", "tu": 3, "den": 3}]


def test_dai_bo_vet_khong_render_va_khung_vet_khac_da_de():
    v0 = [_e(0, "detected"), _e(1, "hidden_net"), _e(2, "detected")]
    v1 = [_e(1, "detected")]
    assert khoanh.dai_thoi_gian([v0, v1], {0: "render", 1: "render"}) == []  # khung 1 có vết khác đè ⇒ không lộ
    assert khoanh.dai_thoi_gian([v0], {0: "cho_nguoi"}) == []


# ---------------------------------------------------------------- tự gán loại lỗi 5 nhánh
BOX_MAY = (378, 864, 143, 24)


@pytest.mark.parametrize("cho_nguoi, giu_goc, vung, box_may, chan, mong", [
    (True, False, (1, 1, 50, 20), None, [], ("may_khong_thay", None)),
    (False, True, None, BOX_MAY, [], ("che_nham", None)),
    (False, False, (522, 850, 53, 30), BOX_MAY, [], ("lo_mep", None)),          # chữ "AI" lộ sát mép phải (v13#63)
    (False, False, (100, 200, 60, 20), BOX_MAY, [], ("de_lech_cho", None)),     # máy đè chỗ khác trên cùng khung
    (False, False, (50, 50, 60, 20), None, [("hidden_sub", (55, 52, 50, 18))], ("lo_do_cong_chan", "hidden_sub")),
    (False, False, (50, 50, 60, 20), None, [("hidden_sub", (400, 600, 50, 18))], ("lo_mat_dau", None)),
])
def test_gan_mau_loi_tat_dinh(cho_nguoi, giu_goc, vung, box_may, chan, mong):
    assert khoanh.gan_mau_loi(cho_nguoi, giu_goc, vung, box_may, chan) == mong


def test_khung_tai_lay_box_may_va_box_bi_chan():
    track = [[_e(5, "detected", x=1)], [_e(5, "hidden_ring", x=300)], [_e(5, "detected", x=900)]]
    may, chan = khoanh.khung_tai(track, {0: "render", 1: "render", 2: "cho_nguoi"}, 5)
    assert may == (1, 10, 50, 20) and chan == [("hidden_ring", (300, 10, 50, 20))]


# ---------------------------------------------------------------- giữ / dọn video
def _video(conn, ket_thuc):
    vid = nhat_ky.bat_dau_video(conn, nguon_video="x")
    conn.execute("UPDATE tl_video SET ket_thuc=?, kho='720x1280', fps=30, so_khung=100 WHERE id=?", (ket_thuc, vid))
    conn.commit()
    return vid


def _thu_muc(tmp_path, vid):
    d = tmp_path / khoanh.THU_MUC_VIDEO / str(vid)
    d.mkdir(parents=True)
    (d / "goc.mp4").write_bytes(b"x")
    return d


def test_giu_video_doi_khoi_scratch_va_tach_thu_muc_nhat_ky(tmp_path):
    s = tmp_path / "scratch"
    s.mkdir()
    (s / "goc.mp4").write_bytes(b"g")
    (s / "ra.mp4").write_bytes(b"r")
    d = khoanh.giu_video(tmp_path, 7, s / "goc.mp4", s / "ra.mp4")
    assert d == tmp_path / "thay_logo_video" / "7" and (d / "goc.mp4").read_bytes() == b"g" and (d / "ra.mp4").read_bytes() == b"r"
    assert not (s / "goc.mp4").exists()
    assert d.parent != tmp_path / "thay_logo"  # KHÔNG chung thư mục `don_dep` có trần dung lượng


def test_don_video_sua_theo_han_danh_gia_va_khoanh(tmp_path):
    conn = nhat_ky.mo(tmp_path / "l.db")
    hang_doi.khoi_tao(conn)
    bay = time.time()
    moi = _video(conn, bay - 86400)                    # 1 ngày, chưa chấm ⇒ giữ
    cu = _video(conn, bay - 8 * 86400)                 # 8 ngày, không khoanh ⇒ xoá
    cu_khoanh = _video(conn, bay - 8 * 86400)          # 8 ngày, có khoanh ⇒ giữ (180 ngày)
    dat = _video(conn, bay - 3600)                     # chấm Đạt, không ca chờ ⇒ xoá ngay
    dat_con_ca = _video(conn, bay - 3600)              # chấm Đạt nhưng còn ca chờ ⇒ giữ
    for v in (moi, cu, cu_khoanh, dat, dat_con_ca):
        _thu_muc(tmp_path, v)
    for v in (cu_khoanh, dat_con_ca):
        khoanh.ghi_ca(conn, video_log_id=v, job_video_id=1, member="a", khung=1, vung=(1, 1, 9, 9), mau_loi="lo_mep",
                      chan_cu=None, box_may=None)
    for v in (dat, dat_con_ca):
        nhat_ky.ghi_danh_gia(conn, v, "a", "dat")
    kq = khoanh.don_video_sua(conn, tmp_path, bay_gio=bay, dia_trong_gb=lambda: 999)
    con = sorted(int(p.name) for p in (tmp_path / khoanh.THU_MUC_VIDEO).iterdir())
    assert con == sorted([moi, cu_khoanh, dat_con_ca]) and kq["xoa"] == 2


def test_don_video_sua_khi_thieu_dia_xoa_cu_truoc_video_khoanh_sau_cung(tmp_path):
    conn = nhat_ky.mo(tmp_path / "l.db")
    hang_doi.khoi_tao(conn)
    bay = time.time()
    a, b = _video(conn, bay - 3 * 3600), _video(conn, bay - 2 * 3600)
    c = _video(conn, bay - 4 * 3600)
    for v in (a, b, c):
        _thu_muc(tmp_path, v)
    khoanh.ghi_ca(conn, video_log_id=c, job_video_id=1, member="a", khung=1, vung=(1, 1, 9, 9), mau_loi="lo_mep",
                  chan_cu=None, box_may=None)
    goc = tmp_path / khoanh.THU_MUC_VIDEO

    def dia():  # đĩa "đủ" khi còn ≤ 2 thư mục video
        return khoanh.DIA_TRONG_TOI_THIEU_GB if len(list(goc.iterdir())) <= 2 else 0.0
    khoanh.don_video_sua(conn, tmp_path, bay_gio=bay, dia_trong_gb=dia)
    con = sorted(int(p.name) for p in (tmp_path / khoanh.THU_MUC_VIDEO).iterdir())
    assert con == sorted([b, c])  # xoá a (cũ nhất KHÔNG khoanh) trước; c có khoanh dù cũ hơn vẫn giữ


def test_don_dep_giu_track_video_co_khoanh_180_ngay(tmp_path):
    conn = nhat_ky.mo(tmp_path / "l.db")
    bay = time.time()
    v = nhat_ky.bat_dau_video(conn, nguon_video="x")
    conn.execute("UPDATE tl_video SET bat_dau=?, duong_dan_track='t' WHERE id=?", (bay - 90 * 86400, v))
    conn.commit()
    (tmp_path / "thay_logo" / str(v)).mkdir(parents=True)
    khoanh.ghi_ca(conn, video_log_id=v, job_video_id=1, member="a", khung=1, vung=(1, 1, 9, 9), mau_loi="lo_mep",
                  chan_cu=None, box_may=None)
    assert nhat_ky.don_dep(conn, tmp_path / "thay_logo", bay_gio=bay)["xoa"] == 0  # 90 ngày > 60 nhưng có khoanh ⇒ giữ


# ---------------------------------------------------------------- route
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")


@pytest.fixture
def ctx(tmp_path):
    from fastapi import FastAPI, Request
    from test_thay_logo_relay import _Client
    from thay_logo_may_chu import MayChu

    from web import thay_logo_routes
    db = tmp_path / "tl.db"

    def require_user(request: Request) -> str:
        return request.headers["x-user"]
    app = FastAPI()
    thay_logo_routes.dang_ky_route_member(app, lambda: db, require_user, lambda e: e == "sep@x", lambda: None,
                                          lambda email, ids: set())
    mc = MayChu(app)
    yield _Client(mc), db, tmp_path
    mc.dung()


def _job(db, tmp_path, trang_thai="xong"):
    conn = nhat_ky.mo(db)
    hang_doi.khoi_tao(conn)
    j = hang_doi.tao_job(conn, "a@x", [{"kieu": "drive", "file_id": "F" * 20}])
    vid = conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (j,)).fetchone()[0]
    log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
    tp = tmp_path / "track.json.gz"
    with gzip.open(tp, "wt") as f:
        json.dump([[_e(9, "detected", x=378, y=864, w=143, h=24), _e(10, "hidden_sub", x=378, y=864, w=143, h=24),
                    _e(11, "detected", x=378, y=864, w=143, h=24, de_khi_biet=True)]], f)
    conn.execute("UPDATE tl_video SET kho='720x1280', fps=30, so_khung=100, duong_dan_track=? WHERE id=?", (str(tp), log_id))
    conn.execute("INSERT INTO tl_vet (video_id, vet, trang_thai) VALUES (?, 0, 'render')", (log_id,))
    conn.commit()
    hang_doi.dat(conn, vid, trang_thai, video_log_id=log_id)
    conn.close()
    return vid, log_id


def _h(u):
    return {"x-user": u}


def test_route_dai_tra_doan_do_vang(ctx):
    c, db, tmp = ctx
    vid, _ = _job(db, tmp)
    r = c.get(f"/api/thay-logo/videos/{vid}/dai", headers=_h("a@x"))
    assert r.status_code == 200
    assert r.json()["doan"] == [{"loai": "do", "tu": 10, "den": 10}, {"loai": "vang", "tu": 11, "den": 11}]
    assert c.get(f"/api/thay-logo/videos/{vid}/dai", headers=_h("b@x")).status_code == 403


def test_route_khoanh_luu_ca_tu_gan_loai_va_quy_doi(ctx):
    c, db, tmp = ctx
    vid, log_id = _job(db, tmp)
    # khung 9: máy đè (378,864,143,24); khoanh chữ "AI" sát mép phải ⇒ lo_mep
    r = c.post(f"/api/thay-logo/videos/{vid}/khoanh", headers=_h("a@x"),
               json={"khung": 9, "vung": {"x": 522 / 720, "y": 850 / 1280, "w": 53 / 720, "h": 30 / 1280}})
    assert r.status_code == 201 and r.json()["mau_loi"] == "lo_mep"
    # khung 10: máy không đè, cổng phụ đề chặn đúng chỗ khoanh ⇒ lo_do_cong_chan
    r2 = c.post(f"/api/thay-logo/videos/{vid}/khoanh", headers=_h("a@x"),
                json={"khung": 10, "vung": {"x": 380 / 720, "y": 866 / 1280, "w": 100 / 720, "h": 20 / 1280}})
    assert r2.json() == {"id": 2, "mau_loi": "lo_do_cong_chan", "chan_cu": "hidden_sub"}
    r3 = c.post(f"/api/thay-logo/videos/{vid}/khoanh", headers=_h("a@x"), json={"khung": 9, "giu_goc": True})
    assert r3.json()["mau_loi"] == "che_nham"
    conn = nhat_ky.mo(db)
    hang = conn.execute("SELECT video_log_id, job_video_id, x, y, w, h, box_may FROM tl_ca_khoanh WHERE id=1").fetchone()
    assert tuple(hang)[:6] == (log_id, vid, 522, 850, 53, 30) and json.loads(hang["box_may"]) == [378, 864, 143, 24]


@pytest.mark.parametrize("body, ma", [({"khung": 9}, 400), ({"khung": 500, "vung": {"x": 0, "y": 0, "w": 0.1, "h": 0.1}}, 400),
                                      ({"khung": 9, "vung": {"x": 0.95, "y": 0, "w": 0.1, "h": 0.1}}, 400),
                                      ({"khung": 10, "giu_goc": True}, 409)])
def test_route_khoanh_tu_choi(ctx, body, ma):
    c, db, tmp = ctx
    vid, _ = _job(db, tmp)
    assert c.post(f"/api/thay-logo/videos/{vid}/khoanh", headers=_h("a@x"), json=body).status_code == ma


def test_route_khoanh_chi_video_da_xong_hoac_may_khong_chac_va_dung_quyen(ctx):
    c, db, tmp = ctx
    vid, _ = _job(db, tmp, trang_thai="dang_chay")
    body = {"khung": 9, "vung": {"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}}
    assert c.post(f"/api/thay-logo/videos/{vid}/khoanh", headers=_h("a@x"), json=body).status_code == 409
    vid2, _ = _job(db, tmp, trang_thai="cho_nguoi")
    assert c.post(f"/api/thay-logo/videos/{vid2}/khoanh", headers=_h("b@x"), json=body).status_code == 403
    assert c.post(f"/api/thay-logo/videos/{vid2}/khoanh", headers=_h("a@x"), json=body).json()["mau_loi"] == "may_khong_thay"


def test_route_khung_tai_video_da_don_tra_404(ctx):
    c, db, tmp = ctx
    vid, _ = _job(db, tmp)
    assert c.get(f"/api/thay-logo/videos/{vid}/khung-tai/5?ban=goc", headers=_h("a@x")).status_code == 404
    assert c.get(f"/api/thay-logo/videos/{vid}/khung-tai/5?ban=xx", headers=_h("a@x")).status_code == 422


def test_route_khung_tai_trich_dung_khung_tu_video_giu(ctx):
    import cv2
    import numpy as np

    from tiktok_music_downloader.watermark import find_ffmpeg
    if find_ffmpeg() is None:
        pytest.skip("không có ffmpeg")
    c, db, tmp = ctx
    vid, log_id = _job(db, tmp)
    d = tmp / khoanh.THU_MUC_VIDEO / str(log_id)
    d.mkdir(parents=True)
    out = cv2.VideoWriter(str(d / "ra.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (64, 96))
    for i in range(30):
        out.write(np.full((96, 64, 3), i * 8, np.uint8))  # độ sáng tăng theo khung ⇒ đoán được khung nào đã trích
    out.release()
    r = c.get(f"/api/thay-logo/videos/{vid}/khung-tai/20", headers=_h("a@x"))
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8"  # JPEG
    anh = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert abs(float(anh.mean()) - 160) < 12  # khung 20 ⇒ ~160, không phải khung 0
    assert c.get(f"/api/thay-logo/videos/{vid}/dai", headers=_h("a@x")).json()["co_video"] == {"goc": False, "ra": True}
