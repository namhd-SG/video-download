"""Bộ đề hồi quy thay logo (scripts/bo_de_thay_logo.py): luật lên 3 vế, đối chứng md5, mẫu soi, chia giữ kín, đọc một lượt chạy."""
import gzip
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

P = Path(__file__).resolve().parent.parent / "scripts" / "bo_de_thay_logo.py"
_spec = importlib.util.spec_from_file_location("bo_de_thay_logo", P)
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)


def vd(de: dict, tt="render", md5="m"):
    return {"tt": tt, "md5": md5, "de": de, "trung": 0}


def luot(**videos):
    return {int(k[1:]): v for k, v in videos.items()}


NHAN_DUNG = [{"v": 1, "frame": 10, "loai": "dung", "box": [100, 200, 50, 20]}]


def test_moc_vs_chinh_no_khong_khac_va_chua_len_vi_khong_sua_ca_nao():
    m = luot(v1=vd({10: (100, 200, 50, 20)}), v2=vd({}, tt="cho_nguoi", md5=""))
    kq = bd.so_sanh(m, m, NHAN_DUNG, None)
    assert kq["video_doi"] == [] and kq["vi_pham"] == [] and kq["rc"] == 2 and "không ca lỗi" in kq["ket"]


@pytest.mark.parametrize("box, vi_pham", [((103, 197, 47, 23), False), ((104, 200, 50, 20), True), ((100, 200, 46, 20), True),
                                         (None, True)])
def test_a_nhan_dung_ho_mep_qua_3px_hoac_mat_de_la_vi_pham(box, vi_pham):
    m = luot(v1=vd({10: (100, 200, 50, 20)}))
    n = luot(v1=vd({10: box} if box else {}, md5="khac"))
    kq = bd.so_sanh(m, n, NHAN_DUNG, None)
    assert any(x.startswith("(a)") for x in kq["vi_pham"]) is vi_pham
    if vi_pham:
        assert kq["rc"] == 1


def test_b_khong_duoc_de_ca_video_va_mot_khung():
    nhan = [{"v": 2, "frame": None, "loai": "khong_duoc_de"}, {"v": 3, "frame": 7, "loai": "khong_duoc_de"}]
    m = luot(v2=vd({}, tt="cho_nguoi", md5=""), v3=vd({6: (1, 1, 9, 9)}))
    assert bd.so_sanh(m, m, nhan, None)["vi_pham"] == []
    n = luot(v2=vd({5: (1, 1, 9, 9)}, md5="x"), v3=vd({6: (1, 1, 9, 9), 7: (1, 1, 9, 9)}, md5="y"))
    kq = bd.so_sanh(m, n, nhan, None)
    assert [x[:6] for x in kq["vi_pham"]] == ["(b) v2", "(b) v3"] and kq["rc"] == 1


def test_doi_chung_md5_video_khong_doi_khung_ma_ban_ra_khac_la_vi_pham():
    m = luot(v1=vd({10: (100, 200, 50, 20)}, md5="a"))
    n = luot(v1=vd({10: (100, 200, 50, 20)}, md5="b"))
    kq = bd.so_sanh(m, n, NHAN_DUNG, None)
    assert kq["md5_lech"] == [1] and kq["rc"] == 1


def test_c_khung_khong_nhan_doi_thi_cho_soi_roi_len_khi_soi_du_va_co_ca_sua():
    nhan = NHAN_DUNG + [{"v": 1, "frame": 30, "loai": "lo_mep", "box_dung": [300, 300, 40, 10]}]
    m = luot(v1=vd({10: (100, 200, 50, 20), 30: (290, 300, 40, 10)}, md5="a"))
    n = luot(v1=vd({10: (100, 200, 50, 20), 20: (5, 5, 9, 9), 30: (300, 301, 40, 10)}, md5="b"))
    kq = bd.so_sanh(m, n, nhan, None)
    assert kq["rc"] == 2 and kq["mau"] == [{"v": 1, "frame": 20, "kieu": "them_de"}] and kq["sua"] == ["v1#30 lo_mep"]
    assert bd.so_sanh(m, n, nhan, {"mau": [{"v": 1, "frame": 20, "ket_qua": "dung"}]})["rc"] == 0
    kq_sai = bd.so_sanh(m, n, nhan, {"mau": [{"v": 1, "frame": 20, "ket_qua": "sai"}]})
    assert kq_sai["rc"] == 1 and "SAI" in kq_sai["vi_pham"][0]


def test_ca_loi_khong_co_box_dung_chi_nguoi_soi_xac_nhan_sua():
    nhan = [{"v": 1, "frame": 30, "loai": "lo_mep", "box_dung": None}]
    m = luot(v1=vd({30: (290, 300, 40, 10)}, md5="a"))
    n = luot(v1=vd({30: (296, 300, 46, 10)}, md5="b"))
    kq = bd.so_sanh(m, n, nhan, None)
    assert kq["sua"] == [] and {"v": 1, "frame": 30, "kieu": "ca_loi:lo_mep"} in kq["mau"] and kq["rc"] == 2
    assert bd.so_sanh(m, n, nhan, {"mau": [{"v": 1, "frame": 30, "ket_qua": "sua"}]})["rc"] == 0


def test_mau_soi_rai_deu_video_va_co_dinh_theo_hat():
    doi = {v: [(f, "them_de") for f in range(100)] for v in (1, 2, 3)}
    a = bd.chon_mau(doi, set())
    assert len(a) == bd.SO_MAU_SOI and a == bd.chon_mau(doi, set())
    dem = {v: sum(1 for x in a if x["v"] == v) for v in (1, 2, 3)}
    assert max(dem.values()) - min(dem.values()) <= 1


def test_chia_giu_kin_tai_lap_dung_tep_bo_de_va_giu_nguyen_nhom_bien_the():
    bo = json.loads(bd.BO_DE.read_text())
    gk = bd.chia_giu_kin(bo["don_vi"], bo["so_giu_kin"], bo["hat_chia"])
    assert gk == sorted(x["v"] for x in bo["video"] if x["phia"] == "giu_kin")
    assert sorted(x["v"] for x in bo["video"]) == list(range(1, 41))
    for u in bo["don_vi"]:
        assert len({x["phia"] for x in bo["video"] if x["v"] in u["v"]}) == 1  # nhóm biến thể không bị tách đôi
        if u.get("co_dinh"):
            assert all(x["phia"] == "thiet_ke" for x in bo["video"] if x["v"] in u["v"])
    hieu = [u["thuong_hieu"] for u in bo["don_vi"] if set(u["v"]) <= set(gk)]
    assert len(hieu) == len(set(hieu))


def test_tep_nhan_hop_le():
    nhan = json.loads(bd.KHUNG_VANG.read_text())["nhan"]
    assert sum(1 for x in nhan if x["loai"] == "dung") == 40
    for x in nhan:
        assert x["loai"] in ("dung", "khong_duoc_de", *bd.LOAI_LOI)
        assert x["loai"] != "dung" or len(x["box"]) == 4


def _ghi_video(d: Path, vet: list[tuple[str, list[dict]]], tt="render", md5=True, vid=1):
    (d / f"files/{vid}").mkdir(parents=True)
    (d / "kq.json").write_text(json.dumps({"rc": 0, "kq": {"video_log_id": vid, "trang_thai": tt}}))
    with gzip.open(d / f"files/{vid}/track.json.gz", "wt") as f:
        json.dump([t for _, t in vet], f)
    with sqlite3.connect(d / "log.db") as c:
        c.execute("CREATE TABLE tl_vet (video_id INTEGER, vet INTEGER, trang_thai TEXT)")
        c.executemany("INSERT INTO tl_vet VALUES (?, ?, ?)", [(vid, k, s) for k, (s, _) in enumerate(vet)])
    if md5:
        (d / "md5").write_text("abc\n")


def test_doc_video_chi_tinh_khung_detected_filled_cua_vet_render(tmp_path):
    e = lambda f, s: {"frame": f, "state": s, "x": f, "y": 1, "w": 2, "h": 3}  # noqa: E731
    _ghi_video(tmp_path / "1", [("render", [e(1, "detected"), e(2, "filled"), e(3, "hidden_net")]),
                                ("cho_nguoi", [e(4, "detected")])])
    r = bd.doc_video(tmp_path / "1")
    assert r == {"tt": "render", "md5": "abc", "de": {1: (1, 1, 2, 3), 2: (2, 1, 2, 3)}, "trung": 0}


def test_doc_video_luot_hong_khong_ket_luan(tmp_path):
    with pytest.raises(bd.LuotHong):
        bd.doc_video(tmp_path / "khong-co")
    (tmp_path / "2").mkdir()
    (tmp_path / "2/kq.json").write_text(json.dumps({"rc": 1, "kq": None}))
    with pytest.raises(bd.LuotHong):
        bd.doc_video(tmp_path / "2")
    _ghi_video(tmp_path / "3", [("render", [{"frame": 1, "state": "detected", "x": 0, "y": 0, "w": 1, "h": 1}])], md5=False)
    with pytest.raises(bd.LuotHong, match="thiếu md5"):
        bd.doc_video(tmp_path / "3")


def test_a_nhan_dung_noi_rong_van_bao_tron_thi_cho_soi_khong_phat():
    m = luot(v1=vd({10: (100, 200, 50, 20)}, md5="a"))
    n = luot(v1=vd({10: (98, 199, 60, 24)}, md5="b"))  # rộng thêm 10 px, vẫn bao trọn box nhãn
    kq = bd.so_sanh(m, n, NHAN_DUNG, None)
    assert kq["vi_pham"] == [] and kq["rc"] == 2 and {"v": 1, "frame": 10, "kieu": "nhan_dung_noi_rong"} in kq["mau"]


def test_md5_doi_khi_box_dich_trong_nguong_khong_phai_vi_pham():
    m = luot(v1=vd({10: (100, 200, 50, 20)}, md5="a"))
    n = luot(v1=vd({10: (102, 200, 50, 20)}, md5="b"))  # dịch 2 px ≤ LECH_PX: không "khung đổi" nhưng bản ra khác là đúng
    kq = bd.so_sanh(m, n, NHAN_DUNG, None)
    assert kq["md5_lech"] == [] and kq["vi_pham"] == []


def test_ca_loi_bo_de_la_vi_pham_ke_ca_khi_nguoi_ghi_sua():
    nhan = [{"v": 1, "frame": 30, "loai": "lo_mep", "box_dung": None}]
    m = luot(v1=vd({30: (290, 300, 40, 10)}, md5="a"))
    n = luot(v1=vd({}, md5="b"))
    kq = bd.so_sanh(m, n, nhan, {"mau": [{"v": 1, "frame": 30, "ket_qua": "sua"}]})
    assert kq["rc"] == 1 and "BỎ ĐÈ" in kq["vi_pham"][0] and kq["sua"] == []


def test_sua_chi_tinh_tren_mau_cua_ca_loi():
    m = luot(v1=vd({10: (100, 200, 50, 20)}, md5="a"))
    n = luot(v1=vd({10: (100, 200, 50, 20), 20: (5, 5, 9, 9)}, md5="b"))
    kq = bd.so_sanh(m, n, NHAN_DUNG, {"mau": [{"v": 1, "frame": 20, "ket_qua": "sua"}]})
    assert kq["sua"] == [] and kq["rc"] == 2


def test_doc_video_doc_dung_video_log_id_khi_log_db_co_hai_lan(tmp_path):
    e = {"frame": 1, "state": "detected", "x": 7, "y": 1, "w": 2, "h": 3}
    _ghi_video(tmp_path / "1", [("render", [e])], vid=2)
    with sqlite3.connect(tmp_path / "1/log.db") as c:  # dòng của lần chạy bị cắt trước đó
        c.execute("INSERT INTO tl_vet VALUES (1, 0, 'render')")
        c.execute("INSERT INTO tl_vet VALUES (1, 1, 'render')")
    assert bd.doc_video(tmp_path / "1")["de"] == {1: (7, 1, 2, 3)}


@pytest.mark.parametrize("noi_dung", ['{"v":1,"rc":0,"kq":}', '{"rc":0,"kq":{"trang_thai":"render"}}'])
def test_doc_video_du_lieu_hong_la_luot_hong_khong_phai_vi_pham(tmp_path, noi_dung):
    (tmp_path / "1").mkdir()
    (tmp_path / "1/kq.json").write_text(noi_dung)
    with pytest.raises(bd.LuotHong):
        bd.doc_video(tmp_path / "1")


@pytest.mark.parametrize("box, ket", [((97, 200, 56, 20), "cho_soi"), ((103, 200, 50, 20), "qua")])
def test_a_dich_roi_noi_rong_van_cho_soi_dich_dung_dung_sai_thi_qua(box, ket):
    m = luot(v1=vd({10: (100, 200, 50, 20)}, md5="a"))
    kq = bd.so_sanh(m, luot(v1=vd({10: box}, md5="b")), NHAN_DUNG, None)
    assert kq["vi_pham"] == []
    assert ({"v": 1, "frame": 10, "kieu": "nhan_dung_noi_rong"} in kq["mau"]) is (ket == "cho_soi")
