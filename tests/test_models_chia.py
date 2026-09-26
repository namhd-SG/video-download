"""Tự chia cụm theo lượt — `web/models_chia.py`: DDL, nháp, nhật ký, đường
duyệt duy nhất sang cụm thật.

Gọi thẳng các hàm model, cùng khuôn `tests/test_web_cum.py`.
"""
from __future__ import annotations

import sqlite3

import pytest

from web import models, models_chia, models_cum

TOI = "toi@astronex.ai"
HO = "ho@astronex.ai"


@pytest.fixture
def kho(tmp_path):
    """Job của TOI với 6 video `1`..`6`."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 6, TOI)
    for vid in ("1", "2", "3", "4", "5", "6"):
        models.record_video(db, job_id=job, video_id=vid, url=f"u{vid}")
    return db, job


def _de_xuat_2_kieu(db, job, chu=TOI, a=("1", "2"), b=("3", "4"),
                    huong_dan=None, nghi=None):
    """Một lượt chia với 2 kiểu: "couple" (a) và "cartoon" (b)."""
    lan_id = models_chia.tao_chia_lan(db, job, chu, "p1")
    models_chia.ghi_de_xuat(db, lan_id, chu, [
        {"nhom": "trang phục", "kieu": [
            {"kieu": "couple", "video_ids": list(a)},
            {"kieu": "cartoon", "video_ids": list(b)},
        ]},
    ], huong_dan=huong_dan, nghi=nghi)
    return lan_id


def _nhom_id(db, lan_id, kieu, chu=TOI):
    chia = models_chia.lay_chia(db, lan_id, chu)
    return next(k["cum_nhap_id"] for k in chia["kieu"] if k["kieu"] == kieu)


def _dem(db, bang) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {bang}").fetchone()[0]


def _thao_tac(db, lan_id) -> list[dict]:
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM thao_tac_duyet WHERE chia_lan_id = ? ORDER BY id", (lan_id,))]


# --- DDL --------------------------------------------------------------------

def test_init_db_creates_tables_and_columns(kho):
    db, _ = kho
    with sqlite3.connect(db) as conn:
        bang = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"chia_lan", "cum_nhap", "video_cum_nhap", "video_dac_diem",
                "thao_tac_duyet"} <= bang
        cot = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        assert {"usecase", "insight_goc"} <= cot
    models.init_db(db)   # idempotent
    models.init_db(db)


# --- tao_chia_lan khởi tạo từ jobs -------------------------------------------

def test_tao_chia_lan_khoi_tao_usecase_tu_jobs(kho):
    db, job = kho
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET usecase = ?, insight_goc = ? WHERE id = ?",
                    ("Dance", "Badaboum", job))
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert (chia["usecase"], chia["insight_goc"]) == ("Dance", "Badaboum")


def test_tao_chia_lan_rong_khi_job_chua_co_insight(kho):
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["usecase"] is None and chia["insight_goc"] is None
    assert chia["trang_thai"] == "cho_hinh"


# --- quyền sở hữu -------------------------------------------------------------

def test_someone_else_cannot_read_or_write_my_lan(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    assert models_chia.lay_chia(db, lan_id, HO) is None
    assert models_chia.ghi_de_xuat(db, lan_id, HO, []) is None
    assert models_chia.ap_thao_tac(db, lan_id, HO, "chap_nhan",
                                   cum_nhap_id=_nhom_id(db, lan_id, "couple")) is None
    assert models_chia.duyet_kieu(db, lan_id, _nhom_id(db, lan_id, "couple"), HO, None,
                                  "Dance", "Badaboum") is None
    assert models_chia.duyet_het(db, lan_id, HO, None, "Dance", "Badaboum") is None


def test_lay_chia_theo_job_is_scoped_to_owner(kho):
    db, job = kho
    _de_xuat_2_kieu(db, job)
    assert models_chia.lay_chia_theo_job(db, job, HO) is None
    assert models_chia.lay_chia_theo_job(db, job, TOI) is not None


# --- một video một chỗ trong một lượt ----------------------------------------

def test_mot_video_mot_cho_trong_mot_luot(kho):
    """Video liệt ở HAI kiểu trong CÙNG một `ghi_de_xuat` ⇒ nhóm liệt SAU
    thắng, không có hai hàng."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [
            {"kieu": "couple", "video_ids": ["1", "2"]},
            {"kieu": "cartoon", "video_ids": ["2", "3"]},   # "2" trùng
        ]},
    ])
    with sqlite3.connect(db) as conn:
        hang = conn.execute(
            "SELECT COUNT(*) FROM video_cum_nhap WHERE chia_lan_id = ? AND video_id = '2'",
            (lan_id,)).fetchone()[0]
    assert hang == 1
    chia = models_chia.lay_chia(db, lan_id, TOI)
    kieu_cua_2 = next(k["kieu"] for k in chia["kieu"] if "2" in k["video_ids"])
    assert kieu_cua_2 == "cartoon"


def test_ghi_de_xuat_thay_toan_bo_nhap_cu(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "moi", "video_ids": ["5"]}]},
    ])
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["kieu"] for k in chia["kieu"]] == ["moi"]
    assert chia["kieu"][0]["video_ids"] == ["5"]


def test_ghi_de_xuat_tu_choi_khi_da_duyet(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1",), b=("2",))
    models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "da_duyet"
    with pytest.raises(ValueError):
        models_chia.ghi_de_xuat(db, lan_id, TOI, [
            {"nhom": "n", "kieu": [{"kieu": "x", "video_ids": ["3"]}]},
        ])


def test_ghi_de_xuat_huong_dan_va_nghi(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1",), b=("2",),
                             huong_dan=["3"], nghi=["4"])
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["huong_dan"] == ["3"] and chia["nghi"] == ["4"]


# --- ghi_de_xuat lọc video đã ở cụm thật khỏi đề xuất mới ---------------------

def test_ghi_de_xuat_loc_video_da_o_cum_that(kho):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "cu")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1"])

    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    ket = models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "couple", "video_ids": ["1", "2"]}]},
    ])
    assert ket["da_o_cum"] == ["1"]
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["kieu"][0]["video_ids"] == ["2"]


# --- duyệt: lối duy nhất từ nháp sang cum thật, tương đương tao_cum + gan_video

def test_duyet_kieu_tao_cum_that_va_chuyen_video(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    assert sorted(ket["gan"]) == ["1", "2"] and ket["da_co"] is False
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        cum = conn.execute("SELECT * FROM cum WHERE id = ?", (ket["cum_id"],)).fetchone()
        assert (cum["usecase"], cum["insight_goc"], cum["kieu"]) == ("Dance", "Badaboum", "couple")
        vc = {r["video_id"] for r in conn.execute(
            "SELECT video_id FROM video_cum WHERE cum_id = ?", (ket["cum_id"],))}
        assert vc == {"1", "2"}
    # Kiểu đã duyệt biến khỏi nháp; kiểu kia vẫn còn.
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["kieu"] for k in chia["kieu"]] == ["cartoon"]
    assert chia["trang_thai"] == "de_xuat"


def test_duyet_trung_ten_dung_lai_cum_co_san_khi_da_xac_nhan(kho):
    db, job = kho
    cu_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")

    # Trùng tên, CHƯA xác nhận ⇒ không gộp, nhóm còn nguyên trong nháp.
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    assert ket["trung_cum_co_san"] == [
        {"cum_nhap_id": couple_id, "cum_id": cu_id, "ten": "Badaboum couple", "so_video": 2}]
    assert _dem(db, "cum") == 1
    assert models_chia.lay_chia(db, lan_id, TOI)["kieu"]  # nhóm còn đó
    # Trùng chưa xác nhận ⇒ KHÔNG ghi `duyet_het` — chỉ có dòng `doi_insight`
    # (lượt chưa có usecase/insight, body vừa truyền vào).
    assert [h["loai"] for h in _thao_tac(db, lan_id)] == ["doi_insight"]

    # Xác nhận ⇒ gộp vào cụm có sẵn, không tạo thêm cụm.
    ket2 = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum",
                                  xac_nhan_gop=[cu_id])
    assert ket2["cum_id"] == cu_id and ket2["da_co"] is True
    assert _dem(db, "cum") == 1
    with sqlite3.connect(db) as conn:
        vc = {r[0] for r in conn.execute("SELECT video_id FROM video_cum WHERE cum_id = ?",
                                         (cu_id,))}
    assert vc == {"1", "2"}


def test_hai_nhap_song_song_video_khong_bi_chuyen_lan_hai(kho):
    """Hai lượt chia CÙNG chứa video "1". Duyệt lượt 1 trước ⇒ video vào cụm
    của lượt 1. Duyệt lượt 2 sau ⇒ "1" phải Ở NGUYÊN cụm của lượt 1, được
    báo lại ở `da_o_cum`, KHÔNG bị kéo sang cụm của lượt 2."""
    db, job = kho
    lan1 = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("9",))
    lan2 = _de_xuat_2_kieu(db, job, a=("1", "3"), b=("9",))
    k1, k2 = _nhom_id(db, lan1, "couple"), _nhom_id(db, lan2, "couple")

    ket1 = models_chia.duyet_kieu(db, lan1, k1, TOI, None, "Dance", "A")
    ket2 = models_chia.duyet_kieu(db, lan2, k2, TOI, None, "Dance", "B")

    assert sorted(ket1["gan"]) == ["1", "2"]
    assert ket2["gan"] == ["3"] and ket2["da_o_cum"] == ["1"]
    with sqlite3.connect(db) as conn:
        cum_cua_1 = conn.execute(
            "SELECT cum_id FROM video_cum WHERE video_id = '1' AND chu = ?", (TOI,)).fetchone()[0]
    assert cum_cua_1 == ket1["cum_id"]


def test_moi_video_da_o_cum_khong_tao_cum_moi_rong(kho):
    """Mọi video của kiểu đã ở cụm thật (do một nháp khác vừa duyệt) ⇒ 0 hàng
    `cum` mới cho kiểu này — không sinh cụm rỗng."""
    db, job = kho
    lan1 = _de_xuat_2_kieu(db, job, a=("1",), b=("9",))
    lan2 = _de_xuat_2_kieu(db, job, a=("1",), b=("8",))
    k1, k2 = _nhom_id(db, lan1, "couple"), _nhom_id(db, lan2, "couple")

    models_chia.duyet_kieu(db, lan1, k1, TOI, None, "Dance", "A")
    truoc = _dem(db, "cum")
    ket2 = models_chia.duyet_kieu(db, lan2, k2, TOI, None, "Dance", "B")

    assert ket2["cum_id"] is None and ket2["gan"] == [] and ket2["da_o_cum"] == ["1"]
    assert _dem(db, "cum") == truoc, "video duy nhất của kiểu đã ở cụm khác ⇒ KHÔNG tạo cụm mới"
    # Kiểu vẫn được coi là đã "giải quyết" — biến khỏi nháp.
    chia = models_chia.lay_chia(db, lan2, TOI)
    assert "couple" not in [k["kieu"] for k in chia["kieu"]]


def test_duyet_het_xu_ly_nhieu_kieu_mot_transaction_mot_dong_nhat_ky(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert len(ket["cum"]) == 2 and ket["trung_cum_co_san"] == []
    assert _dem(db, "cum") == 2
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["kieu"] == [] and chia["trang_thai"] == "da_duyet" and chia["duyet_luc"]
    # Lượt chưa có usecase/insight nào ⇒ truyền trong body ghi thêm MỘT dòng
    # `doi_insight` trước dòng `duyet_het` — hai cú "bấm" khác nhau.
    hang = _thao_tac(db, lan_id)
    assert [h["loai"] for h in hang] == ["doi_insight", "duyet_het"]
    assert hang[1]["so_video"] == 4


def test_duyet_het_trung_ten_van_duyet_phan_an_toan(kho):
    db, job = kho
    cu_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    lan_id = _de_xuat_2_kieu(db, job, a=("1",), b=("2",))
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert len(ket["cum"]) == 1 and ket["cum"][0]["gan"] == ["2"]
    assert ket["trung_cum_co_san"] == [
        {"cum_nhap_id": _nhom_id(db, lan_id, "couple"), "cum_id": cu_id,
         "ten": "Badaboum couple", "so_video": 1}]
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["kieu"] for k in chia["kieu"]] == ["couple"]
    assert chia["trang_thai"] == "de_xuat", "còn kiểu chờ xác nhận ⇒ CHƯA da_duyet"


# --- video_de_loai / phạm vi thư viện (chi_cua) khi duyệt ---------------------

def test_duyet_bo_qua_video_da_loai(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("9",))
    models.danh_dau_da_loai(db, "1", TOI)
    ket = models_chia.duyet_kieu(db, lan_id, _nhom_id(db, lan_id, "couple"), TOI, TOI,
                                 "Dance", "Badaboum")
    assert ket["gan"] == ["2"]


# --- ap_thao_tac: nhật ký đủ loại + thao tác trượt ⇒ 0 dòng -------------------

def test_thao_tac_khong_hop_le_bi_tu_choi_khong_ghi_nhat_ky(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten",
                                  cum_nhap_id=999999, kieu="x")
    assert ket == {"tu_choi": "khong_hop_le"}
    assert _thao_tac(db, lan_id) == []


def test_loai_thao_tac_la_tap_dong_10_gia_tri():
    assert models_chia.LOAI_THAO_TAC == (
        "chap_nhan", "duyet_het", "gop", "doi_ten", "chuyen",
        "ngoai_chu_de", "tra_ve", "hoan_tac", "xoa_kieu", "doi_insight")


def test_ap_thao_tac_tu_choi_loai_khong_ro(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    with pytest.raises(ValueError):
        models_chia.ap_thao_tac(db, lan_id, TOI, "an-trom")


def test_ap_thao_tac_tu_choi_duyet_het_qua_duong_nay(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    with pytest.raises(ValueError):
        models_chia.ap_thao_tac(db, lan_id, TOI, "duyet_het")


def test_chap_nhan_ghi_nhat_ky_khong_doi_du_lieu(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"))
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "chap_nhan", cum_nhap_id=couple_id)
    assert ket["so_video"] == 2
    hang = _thao_tac(db, lan_id)
    assert len(hang) == 1 and hang[0]["loai"] == "chap_nhan"
    assert models_chia.lay_chia(db, lan_id, TOI)["kieu"][0]["video_ids"] == ["1", "2"]


def test_doi_ten_doi_nhom_va_kieu(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id,
                            kieu="nhóm nhảy", nhom="phong cách")
    chia = models_chia.lay_chia(db, lan_id, TOI)
    nhom = next(k for k in chia["kieu"] if k["cum_nhap_id"] == couple_id)
    assert (nhom["nhom"], nhom["kieu"]) == ("phong cách", "nhóm nhảy")


def test_gop_chuyen_video_va_xoa_nhom_nguon(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "gop",
                                  tu_cum_nhap_id=couple_id, den_cum_nhap_id=cartoon_id)
    assert ket["so_video"] == 2
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["cum_nhap_id"] for k in chia["kieu"]] == [cartoon_id]
    assert sorted(chia["kieu"][0]["video_ids"]) == ["1", "2", "3"]


def test_ngoai_chu_de_roi_tra_ve(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "ngoai_chu_de", video_ids=["1"])
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["nghi"] == ["1"]
    assert "1" not in next(k["video_ids"] for k in chia["kieu"] if k["cum_nhap_id"] == couple_id)

    models_chia.ap_thao_tac(db, lan_id, TOI, "tra_ve", video_ids=["1"], den_cum_nhap_id=couple_id)
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["nghi"] == []
    assert "1" in next(k["video_ids"] for k in chia["kieu"] if k["cum_nhap_id"] == couple_id)


def test_tra_ve_tu_choi_video_dang_o_mot_kieu(kho):
    """`tra_ve` chỉ nhận video đang ở làn "hướng dẫn"/"nghi" — video đang ở
    MỘT KIỂU thì đó là việc của `chuyen`."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1",), b=("2",))
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "tra_ve", video_ids=["1"],
                                  den_cum_nhap_id=cartoon_id)
    assert ket == {"tu_choi": "khong_hop_le"}


def test_xoa_kieu_dua_video_ve_lan_nghi(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu", cum_nhap_id=couple_id)
    assert ket["so_video"] == 2
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["kieu"] for k in chia["kieu"]] == ["cartoon"]
    assert sorted(chia["nghi"]) == ["1", "2"]


def test_doi_insight_qua_thao_tac_ghi_ca_chia_lan_va_jobs(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_insight",
                            usecase="Dance", insight_goc="Badaboum")
    assert models_chia.lay_chia(db, lan_id, TOI)["usecase"] == "Dance"
    j = models.get_job(db, job)
    assert (j["usecase"], j["insight_goc"]) == ("Dance", "Badaboum")


def test_hoan_tac_gop_khoi_phuc_nhom_nguon(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop",
                            tu_cum_nhap_id=couple_id, den_cum_nhap_id=cartoon_id)
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket["so_video"] == 2
    chia = models_chia.lay_chia(db, lan_id, TOI)
    nhoms = {k["kieu"]: sorted(k["video_ids"]) for k in chia["kieu"]}
    assert nhoms == {"couple": ["1", "2"], "cartoon": ["3"]}


def test_hoan_tac_khong_co_gi_de_lui_thi_tu_choi(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket == {"tu_choi": "khong_hop_le"}


# --- insight ghi ngược vào job để "chia lại" không mất công gõ lại ------------

def test_doi_insight_roi_chia_lai_insight_van_con(kho):
    """`doi_insight` rồi "chia lại" (nháp mới cho CÙNG job) ⇒ insight vẫn
    còn — vì `doi_insight` ghi CẢ `jobs`, và `tao_chia_lan` đọc từ đó."""
    db, job = kho
    lan1 = models_chia.tao_chia_lan(db, job, TOI, "p1")
    # `ap_thao_tac` đòi `trang_thai == 'de_xuat'` — một đề xuất RỖNG cũng đưa
    # lượt vào trạng thái đó mà không cần kiểu nào (nội dung của test này chỉ
    # quan tâm `doi_insight` ghi ngược `jobs`, không quan tâm cấu trúc nháp).
    models_chia.ghi_de_xuat(db, lan1, TOI, [])
    models_chia.ap_thao_tac(db, lan1, TOI, "doi_insight",
                            usecase="Dance", insight_goc="Badaboum")
    lan2 = models_chia.tao_chia_lan(db, job, TOI, "p1")   # "chia lại"
    chia2 = models_chia.lay_chia(db, lan2, TOI)
    assert (chia2["usecase"], chia2["insight_goc"]) == ("Dance", "Badaboum")


def test_duyet_voi_insight_trong_body_ma_chia_lan_con_trong(kho):
    """`duyet` mang insight trong body mà `chia_lan` còn trống ⇒ cụm tạo với
    insight của BODY."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    assert models_chia.lay_chia(db, lan_id, TOI)["usecase"] is None
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        cum = conn.execute("SELECT usecase, insight_goc FROM cum WHERE id = ?",
                          (ket["cum_id"],)).fetchone()
    assert (cum["usecase"], cum["insight_goc"]) == ("Dance", "Badaboum")
    # Giá trị body cũng được ghi lại vào `chia_lan` (và `jobs`) làm mặc định.
    assert models_chia.lay_chia(db, lan_id, TOI)["usecase"] == "Dance"
    assert models.get_job(db, job)["usecase"] == "Dance"


# --- an toàn giao dịch: nhật ký PHẢI cùng transaction với việc nó khẳng định --

def test_duyet_that_bai_sau_khi_ghi_nhat_ky_thi_khong_de_lai_dong_nao(kho, monkeypatch):
    """Ép lỗi NGAY SAU điểm ghi `thao_tac_duyet` (nhưng trước khi `with` block
    đóng) — nếu log CÙNG một transaction với việc tạo cụm/gán video thì lỗi
    này phải cuốn theo TẤT CẢ: 0 cụm mới, 0 video_cum mới, 0 dòng nhật ký.

    Mutation đã đo (`ghi nhật ký NGOÀI transaction`): chèn `conn.execute
    ("COMMIT")` ngay TRƯỚC câu `INSERT INTO thao_tac_duyet` — tách việc tạo
    cụm/gán video khỏi phần còn lại thành MỘT transaction đã chốt riêng. Lỗi
    ép ở đây xảy ra SAU điểm COMMIT đó ⇒ cụm/video_cum đã tạo SỐNG SÓT (1 cụm)
    dù toàn bộ lời gọi `duyet_kieu` coi như thất bại — đúng lớp hỏng-âm-thầm
    mà việc ghi nhật ký CÙNG transaction sinh ra để chặn.
    `assert _dem(db, "cum") == 0` bắt được ngay."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("9",))
    couple_id = _nhom_id(db, lan_id, "couple")

    def no(*a, **kw):
        raise RuntimeError("ép lỗi sau khi ghi nhật ký")

    monkeypatch.setattr(models_chia, "_chia_lan_xong_neu_het_kieu", no)
    with pytest.raises(RuntimeError):
        models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")

    assert _dem(db, "cum") == 0
    assert _dem(db, "video_cum") == 0
    assert _thao_tac(db, lan_id) == []
    # Nháp vẫn nguyên — cũng bị cuốn theo cùng transaction.
    assert models_chia.lay_chia(db, lan_id, TOI)["kieu"]


# --- payload dựng ở server ---------------------------------------------------

def test_xay_payload_lo_chi_gom_video_co_drive_va_dung_thu_tu(kho):
    db, job = kho
    for vid, drive in (("1", "d1"), ("2", None), ("3", "d3")):
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE videos SET drive_file_id = ?, tao_luc = ? WHERE video_id = ?",
                        (drive, f"2026-09-2{vid}T00:00:00+00:00", vid))
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "3"])
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    payload = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert payload["v"] == 1
    assert [i["f"] for i in payload["items"]] == ["d1", "d3"], "video không có drive_file_id bị bỏ"
    assert payload["nhan"] == {"usecase": "Dance", "insight": "Badaboum couple",
                               "template": "Goc", "cum_id": cum_id, "lo": {"thu": 1, "tong": 1}}


def test_xay_payload_lo_bo_video_da_loai_sau_khi_vao_cum(kho):
    """Video bị "loại" SAU khi đã ở cụm vẫn còn hàng `video_cum`, nhưng không
    được sang Creative Desk — cùng bộ lọc mà `lay_cum` đếm, để lô gửi đi khớp
    số video người dùng thấy."""
    db, job = kho
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE videos SET drive_file_id = 'd' || video_id")
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "3"])
    models.danh_dau_da_loai(db, "2", TOI)
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    payload = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert [i["f"] for i in payload["items"]] == ["d1", "d3"]


def test_xay_payload_lo_chi_gom_video_trong_pham_vi_chi_cua(kho):
    """Cụm có cả video thuộc job của người khác (gán khi không giới hạn phạm
    vi) — lô gửi đi dưới phạm vi `chi_cua` chỉ mang video của người đó, cùng
    bộ lọc `lay_cum` dùng để đếm."""
    db, job = kho
    job_ho = models.create_job(db, "https://www.tiktok.com/tag/b", 1, HO)
    models.record_video(db, job_id=job_ho, video_id="h1", url="uh1")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE videos SET drive_file_id = 'd' || video_id")
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, None, ["1", "h1"])
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    payload = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert [i["f"] for i in payload["items"]] == ["d1"]


# --- hoan_tac là NGĂN XẾP -----------------------------------------------

def test_hoan_tac_gop_hai_lan_lien_tiep_undo_hai_lan_khoi_phuc_ca_hai(kho):
    """`hoan_tac` phải chọn ĐÚNG dòng chưa lùi, không lặp lại dòng lần undo
    trước đã lùi — lặp lại dòng đó ra `IntegrityError UNIQUE constraint
    failed: cum_nhap.id` khi thao tác là `gop`. Ở đây gop HAI LẦN (a→b rồi
    b→c) — undo hai lần phải trả cấu trúc về nguyên vẹn ba kiểu tách biệt."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [
            {"kieu": "a", "video_ids": ["1"]},
            {"kieu": "b", "video_ids": ["2"]},
            {"kieu": "c", "video_ids": ["3"]},
        ]},
    ])
    a_id, b_id, c_id = (_nhom_id(db, lan_id, k) for k in ("a", "b", "c"))
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop", tu_cum_nhap_id=a_id, den_cum_nhap_id=b_id)
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop", tu_cum_nhap_id=b_id, den_cum_nhap_id=c_id)
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert {k["kieu"]: sorted(k["video_ids"]) for k in chia["kieu"]} == {"c": ["1", "2", "3"]}

    ket1 = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket1["so_video"] == 2   # gop(b→c) chuyển đúng 2 video ("1","2", đã cộng dồn từ gop trước)
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert {k["kieu"]: sorted(k["video_ids"]) for k in chia["kieu"]} == {
        "b": ["1", "2"], "c": ["3"]}

    ket2 = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket2["so_video"] == 1   # gop(a→b) chỉ chuyển "1"
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert {k["kieu"]: sorted(k["video_ids"]) for k in chia["kieu"]} == {
        "a": ["1"], "b": ["2"], "c": ["3"]}, "phải về ĐÚNG cấu trúc ban đầu, không lệch"

    # Cả hai thao tác lùi được đều đã lùi — hoàn tác lần ba: KHÔNG có gì nữa.
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac") == {"tu_choi": "khong_hop_le"}


def test_hoan_tac_doi_ten_hai_lan_lien_tiep_undo_hai_lan_ve_ten_goc(kho):
    """`a→a2→b`, undo hai lần ⇒ về đúng `a` — undo lần hai phải lùi được cái
    ĐẦU TIÊN, không chọn lại dòng mới nhất mỗi lần."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="a2")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="b")
    ten = lambda: next(k["kieu"] for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]
                       if k["cum_nhap_id"] == couple_id)
    assert ten() == "b"
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ten() == "a2"
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ten() == "couple", "phải về TÊN GỐC, không dừng ở nấc giữa"


# --- chỉ sửa/duyệt được khi lượt đang `de_xuat`, hoan_tac không lùi xuyên
#     thế hệ, `ghi_de_xuat` không hồi sinh lượt `huy` ----------------------------

def test_ap_thao_tac_va_duyet_tu_choi_khi_luot_da_duyet(kho):
    """MỌI `ap_thao_tac`/`duyet_kieu`/`duyet_het` phải từ chối một khi lượt
    không còn `de_xuat` — thiếu chặn này thì gop rồi `duyet_het` (lượt
    thành `da_duyet`) rồi `hoan_tac` hồi sinh một kiểu nháp bên trong một
    lượt đã báo đã duyệt xong."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop", tu_cum_nhap_id=couple_id,
                            den_cum_nhap_id=cartoon_id)
    models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "da_duyet"

    with pytest.raises(ValueError):
        models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    with pytest.raises(ValueError):
        models_chia.duyet_kieu(db, lan_id, 999999, TOI, None, "Dance", "Badaboum")
    with pytest.raises(ValueError):
        models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    # Không có gì bị đổi thêm bởi các lời gọi bị chặn ở trên.
    assert _dem(db, "cum") == 1


def test_hoan_tac_khong_lui_xuyen_the_he_sau_ghi_de_xuat_moi(kho):
    """`the_he` phải chặn việc lùi xuyên thế hệ — thiếu nó thì `xoa_kieu`
    rồi `ghi_de_xuat` một đề xuất MỚI (thế hệ mới) rồi `hoan_tac` hồi sinh
    kiểu của đề xuất CŨ, kéo video ra khỏi đề xuất mới."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1",), b=("2",))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu", cum_nhap_id=couple_id)
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "moi", "video_ids": ["1", "2"]}]},
    ])
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac") == {"tu_choi": "khong_hop_le"}
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["kieu"] for k in chia["kieu"]] == ["moi"]
    assert sorted(next(k["video_ids"] for k in chia["kieu"] if k["kieu"] == "moi")) == ["1", "2"]


def test_ghi_de_xuat_khong_hoi_sinh_luot_huy(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE chia_lan SET trang_thai = 'huy' WHERE id = ?", (lan_id,))
        conn.commit()
    with pytest.raises(ValueError):
        models_chia.ghi_de_xuat(db, lan_id, TOI, [
            {"nhom": "n", "kieu": [{"kieu": "x", "video_ids": ["1"]}]}])
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT trang_thai FROM chia_lan WHERE id = ?",
                            (lan_id,)).fetchone()[0] == "huy", "vẫn phải là 'huy', không đổi"


# --- Chính sách tên cụm lúc duyệt (addendum điều phối 24/09) ------------------

def test_duyet_het_hai_kieu_cung_ten_o_hai_nhom_ghep_ten_nhom_khong_hoi_gop(kho):
    """Hai nhóm khác nhau CÙNG kiểu 'couple' trong MỘT lượt ⇒ hai cụm PHÂN
    BIỆT ghép tên nhóm+kiểu, và KHÔNG có lời mời 'gộp' trỏ vào cụm cụm khác
    vừa được `duyet_het` tự tạo trong CHÍNH lượt gọi này."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "Vest", "kieu": [{"kieu": "couple", "video_ids": ["1", "2"]}]},
        {"nhom": "Đồng phục", "kieu": [{"kieu": "couple", "video_ids": ["3"]}]},
    ])
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom Ai")
    assert ket["trung_cum_co_san"] == [], "không được hỏi gộp vào cụm vừa tạo trong CÙNG lượt gọi"
    assert len(ket["cum"]) == 2
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        ten = {models_cum.ten_insight_con(r["insight_goc"], r["kieu"])
              for r in conn.execute("SELECT insight_goc, kieu FROM cum WHERE chu = ?", (TOI,))}
    assert ten == {"Strom Ai Vest couple", "Strom Ai Đồng phục couple"}


def test_duyet_het_kieu_khong_trung_ten_giu_nguyen_khong_ghep_nhom(kho):
    """Đối chứng: hai kiểu KHÁC tên trong cùng lượt (không trùng) thì tên cụm
    KHÔNG bị ghép nhóm — chính sách chỉ áp cho phần THẬT SỰ trùng."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        ten = {r["kieu"] for r in conn.execute(
            "SELECT kieu FROM cum WHERE chu = ?", (TOI,))}
    assert ten == {"couple", "cartoon"}, "kiểu không trùng thì giữ nguyên tên, không ghép nhóm"


# --- quyền sở hữu -------------------------------------------------------------

def test_tao_chia_lan_chi_cho_chu_job(kho):
    db, job = kho   # job của TOI
    assert models_chia.tao_chia_lan(db, job, HO, "p1") is None, "HO không phải chủ job này"
    assert models_chia.tao_chia_lan(db, job, TOI, "p1") is not None


def test_doi_insight_qua_thao_tac_khong_ghi_de_job_neu_luot_khong_thuoc_chu_that(kho):
    """`ap_thao_tac(..., 'doi_insight', ...)` chỉ ghi ngược `jobs` khi
    `jobs.nguoi_tao = chu` gọi request. Mô phỏng lượt bị lệch chủ khỏi job của
    nó (ca không nên xảy ra qua API bình thường sau khi `tao_chia_lan` đã khoá
    theo chủ job — đây là lớp chặn THỨ HAI ngay tại điểm ghi)."""
    db, job = kho   # job của TOI
    lan_id = _de_xuat_2_kieu(db, job)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE chia_lan SET chu = ? WHERE id = ?", (HO, lan_id))
        conn.commit()
    models_chia.ap_thao_tac(db, lan_id, HO, "doi_insight", usecase="Dance", insight_goc="Badaboum")
    assert models_chia.lay_chia(db, lan_id, HO)["usecase"] == "Dance", "chia_lan (của HO) vẫn ghi"
    assert models.get_job(db, job)["usecase"] is None, "jobs (của TOI) KHÔNG được đổi"


def test_duyet_voi_insight_body_khong_ghi_de_job_neu_luot_khong_thuoc_chu_that(kho):
    """Cùng luật sở hữu, đường `_ap_doi_insight_neu_co` (insight trong body lúc
    duyệt) — khác hàm, cùng cột SQL cần lớp chặn."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE chia_lan SET chu = ? WHERE id = ?", (HO, lan_id))
        conn.commit()
    couple_id = _nhom_id(db, lan_id, "couple", chu=HO)
    models_chia.duyet_kieu(db, lan_id, couple_id, HO, None, "Dance", "Badaboum")
    assert models.get_job(db, job)["usecase"] is None


# --- video bị lọc bỏ (thư viện/đã loại) không được rơi mất không dấu vết ------

def test_duyet_bao_lai_video_bi_loc_boi_thu_vien_o_bi_bo(kho):
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "couple", "video_ids": ["1", "NOPE"]}]},
    ])
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, TOI, "Dance", "Badaboum")
    assert ket["gan"] == ["1"]
    assert ket["bi_bo"] == ["NOPE"], "id không thuộc thư viện phải được BÁO, không rơi mất"
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["bi_bo"] == ["NOPE"], "`lay_chia` không được lặng lẽ giấu video mồ côi"
    assert chia["kieu"] == []


# --- một kiểu tên xấu không được làm sập cả "Duyệt tất cả" -------------------

def test_duyet_het_bo_qua_kieu_ten_qua_dai_van_duyet_kieu_con_lai(kho):
    db, job = kho
    ten_qua_dai = "k" * 200
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [
            {"kieu": "couple", "video_ids": ["1"]},
            {"kieu": ten_qua_dai, "video_ids": ["2"]},
        ]},
    ])
    xau_id = _nhom_id(db, lan_id, ten_qua_dai)
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert len(ket["cum"]) == 1 and ket["cum"][0]["gan"] == ["1"]
    assert len(ket["loi_ten"]) == 1
    assert ket["loi_ten"][0]["cum_nhap_id"] == xau_id
    assert "120" in ket["loi_ten"][0]["ly_do"]
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["kieu"] for k in chia["kieu"]] == [ten_qua_dai], "kiểu xấu vẫn ở nguyên trong nháp"
    assert chia["trang_thai"] == "de_xuat", "chưa xong hết ⇒ chưa da_duyet"


# --- chống trôi — duyet_kieu phải tương đương tao_cum + gan_video -------------

def test_duyet_kieu_tuong_duong_tao_cum_va_gan_video_tren_hai_db_song_sinh(tmp_path):
    """`_giai_quyet_kieu` viết LẠI (không gọi thẳng) `tao_cum`+`gan_video` vì lý
    do transaction (xem docstring đầu module) — pin sự tương đương bằng cách
    chạy CÙNG input qua hai đường trên HAI DB riêng và so hàng `cum`/
    `video_cum` cột-theo-cột (bỏ id/mốc giờ, vì hai DB đánh số độc lập)."""
    db_a = tmp_path / "sinh-doi-a.db"
    db_b = tmp_path / "sinh-doi-b.db"
    models.init_db(db_a)
    models.init_db(db_b)
    job_a = models.create_job(db_a, "https://x/a", 2, TOI)
    job_b = models.create_job(db_b, "https://x/b", 2, TOI)
    for vid in ("1", "2"):
        models.record_video(db_a, job_id=job_a, video_id=vid, url=f"u{vid}")
        models.record_video(db_b, job_id=job_b, video_id=vid, url=f"u{vid}")

    # Đường A: `models_cum` trực tiếp (nguồn sự thật #13).
    cum_id_a, _ = models_cum.tao_cum(db_a, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db_a, cum_id_a, TOI, TOI, ["1", "2"])

    # Đường B: `models_chia.duyet_kieu` (đường mới, viết lại hai câu INSERT).
    lan_id = models_chia.tao_chia_lan(db_b, job_b, TOI, "p1")
    models_chia.ghi_de_xuat(db_b, lan_id, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "couple", "video_ids": ["1", "2"]}]}])
    couple_id = _nhom_id(db_b, lan_id, "couple")
    models_chia.duyet_kieu(db_b, lan_id, couple_id, TOI, TOI, "Dance", "Badaboum")

    with sqlite3.connect(db_a) as conn:
        conn.row_factory = sqlite3.Row
        cum_a = dict(conn.execute("SELECT chu, usecase, insight_goc, kieu FROM cum").fetchone())
        vc_a = [dict(r) for r in conn.execute(
            "SELECT video_id, chu FROM video_cum ORDER BY video_id")]
    with sqlite3.connect(db_b) as conn:
        conn.row_factory = sqlite3.Row
        cum_b = dict(conn.execute("SELECT chu, usecase, insight_goc, kieu FROM cum").fetchone())
        vc_b = [dict(r) for r in conn.execute(
            "SELECT video_id, chu FROM video_cum ORDER BY video_id")]
    assert cum_a == cum_b, "cột `cum` (bỏ id/tao_luc) phải khớp hệt giữa hai đường"
    assert vc_a == vc_b, "cột `video_cum` (bỏ cum_id, khác số giữa 2 DB) phải khớp hệt"


# --- hoàn tác không được lùi XUYÊN QUA một lần duyệt --------------------------

def test_hoan_tac_khong_the_lui_xuyen_mot_lan_duyet_sau_khi_chuyen(kho):
    """`chuyen` video "1" từ "couple" sang "cartoon" rồi DUYỆT đúng "couple"
    (hàng `cum_nhap` của nó bị xoá thật) — `hoan_tac` của thao tác `chuyen`
    phía trên từng vẫn CHỌN LẠI được và cố chèn ngược `cum_nhap_id` đã không
    còn tồn tại ⇒ `sqlite3.IntegrityError` (khoá ngoại). Duyệt bất cứ gì phải
    CHỐT thế hệ ngay — hoàn tác sau đó phải bị từ chối SẠCH, không có ngoại
    lệ nào rò ra."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.ap_thao_tac(db, lan_id, TOI, "chuyen", video_ids=["1"],
                            den_cum_nhap_id=cartoon_id)
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket == {"tu_choi": "khong_hop_le"}
    assert not any(h["loai"] == "hoan_tac" for h in _thao_tac(db, lan_id)), \
        "hoàn tác bị từ chối không được ghi thêm dòng nhật ký nào"


def test_hoan_tac_khong_the_lui_xuyen_duyet_het_khi_con_kieu_o_lai(kho):
    """Cùng luật chốt thế hệ, qua `duyet_het`: `chuyen` video "1" sang
    "cartoon" rồi "Duyệt tất cả" — "couple" và "cartoon" vào cụm thật, còn
    "khac" Ở LẠI nháp vì trùng một cụm có sẵn chưa được xác nhận gộp, nên lượt
    vẫn `de_xuat` và luật trạng thái không che hộ. Hoàn tác sau đó phải bị từ
    chối sạch, không cố chèn lại hàng `cum_nhap` đã bị xoá khi duyệt."""
    db, job = kho
    models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "khac")
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [
            {"kieu": "couple", "video_ids": ["1", "2"]},
            {"kieu": "cartoon", "video_ids": ["3"]},
            {"kieu": "khac", "video_ids": ["4"]},
        ]},
    ])
    models_chia.ap_thao_tac(db, lan_id, TOI, "chuyen", video_ids=["1"],
                            den_cum_nhap_id=_nhom_id(db, lan_id, "cartoon"))
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert len(ket["cum"]) == 2 and len(ket["trung_cum_co_san"]) == 1
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "de_xuat"
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac") == {"tu_choi": "khong_hop_le"}
    assert not any(h["loai"] == "hoan_tac" for h in _thao_tac(db, lan_id))


def test_hoan_tac_khong_the_lui_xuyen_mot_lan_duyet_sau_khi_gop(kho):
    """gop "couple"→"cartoon" rồi duyệt "cartoon" (video "1"
    và "2" vào cụm thật) rồi hoàn tác — trước đây CHẠY ĐƯỢC và làm sống lại
    một "couple" trong nháp chứa video "1" trong khi video đó ĐÃ Ở một cụm
    thật (nháp nói dối). Giờ phải bị chặn sạch, không hồi sinh gì.

    Giữ lại một kiểu thứ ba CHƯA duyệt ("khac") để lượt còn ở trạng thái
    `de_xuat` sau khi duyệt "cartoon" — nếu không, duyệt hết mọi kiểu tự đưa
    lượt sang `da_duyet`, và `hoan_tac` bị chặn bởi luật trạng thái (kiểm ở
    chỗ khác) trước khi kịp chạm tới bộ lọc `the_he` đang muốn pin ở đây.
    """
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [
            {"kieu": "couple", "video_ids": ["1"]},
            {"kieu": "cartoon", "video_ids": ["2"]},
            {"kieu": "khac", "video_ids": ["3"]},
        ]},
    ])
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop",
                            tu_cum_nhap_id=couple_id, den_cum_nhap_id=cartoon_id)
    models_chia.duyet_kieu(db, lan_id, cartoon_id, TOI, None, "Dance", "Badaboum")
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "de_xuat", "còn kiểu 'khac' chưa duyệt"
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket == {"tu_choi": "khong_hop_le"}
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert "couple" not in [k["kieu"] for k in chia["kieu"]], \
        "không được hồi sinh một kiểu nháp chứa video đã ở cụm thật"


def test_hoan_tac_doi_ten_sau_khi_duyet_khong_dot_stack_khong_ghi_log(kho):
    """Đổi tên "couple"→"a2" rồi duyệt kiểu đó rồi hoàn tác — trước đây CHẠY
    ĐƯỢC nhưng là một cú lùi RỖNG (`so_video: 0`, kiểu đã biến khỏi nháp),
    vẫn ĐỐT một chỗ trong ngăn xếp và ghi thêm một dòng `hoan_tac` vào nhật
    ký (nhiễu số đếm nghiệm thu — số dòng nhật ký dùng làm phép nghiệm thu).
    Giờ phải bị từ chối sạch, không đốt gì."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="a2")
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    so_dong_truoc = len(_thao_tac(db, lan_id))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket == {"tu_choi": "khong_hop_le"}
    assert len(_thao_tac(db, lan_id)) == so_dong_truoc, "hoàn tác bị từ chối không được ghi thêm dòng nào"


# --- bộ lọc chống trôi trên đường duyệt: mỗi bộ lọc một phép kiểm riêng -----

def test_duyet_bo_qua_video_thuoc_job_cua_nguoi_khac_theo_chi_cua(kho):
    """`chi_cua` là lớp chặn PHÒNG THỦ trên đường duyệt: `ghi_de_xuat` không
    tự kiểm id video có thuộc job của người gọi hay không, nên nếu một id
    video của NGƯỜI KHÁC lọt vào đề xuất, duyệt vẫn phải LOẠI nó ở `bi_bo`,
    không gán vào cụm."""
    db, job = kho
    job_ho = models.create_job(db, "https://www.tiktok.com/tag/b", 1, HO)
    models.record_video(db, job_id=job_ho, video_id="99", url="u99")
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "couple", "video_ids": ["1", "99"]}]},
    ])
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, TOI, "Dance", "Badaboum")
    assert ket["gan"] == ["1"]
    assert ket["bi_bo"] == ["99"], "video của job người khác phải bị `chi_cua` chặn, không gán"


def test_duyet_phat_hien_trung_cum_that_bat_ke_hoa_thuong(kho):
    """So trùng với cụm THẬT dùng khoá casefold (`models_cum._khoa_ten`) —
    biến thể hoa/thường của tên cũ vẫn phải bị coi là trùng, không tạo cụm
    thứ hai."""
    db, job = kho
    cu_id, _ = models_cum.tao_cum(db, TOI, "dance", "badaboum", "COUPLE")
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    assert ket == {"trung_cum_co_san": [
        {"cum_nhap_id": couple_id, "cum_id": cu_id, "ten": "Badaboum couple", "so_video": 2}]}


# --- usecase/insight gốc trống ⇒ 400 GIỐNG NHAU ở cả hai đường duyệt -------

def test_duyet_kieu_va_duyet_het_tra_loi_giong_nhau_khi_insight_trong(kho):
    """`duyet_kieu` và `duyet_het` phải raise CÙNG một `ValueError` khi
    usecase/insight gốc trống (qua `kiem_nhan`) — nếu `duyet_het` nuốt lỗi
    đó vào `loi_ten` của TỪNG kiểu và trả 200 thay vì raise thì hai đường
    không khớp nhau cho CÙNG một đầu vào, và `duyet_het` không được có
    `loi_ten` cho ca này."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    with pytest.raises(ValueError, match="usecase/insight gốc"):
        models_chia.duyet_kieu(db, lan_id, _nhom_id(db, lan_id, "couple"), TOI, None, "", "")
    with pytest.raises(ValueError, match="usecase/insight gốc"):
        models_chia.duyet_het(db, lan_id, TOI, None, "", "")
    # Không thao tác nào bị ghi — cả hai lời gọi trên đều thất bại sạch.
    assert _thao_tac(db, lan_id) == []


# --- tên cụm CHỐT một lần lúc ghi_de_xuat, duyệt CHỈ đọc ---------------------

def test_ten_cum_on_dinh_du_duyet_tung_kieu_theo_thu_tu_nao(kho):
    """Trước đây tên ghép nhóm được tính LẠI mỗi lần duyệt
    từ dữ liệu CÒN SỐNG — duyệt hai kiểu trùng tên (khác nhóm) TỪNG CÁI MỘT
    qua `duyet_kieu` cho ra hai tên khác nhau tuỳ thứ tự (kiểu duyệt SAU
    không còn thấy "anh em" trùng tên của nó, vì hàng đó đã bị xoá bởi lần
    duyệt trước). Tên giờ CHỐT một lần lúc `ghi_de_xuat`, ổn định bất kể
    thứ tự duyệt."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "Vest", "kieu": [{"kieu": "couple", "video_ids": ["1", "2"]}]},
        {"nhom": "Đồng phục", "kieu": [{"kieu": "couple", "video_ids": ["3"]}]},
    ])
    chia = models_chia.lay_chia(db, lan_id, TOI)
    vest_id = next(k["cum_nhap_id"] for k in chia["kieu"] if k["nhom"] == "Vest")
    dong_phuc_id = next(k["cum_nhap_id"] for k in chia["kieu"] if k["nhom"] == "Đồng phục")

    ket1 = models_chia.duyet_kieu(db, lan_id, vest_id, TOI, None, "Motion", "Strom Ai")
    ket2 = models_chia.duyet_kieu(db, lan_id, dong_phuc_id, TOI, None, "Motion", "Strom Ai")
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        ten = {r["id"]: models_cum.ten_insight_con(r["insight_goc"], r["kieu"])
              for r in conn.execute("SELECT id, insight_goc, kieu FROM cum")}
    assert {ten[ket1["cum_id"]], ten[ket2["cum_id"]]} == {
        "Strom Ai Vest couple", "Strom Ai Đồng phục couple"}, \
        "cả hai phải ghép tên nhóm dù duyệt TỪNG CÁI MỘT — không phụ thuộc thứ tự"


def test_bien_the_hoa_thuong_trong_cung_nhom_tu_gop_khong_hoi(kho):
    """Hai kiểu trong CÙNG nhóm chỉ khác hoa/thường
    ("couple"/"Couple") ghép ra hai chuỗi khác NHAU Ở MẶT CHỮ ("Vest
    couple"/"Vest Couple") nhưng trùng nhau ở casefold — trước đây kiểu xử
    lý SAU đọc nhầm thành "trùng cụm có sẵn" với cụm mà CHÍNH `duyet_het` vừa
    tạo cho kiểu xử lý TRƯỚC, trong CÙNG một lượt gọi (hop-dong cấm việc
    này). Giờ phải tự gộp thẳng, không hỏi, không tạo cụm thứ hai."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "Vest", "kieu": [
            {"kieu": "couple", "video_ids": ["1"]},
            {"kieu": "Couple", "video_ids": ["2"]},
        ]},
    ])
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom Ai")
    assert ket["trung_cum_co_san"] == [], "không được hỏi gộp giữa hai kiểu ANH EM cùng lượt gọi"
    assert len(ket["cum"]) == 2 and _dem(db, "cum") == 1, "phải tự gộp vào MỘT cụm, không tạo hai"
    with sqlite3.connect(db) as conn:
        vc = {r[0] for r in conn.execute("SELECT video_id FROM video_cum WHERE chu = ?", (TOI,))}
    assert vc == {"1", "2"}


def test_ten_ghep_nhom_trung_voi_kieu_don_cua_hang_khac_tu_gop_khong_hoi(kho):
    """Nhóm "A" và nhóm "B" cùng có kiểu "couple" ⇒ ghép
    "A couple"/"B couple"; một hàng thứ ba ở nhóm "C" có kiểu ĐƠN vốn ĐÃ LÀ
    "A couple" (không hề trùng chữ "couple" của hai hàng kia, nên không tự
    ghép nhóm) — tên GHÉP của hàng đầu trùng NGUYÊN VĂN kiểu ĐƠN của hàng thứ
    ba. Từng đọc thành "trùng cụm có sẵn" với cụm vừa tự tạo trong CHÍNH lượt
    gọi này; giờ phải tự gộp."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "B", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "C", "kieu": [{"kieu": "A couple", "video_ids": ["3"]}]},
    ])
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom Ai")
    assert ket["trung_cum_co_san"] == []
    assert _dem(db, "cum") == 2, "'A couple' (ghép) và 'A couple' (đơn) là MỘT cụm; 'B couple' là cụm còn lại"


def test_duyet_kiem_lai_trung_voi_cum_that_xuat_hien_sau_ghi_de_xuat(kho):
    """Tên cụm chốt lúc `ghi_de_xuat`, nhưng lúc duyệt vẫn phải KIỂM LẠI va
    chạm với bảng `cum` THẬT — kể cả khi cụm trùng tên đó chỉ mới xuất hiện
    SAU khi đề xuất đã ghi, không phải trước đó."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    # Cụm THẬT trùng tên xuất hiện SAU khi đề xuất đã ghi.
    cu_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    assert ket == {"trung_cum_co_san": [
        {"cum_nhap_id": couple_id, "cum_id": cu_id, "ten": "Badaboum couple", "so_video": 2}]}


# --- tên cụm CHỈ tính lại khi `doi_ten`, và chỉ cho hàng bị đổi + hàng va chạm

def _ten_cum_theo_nhom_kieu(db, lan_id) -> dict[tuple[str, str], str]:
    return {(k["nhom"], k["kieu"]): k["ten_cum"]
            for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}


def test_lay_chia_tra_ten_cum_moi_kieu(kho):
    """`lay_chia` trả `ten_cum` của từng kiểu — đúng cái tên mà lúc duyệt sẽ
    dùng, để UI hiện trước được tên cụm sắp tạo."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "Vest", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "Đồng phục", "kieu": [{"kieu": "couple", "video_ids": ["2"]},
                                       {"kieu": "cartoon", "video_ids": ["3"]}]},
    ])
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("Vest", "couple"): "Vest couple", ("Đồng phục", "couple"): "Đồng phục couple",
        ("Đồng phục", "cartoon"): "cartoon"}


def test_duyet_mot_kieu_roi_doi_ten_kieu_khac_khong_lam_troi_ten_anh_em(kho):
    """Tên đã chốt của một kiểu CHỈ đổi khi chính nó bị `doi_ten` hoặc va chạm
    với tên vừa đổi. Duyệt riêng "Vest couple" (hàng đó rời nháp) rồi đổi tên
    một kiểu KHÔNG liên quan: "Đồng phục couple" vẫn phải giữ tiền tố nhóm —
    không được tính lại cả lượt trên tập hàng CÒN SỐNG."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "Vest", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "Đồng phục", "kieu": [{"kieu": "couple", "video_ids": ["2"]},
                                       {"kieu": "cartoon", "video_ids": ["3"]}]},
    ])
    chia = models_chia.lay_chia(db, lan_id, TOI)
    id_cua = {(k["nhom"], k["kieu"]): k["cum_nhap_id"] for k in chia["kieu"]}
    models_chia.duyet_kieu(db, lan_id, id_cua[("Vest", "couple")], TOI, TOI, "Motion", "Strom")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten",
                            cum_nhap_id=id_cua[("Đồng phục", "cartoon")], kieu="cartoon 2")
    models_chia.duyet_het(db, lan_id, TOI, TOI)
    with sqlite3.connect(db) as conn:
        ten = sorted(r[0] for r in conn.execute("SELECT kieu FROM cum"))
    assert ten == ["Vest couple", "cartoon 2", "Đồng phục couple"]


def test_gop_va_xoa_kieu_khong_doi_ten_cum_cua_kieu_khac(kho):
    """Gộp/xoá làm mất "anh em" trùng tên của một kiểu — tên đã chốt của kiểu
    còn lại vẫn GIỮ NGUYÊN (chỉ `doi_ten` mới tính lại tên)."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "B", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "C", "kieu": [{"kieu": "cartoon", "video_ids": ["3"]},
                               {"kieu": "dance", "video_ids": ["4"]}]},
    ])
    id_cua = {(k["nhom"], k["kieu"]): k["cum_nhap_id"]
              for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop", tu_cum_nhap_id=id_cua[("B", "couple")],
                            den_cum_nhap_id=id_cua[("C", "cartoon")])
    assert _ten_cum_theo_nhom_kieu(db, lan_id)[("A", "couple")] == "A couple"
    models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu", cum_nhap_id=id_cua[("C", "dance")])
    assert _ten_cum_theo_nhom_kieu(db, lan_id)[("A", "couple")] == "A couple"


def test_hoan_tac_gop_va_xoa_kieu_tra_lai_dung_ten_cum_cu(kho):
    """Hàng được hồi sinh bởi `hoan_tac` (gộp/xoá) mang lại ĐÚNG `ten_cum` nó
    có trước thao tác, không tính lại."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "B", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "C", "kieu": [{"kieu": "cartoon", "video_ids": ["3"]}]},
    ])
    truoc = _ten_cum_theo_nhom_kieu(db, lan_id)
    id_cua = {(k["nhom"], k["kieu"]): k["cum_nhap_id"]
              for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop", tu_cum_nhap_id=id_cua[("B", "couple")],
                            den_cum_nhap_id=id_cua[("C", "cartoon")])
    models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu", cum_nhap_id=id_cua[("A", "couple")])
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == truoc


def test_hoan_tac_doi_ten_tra_lai_dung_ten_cu_cua_hang_doi_va_hang_va_cham(kho):
    """`doi_ten` "cartoon"→"dance" va chạm với "dance" có sẵn ⇒ CẢ HAI ghép
    nhóm. Hoàn tác phải trả lại ĐÚNG tên cũ của hàng bị đổi VÀ của hàng va
    chạm — kể cả một hàng không liên quan mà tên đã chốt ("A couple", còn
    tiền tố dù anh em "B couple" đã bị xoá) khác với cái một lần tính lại
    toàn lượt sẽ cho ra."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "B", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "C", "kieu": [{"kieu": "cartoon", "video_ids": ["3"]}]},
        {"nhom": "D", "kieu": [{"kieu": "dance", "video_ids": ["4"]}]},
    ])
    id_cua = {(k["nhom"], k["kieu"]): k["cum_nhap_id"]
              for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}
    models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu", cum_nhap_id=id_cua[("B", "couple")])
    truoc = _ten_cum_theo_nhom_kieu(db, lan_id)
    assert truoc == {("A", "couple"): "A couple", ("C", "cartoon"): "cartoon",
                     ("D", "dance"): "dance"}

    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=id_cua[("C", "cartoon")],
                            kieu="dance")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("A", "couple"): "A couple", ("C", "dance"): "C dance", ("D", "dance"): "D dance"}

    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == truoc
