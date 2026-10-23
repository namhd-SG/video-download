"""Ảnh soi nhanh màn Lô: chọn 3 khung, cắt quanh box, ghi mốc sau cùng, route dựng lười một lần."""
import gzip
import json
import threading
import time

import pytest

from tiktok_music_downloader.thay_logo import khoanh, soi_nhanh


def _e(f, state, x=100, y=200, w=60, h=20, **k):
    return {"frame": f, "state": state, "x": x, "y": y, "w": w, "h": h, **k}


# ---------------------------------------------------------------- chọn khung
def test_video_xong_chon_dau_giua_cuoi_cua_khung_may_de_va_box_tung_khung():
    vet = [_e(5, "detected", x=100), _e(6, "hidden_sub"), _e(7, "filled", x=110), _e(8, "detected", x=120),
           _e(9, "interpolated"), _e(12, "detected", x=130)]
    chon = soi_nhanh.chon_khung([vet], {0: "render"}, "xong", 100, "720x1280")
    assert [c["khung"] for c in chon] == [5, 8, 12]  # tập đè {5,7,8,12}: đầu, giữa (index 2), cuối — khung bị chặn/nội suy không tính
    assert all(c["ban"] == "ra" for c in chon)
    # nới max(w//2=30, 24) ngang ⇒ 120, max(h//2=10, 24) dọc ⇒ 68; ép 4:3 ⇒ 120×90, đặt giữa box (130, 210)
    assert chon[0]["cat"] == (70, 165, 120, 90)
    assert chon[2]["cat"][0] == 100                # box khung 12 ở x=130 ⇒ cắt theo box CỦA khung đó, không box chung


@pytest.mark.parametrize("box", [(660, 600, 60, 20),    # sát mép phải
                                 (0, 600, 60, 20),      # sát mép trái
                                 (300, 0, 143, 24),     # sát mép trên
                                 (300, 1256, 143, 24),  # sát mép dưới
                                 (690, 1270, 30, 10),   # góc dưới phải, box nhỏ
                                 (100, 400, 500, 30),   # box rộng
                                 (300, 300, 20, 300)])  # box cao
def test_cat_quanh_ti_le_4_3_trong_khung_va_box_nam_tron(box):
    x0, y0, w, h = soi_nhanh.cat_quanh(box, 720, 1280)
    bx, by, bw, bh = box
    assert 0 <= x0 and x0 + w <= 720 and 0 <= y0 and y0 + h <= 1280
    assert x0 <= bx and bx + bw <= x0 + w and y0 <= by and by + bh <= y0 + h  # trượt vào trong, không cắt mất box
    assert abs(w * 3 - h * 4) <= 4  # 4:3, lệch tối đa vì làm tròn số nguyên


def test_cat_quanh_sat_mep_phai_truot_vao_giu_nguyen_co():
    giua = soi_nhanh.cat_quanh((400, 600, 60, 20), 720, 1280)
    mep = soi_nhanh.cat_quanh((660, 600, 60, 20), 720, 1280)
    assert mep[2:] == giua[2:] and mep[0] + mep[2] == 720  # cùng cỡ với box ở giữa, mép phải vùng cắt trùng mép khung


def test_bo_vet_khong_render_va_video_xong_khong_khung_de_thi_rong():
    assert soi_nhanh.chon_khung([[_e(1, "detected")]], {0: "cho_nguoi"}, "xong", 100, "720x1280") == []
    assert soi_nhanh.chon_khung([], {}, "xong", 100, "720x1280") == []


def test_video_cho_nguoi_lay_ca_khung_goc_o_10_50_90_phan_tram():
    chon = soi_nhanh.chon_khung(None, {}, "cho_nguoi", 300, None)
    assert chon == [{"khung": 30, "ban": "goc", "cat": None}, {"khung": 150, "ban": "goc", "cat": None},
                    {"khung": 270, "ban": "goc", "cat": None}]
    assert soi_nhanh.chon_khung(None, {}, "cho_nguoi", None, None) == []


# ---------------------------------------------------------------- dựng + mốc
def _ffmpeg():
    from tiktok_music_downloader.watermark import find_ffmpeg
    f = find_ffmpeg()
    if f is None:
        pytest.skip("không có ffmpeg")
    return f


def _video(p, so_khung=30, kho=(64, 96)):
    import cv2
    import numpy as np
    p.parent.mkdir(parents=True, exist_ok=True)
    out = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, kho)
    for i in range(so_khung):
        out.write(np.full((kho[1], kho[0], 3), i * 8, np.uint8))  # độ sáng tăng theo khung ⇒ đoán được khung đã trích
    out.release()


def _sang(b):
    import cv2
    import numpy as np
    return float(cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_GRAYSCALE).mean())


def test_dung_anh_dung_khung_cat_dung_vung_va_ghi_moc(tmp_path):
    ff = _ffmpeg()
    _video(khoanh.duong_video(tmp_path, 7, "ra"))
    chon = [{"khung": 2, "ban": "ra", "cat": (0, 0, 32, 48)}, {"khung": 10, "ban": "ra", "cat": (16, 24, 32, 48)},
            {"khung": 20, "ban": "ra", "cat": None}]
    assert soi_nhanh.dung_anh(tmp_path, 7, chon, ff, 30.0) is True
    meta = soi_nhanh.da_co(tmp_path, 7)
    assert [a["khung"] for a in meta["anh"]] == [2, 10, 20]
    d = soi_nhanh.thu_muc(tmp_path, 7)
    for i, mong in enumerate((16, 80, 160)):
        assert abs(_sang((d / f"soi-{i}.jpg").read_bytes()) - mong) < 12
    import cv2
    anh = cv2.imread(str(d / "soi-0.jpg"))
    assert anh.shape[:2] == (soi_nhanh.CAO_ANH, soi_nhanh.RONG_ANH)  # ảnh cắt luôn đúng cỡ lưới
    assert cv2.imread(str(d / "soi-2.jpg")).shape[1] == soi_nhanh.RONG_ANH  # ảnh cả khung: rộng cố định, giữ tỉ lệ video
    assert not list(d.glob(".*.tam"))


def test_moc_ghi_sau_cung_ffmpeg_truot_anh_thu_hai_thi_khong_co_moc(tmp_path):
    ff = _ffmpeg()
    _video(khoanh.duong_video(tmp_path, 7, "ra"))
    chon = [{"khung": 2, "ban": "ra", "cat": None}, {"khung": 10, "ban": "goc", "cat": None},  # goc.mp4 không có
            {"khung": 20, "ban": "ra", "cat": None}]
    assert soi_nhanh.dung_anh(tmp_path, 7, chon, ff, 30.0) is False
    d = soi_nhanh.thu_muc(tmp_path, 7)
    assert (d / "soi-0.jpg").exists() and not (d / soi_nhanh.TEN_MOC).exists()
    assert soi_nhanh.da_co(tmp_path, 7) is None


def test_moc_con_ma_mat_mot_anh_thi_coi_nhu_chua_co(tmp_path):
    ff = _ffmpeg()
    _video(khoanh.duong_video(tmp_path, 7, "ra"))
    chon = [{"khung": k, "ban": "ra", "cat": None} for k in (1, 2, 3)]
    assert soi_nhanh.dung_anh(tmp_path, 7, chon, ff, 30.0)
    (soi_nhanh.thu_muc(tmp_path, 7) / "soi-1.jpg").unlink()
    assert soi_nhanh.da_co(tmp_path, 7) is None


def test_qua_tran_thoi_gian_thi_bo_khong_ghi_moc(tmp_path, monkeypatch):
    ff = _ffmpeg()
    _video(khoanh.duong_video(tmp_path, 7, "ra"))
    monkeypatch.setattr(soi_nhanh, "TRAN_GIAY_DUNG", 0)
    chon = [{"khung": k, "ban": "ra", "cat": None} for k in (1, 2, 3)]
    assert soi_nhanh.dung_anh(tmp_path, 7, chon, ff, 30.0) is False
    assert soi_nhanh.da_co(tmp_path, 7) is None


def test_khong_du_ba_khung_thi_khong_dung(tmp_path):
    assert soi_nhanh.dung_anh(tmp_path, 7, [], "ffmpeg", 30.0) is False


# ---------------------------------------------------------------- route
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from test_thay_logo_khoanh import _h, _job, ctx  # noqa: E402,F401  (fixture route dùng chung)


def test_route_soi_dung_luoi_mot_lan_roi_tra_anh(ctx, monkeypatch):
    _ffmpeg()
    c, db, tmp = ctx
    vid, log_id = _job(db, tmp)  # track: box máy đè khung 9 và 11 ⇒ chọn [9, 11, 11]
    _video(khoanh.duong_video(tmp, log_id, "goc"), so_khung=30, kho=(720, 1280))
    _video(khoanh.duong_video(tmp, log_id, "ra"), so_khung=30, kho=(720, 1280))
    goi = []
    that = soi_nhanh.dung_cho_video
    monkeypatch.setattr(soi_nhanh, "dung_cho_video", lambda *a, **k: goi.append(1) or that(*a, **k))
    r = c.get(f"/api/thay-logo/videos/{vid}/soi", headers=_h("a@x")).json()
    assert r["co"] is True and [a["khung"] for a in r["anh"]] == [9, 11, 11]
    assert c.get(f"/api/thay-logo/videos/{vid}/soi", headers=_h("a@x")).json()["co"] is True
    assert len(goi) == 1  # lần hai đọc mốc, không dựng lại
    a = c.get(f"/api/thay-logo/videos/{vid}/soi/2", headers=_h("a@x"))
    assert a.status_code == 200 and a.content[:2] == b"\xff\xd8"
    assert c.get(f"/api/thay-logo/videos/{vid}/soi/2", headers=_h("b@x")).status_code == 403
    assert c.get(f"/api/thay-logo/videos/{vid}/soi/3", headers=_h("a@x")).status_code == 422


def test_route_soi_hai_request_cung_luc_chi_dung_mot_lan(ctx, monkeypatch):
    c, db, tmp = ctx
    vid, log_id = _job(db, tmp)
    khoanh.duong_video(tmp, log_id, "goc").parent.mkdir(parents=True)
    khoanh.duong_video(tmp, log_id, "goc").write_bytes(b"x")
    vao, tha, goi = threading.Event(), threading.Event(), []

    def gia(conn, data, video_log_id, trang_thai, ffmpeg):  # dựng giả: ghi đủ 3 ảnh + mốc, chậm để hai request chồng nhau
        goi.append(1)
        vao.set()
        tha.wait(5)
        d = soi_nhanh.thu_muc(data, video_log_id)
        for i in range(3):
            (d / f"soi-{i}.jpg").write_bytes(b"\xff\xd8")
        (d / soi_nhanh.TEN_MOC).write_text(json.dumps({"anh": [{"i": i, "khung": i, "ban": "ra", "cat": None} for i in range(3)]}))
        return True
    monkeypatch.setattr(soi_nhanh, "dung_cho_video", gia)
    kq = []
    ts = [threading.Thread(target=lambda: kq.append(c.get(f"/api/thay-logo/videos/{vid}/soi", headers=_h("a@x")).json()))
          for _ in range(2)]
    ts[0].start()
    assert vao.wait(5)
    ts[1].start()
    time.sleep(0.5)  # request 2 tới điểm dựng TRONG LÚC request 1 còn dựng — thả sớm thì request 2 thấy mốc, test không phân định khoá
    tha.set()
    for t in ts:
        t.join(10)
    assert len(goi) == 1 and [r["co"] for r in kq] == [True, True]


def test_route_soi_video_da_don_hoac_chua_xong_tra_co_false(ctx):
    c, db, tmp = ctx
    vid, _ = _job(db, tmp)
    assert c.get(f"/api/thay-logo/videos/{vid}/soi", headers=_h("a@x")).json() == {"co": False, "anh": []}
    assert c.get(f"/api/thay-logo/videos/{vid}/soi/0", headers=_h("a@x")).status_code == 404
    vid2, _ = _job(db, tmp, trang_thai="dang_chay")
    assert c.get(f"/api/thay-logo/videos/{vid2}/soi", headers=_h("a@x")).json() == {"co": False, "anh": []}


def test_dung_cho_video_doc_track_that_cua_nhat_ky(tmp_path):
    ff = _ffmpeg()
    from tiktok_music_downloader.thay_logo import nhat_ky
    conn = nhat_ky.mo(tmp_path / "tl.db")
    log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
    tp = tmp_path / "t.json.gz"
    with gzip.open(tp, "wt") as f:
        json.dump([[_e(3, "detected", x=10, y=20, w=20, h=10), _e(6, "detected", x=10, y=20, w=20, h=10),
                    _e(9, "filled", x=10, y=20, w=20, h=10)]], f)
    conn.execute("UPDATE tl_video SET kho='64x96', fps=30, so_khung=30, duong_dan_track=? WHERE id=?", (str(tp), log_id))
    conn.execute("INSERT INTO tl_vet (video_id, vet, trang_thai) VALUES (?, 0, 'render')", (log_id,))
    conn.commit()
    _video(khoanh.duong_video(tmp_path, log_id, "ra"))
    assert soi_nhanh.dung_cho_video(conn, tmp_path, log_id, "xong", ff) is True
    assert [a["khung"] for a in soi_nhanh.da_co(tmp_path, log_id)["anh"]] == [3, 6, 9]
