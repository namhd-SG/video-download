"""Nhật ký thay logo: ghi đủ để tune, đánh giá member có kiểm, dọn file đúng chính sách (tuổi, trần, giữ video hỏng)."""
import time

import pytest

from tiktok_music_downloader.thay_logo import nhat_ky


@pytest.fixture
def conn(tmp_path):
    c = nhat_ky.mo(tmp_path / "log.db")
    yield c
    c.close()


def _video(conn, tmp_path, tuoi_ngay=0.0, byte=10, nguon="v"):
    vid = nhat_ky.bat_dau_video(conn, nguon_video=nguon)
    conn.execute("UPDATE tl_video SET bat_dau=? WHERE id=?", (time.time() - tuoi_ngay * 86400, vid))
    d = tmp_path / "f" / str(vid)
    d.mkdir(parents=True)
    (d / "track.json.gz").write_bytes(b"x" * byte)
    nhat_ky.cap_nhat_video(conn, vid, duong_dan_track=str(d / "track.json.gz"))
    return vid


def test_mo_hai_lan_khong_loi_va_giu_du_lieu(tmp_path):
    c = nhat_ky.mo(tmp_path / "log.db")
    vid = nhat_ky.bat_dau_video(c, nguon_video="drive:abc", job_id=7)
    c.close()
    c = nhat_ky.mo(tmp_path / "log.db")
    r = c.execute("SELECT job_id, nguon_video, phien_ban FROM tl_video WHERE id=?", (vid,)).fetchone()
    assert (r["job_id"], r["nguon_video"]) == (7, "drive:abc") and len(r["phien_ban"]) == 12


def test_phien_ban_doi_khi_ma_nguon_doi(monkeypatch, tmp_path):
    a = nhat_ky.phien_ban_thuat_toan()
    (tmp_path / "x.py").write_text("K = 1")
    monkeypatch.setattr(nhat_ky, "__file__", str(tmp_path / "nhat_ky.py"))
    assert nhat_ky.phien_ban_thuat_toan() != a


def test_danh_gia_hong_bat_buoc_loai_loi(conn):
    vid = nhat_ky.bat_dau_video(conn, nguon_video="v")
    with pytest.raises(ValueError):
        nhat_ky.ghi_danh_gia(conn, vid, "a@x", "hong")
    with pytest.raises(ValueError):
        nhat_ky.ghi_danh_gia(conn, vid, "a@x", "tam_duoc")
    nhat_ky.ghi_danh_gia(conn, vid, "a@x", "hong", "che_phu_de", "đè phụ đề giây 3")
    nhat_ky.ghi_danh_gia(conn, vid, "b@x", "dat")
    hang = conn.execute("SELECT member, ket_qua, loai_loi FROM tl_danh_gia ORDER BY luc").fetchall()
    assert [tuple(r) for r in hang] == [("a@x", "hong", "che_phu_de"), ("b@x", "dat", None)]


def test_ghi_vet_tinh_so_tu_track():
    pytest.importorskip("cv2", reason="KetQuaVet nằm trong module dùng opencv")
    from tiktok_music_downloader.thay_logo.duong_ong import KetQuaVet
    conn = nhat_ky.mo(":memory:")
    track = [{"frame": 0, "state": "detected", "diem_tot": 0.9, "loc_pd": 0},
             {"frame": 1, "state": "hidden_ring", "diem_tot": 0.8, "loc_pd": 1},
             {"frame": 2, "state": "hidden", "diem_tot": 0.2, "loc_pd": 2},
             {"frame": 3, "state": "predicted", "diem_tot": 0.5, "loc_pd": 0}]
    v = KetQuaVet("render", 6, 0.8, track, [track[0]], {"khop": 4, "lech": 0, "track_vang": 2, "qua_cong": True})
    conn.execute("INSERT INTO tl_video (id, nguon_video, phien_ban, bat_dau) VALUES (1, 'v', 'p', 0)")
    nhat_ky.ghi_vet(conn, 1, 0, v)
    r = dict(conn.execute("SELECT * FROM tl_vet").fetchone())
    assert (r["so_khung"], r["so_chac"], r["so_render"], r["chan_vanh"], r["so_predicted"], r["so_hidden"]) == (4, 1, 1, 1, 1, 1)
    assert (r["khop"], r["lech"], r["khung_loc_phu_de"]) == (4, 0, 2)
    assert r["diem_c_p50"] == 0.8 and r["diem_c_p90"] == 0.9


def test_don_dep_theo_tuoi_giu_video_hong_lau_hon(conn, tmp_path):
    cu = _video(conn, tmp_path, tuoi_ngay=61)
    cu_hong = _video(conn, tmp_path, tuoi_ngay=61)
    nhat_ky.ghi_danh_gia(conn, cu_hong, "a@x", "hong", "sai_cho")
    moi = _video(conn, tmp_path, tuoi_ngay=1)
    kq = nhat_ky.don_dep(conn, tmp_path / "f")
    assert kq["xoa"] == 1
    assert not (tmp_path / "f" / str(cu)).exists()
    assert (tmp_path / "f" / str(cu_hong)).exists() and (tmp_path / "f" / str(moi)).exists()
    assert conn.execute("SELECT duong_dan_track FROM tl_video WHERE id=?", (cu,)).fetchone()[0] is None
    assert conn.execute("SELECT count(*) FROM tl_video").fetchone()[0] == 3  # hàng DB không bao giờ xoá


def test_don_dep_theo_tran_xoa_cu_nhat_truoc_va_hong_sau_cung(conn, tmp_path):
    a_hong = _video(conn, tmp_path, tuoi_ngay=5, byte=100)
    nhat_ky.ghi_danh_gia(conn, a_hong, "a@x", "hong", "khac")
    b = _video(conn, tmp_path, tuoi_ngay=4, byte=100)
    c = _video(conn, tmp_path, tuoi_ngay=3, byte=100)
    kq = nhat_ky.don_dep(conn, tmp_path / "f", tran_byte=150)
    assert kq == {"xoa": 2, "byte_con_lai": 100}
    assert (tmp_path / "f" / str(a_hong)).exists()
    assert not (tmp_path / "f" / str(b)).exists() and not (tmp_path / "f" / str(c)).exists()


def test_danh_gia_lai_dat_thi_het_uu_tien_hong(conn, tmp_path):
    vid = _video(conn, tmp_path, tuoi_ngay=61)
    nhat_ky.ghi_danh_gia(conn, vid, "a@x", "hong", "sai_cho")
    time.sleep(0.01)
    nhat_ky.ghi_danh_gia(conn, vid, "a@x", "dat")
    assert nhat_ky.don_dep(conn, tmp_path / "f")["xoa"] == 1
