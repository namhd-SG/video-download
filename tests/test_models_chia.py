"""Tự chia cụm theo lượt — `web/models_chia.py`: DDL, nháp, nhật ký, đường
duyệt duy nhất sang cụm thật.

Gọi thẳng các hàm model, cùng khuôn `tests/test_web_cum.py`.
"""
from __future__ import annotations

import json
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
    # Trùng chưa xác nhận ⇒ KHÔNG ghi `duyet_kieu` — chỉ có dòng `doi_insight`
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


def test_loai_thao_tac_la_tap_dong_gia_tri():
    assert models_chia.LOAI_THAO_TAC == (
        "chap_nhan", "duyet_het", "duyet_kieu", "gop", "doi_ten", "chuyen",
        "ngoai_chu_de", "tra_ve", "hoan_tac", "xoa_kieu", "doi_insight",
        "tach", "gop_nhom", "doi_ten_nhom", "huy_luot")


def test_ap_thao_tac_tu_choi_loai_khong_ro(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    with pytest.raises(ValueError):
        models_chia.ap_thao_tac(db, lan_id, TOI, "an-trom")


@pytest.mark.parametrize("loai", ["duyet_het", "duyet_kieu"])
def test_ap_thao_tac_tu_choi_duyet_qua_duong_nay(kho, loai):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    with pytest.raises(ValueError):
        models_chia.ap_thao_tac(db, lan_id, TOI, loai)


def test_duyet_kieu_ghi_nhat_ky_rieng_va_khong_hoan_tac_duoc(kho):
    """Duyệt MỘT kiểu ghi `loai='duyet_kieu'` — phân biệt được với "Duyệt tất
    cả" (`duyet_het`) khi đọc nhật ký — và, như mọi dòng duyệt, không nằm
    trong luồng hoàn tác nháp."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1",), b=("2",))
    models_chia.duyet_kieu(db, lan_id, _nhom_id(db, lan_id, "couple"), TOI, None,
                           "Dance", "Badaboum")
    assert [h["loai"] for h in _thao_tac(db, lan_id)] == ["doi_insight", "duyet_kieu"]
    assert "duyet_kieu" not in models_chia._HOAN_TAC_DUOC
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac") == {"tu_choi": "khong_hop_le"}
    models_chia.duyet_het(db, lan_id, TOI, None)
    assert [h["loai"] for h in _thao_tac(db, lan_id)] == ["doi_insight", "duyet_kieu", "duyet_het"]


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


# --- video ĐÃ DUYỆT không được kéo lại nháp qua tach/chuyen/ngoai_chu_de/tra_ve --

def test_op_tu_choi_video_da_duyet_khong_keo_lai_vao_nhap(kho):
    """Video đã DUYỆT (vào `video_cum` thật) không được kéo lại nháp qua
    `tach`/`chuyen`/`ngoai_chu_de` — hàng nháp của nó còn "mồ côi"
    (`lan='kieu'`, `cum_nhap_id=NULL`, FK `ON DELETE SET NULL` chỉ xoá cột đó,
    không đổi `lan`) nhưng KHÔNG còn thuộc phạm vi sửa của lượt này. Lý do
    "đã ở cụm thật" mang mã RIÊNG (`video_da_o_cum_that` + `video_ids`) —
    khác lý do chung "khong_hop_le" — để UI báo đúng lý do (xem route/UI)."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    truoc = len(_thao_tac(db, lan_id))

    assert models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["1"], nhom="n",
                                   kieu="k") == {"tu_choi": "video_da_o_cum_that",
                                                "video_ids": ["1"]}
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "chuyen", video_ids=["1"],
                                   den_cum_nhap_id=cartoon_id) == {
        "tu_choi": "video_da_o_cum_that", "video_ids": ["1"]}
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "ngoai_chu_de",
                                   video_ids=["1"]) == {"tu_choi": "video_da_o_cum_that",
                                                        "video_ids": ["1"]}
    assert len(_thao_tac(db, lan_id)) == truoc, "không ghi thêm dòng nhật ký nào"


def test_op_tu_choi_video_da_loai_khong_tao_kieu_rong(kho):
    """Video đã LOẠI khỏi thư viện (Thùng rác) vẫn còn hàng `video_cum_nhap`
    của lượt. Mọi op di chuyển theo id phải từ chối CẢ yêu cầu với mã riêng
    `video_da_loai` — trước đây `tach` nhận nó và sinh một kiểu RỖNG trên UI.
    Danh sách trộn (một video còn sống + một đã loại) cũng bị từ chối trọn."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",), nghi=["5", "6"])
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE videos SET da_loai_luc = '2026-09-28T09:00:00+00:00' "
                     "WHERE video_id = '5'")
    kieu_truoc, nhat_ky_truoc = _dem(db, "cum_nhap"), len(_thao_tac(db, lan_id))
    tu_choi = {"tu_choi": "video_da_loai", "video_ids": ["5"]}

    assert models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["5"], nhom="n",
                                   kieu="k") == tu_choi
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "chuyen", video_ids=["1", "5"],
                                   den_cum_nhap_id=cartoon_id) == tu_choi
    assert models_chia.ap_thao_tac(db, lan_id, TOI, "tra_ve", video_ids=["5"],
                                   den_cum_nhap_id=cartoon_id) == tu_choi
    assert _dem(db, "cum_nhap") == kieu_truoc, "không sinh kiểu nào"
    assert len(_thao_tac(db, lan_id)) == nhat_ky_truoc, "không ghi dòng nhật ký nào"
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert next(k for k in chia["kieu"] if k["kieu"] == "couple")["video_ids"] == ["1", "2"], \
        "video còn sống trong danh sách trộn không bị chuyển"
    # Đối chứng: video KHÔNG bị loại cùng làn vẫn tách được như cũ.
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["6"], nhom="n", kieu="k")
    assert ket and not ket.get("tu_choi")


def test_tra_ve_tu_choi_video_da_duyet_du_dang_o_lan_nghi(kho):
    """`tra_ve` cũng phải chặn video đã duyệt — kể cả khi hàng của nó đang
    mang `lan='nghi'` (mô phỏng trạng thái còn sót lại từ trước khi có luật
    lọc này, hoặc một đường ghi trực tiếp khác). Cùng lý do RIÊNG
    `video_da_o_cum_that` (ưu tiên hơn lý do "đang ở nghi")."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE video_cum_nhap SET lan = 'nghi' WHERE chia_lan_id = ? AND video_id = '1'",
            (lan_id,))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "tra_ve", video_ids=["1"],
                                  den_cum_nhap_id=cartoon_id)
    assert ket == {"tu_choi": "video_da_o_cum_that", "video_ids": ["1"]}


def test_ngoai_chu_de_tren_video_da_o_nghi_la_no_op_khong_ghi_log(kho):
    """Nút cũ "Đúng, bỏ khỏi lượt" gọi `ngoai_chu_de` trên chính video ĐÃ ở
    nghi — không có gì đổi (hợp đồng chỉ có MỘT trạng thái "nghi") nên phải
    là no-op: không ghi log, và không chiếm mất lượt "Hoàn tác" của thao tác
    TRƯỚC đó."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu",
                            cum_nhap_id=_nhom_id(db, lan_id, "cartoon"))
    assert models_chia.lay_chia(db, lan_id, TOI)["nghi"] == ["3"]
    truoc = len(_thao_tac(db, lan_id))

    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "ngoai_chu_de", video_ids=["3"])
    assert ket == {"tu_choi": "khong_hop_le"}
    assert len(_thao_tac(db, lan_id)) == truoc, "video đã ở nghi rồi ⇒ no-op, không ghi log"

    ket2 = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket2["so_video"] == 1
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert "cartoon" in [k["kieu"] for k in chia["kieu"]], \
        "hoan_tac phải lùi đúng xoa_kieu, không bị dòng no-op chiếm mất"


# --- danh sách TRỘN (vài video hợp lệ + vài không) bị từ chối CẢ yêu cầu ----

def test_tach_danh_sach_tron_tu_choi_ca_yeu_cau_khong_tach_phan_hop_le(kho):
    """`tach(['1' hợp lệ, '9' không thuộc lượt])` phải từ chối CẢ yêu cầu —
    không tự lọc bỏ '9' rồi vẫn tách '1' sang kiểu mới."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    truoc = len(_thao_tac(db, lan_id))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["1", "9"],
                                  nhom="n", kieu="k")
    assert ket == {"tu_choi": "khong_hop_le"}
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert "k" not in [k["kieu"] for k in chia["kieu"]], "không được tạo kiểu mới cho phần hợp lệ"
    assert "1" in next(k["video_ids"] for k in chia["kieu"] if k["kieu"] == "couple"), \
        "video '1' phải Ở NGUYÊN trong 'couple', không bị tách"
    assert len(_thao_tac(db, lan_id)) == truoc, "không ghi thêm dòng nhật ký nào"


def test_chuyen_danh_sach_tron_tu_choi_ca_yeu_cau_va_bao_dung_ly_do(kho):
    """`chuyen(['1' đã duyệt, '3' hợp lệ])` phải từ chối CẢ yêu cầu, mang lý
    do RIÊNG "video_da_o_cum_that" — không tự lọc bỏ '1' rồi vẫn chuyển '3'."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    truoc = len(_thao_tac(db, lan_id))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "chuyen", video_ids=["1", "3"],
                                  den_cum_nhap_id=cartoon_id)
    assert ket == {"tu_choi": "video_da_o_cum_that", "video_ids": ["1"]}
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert "3" in next(k["video_ids"] for k in chia["kieu"] if k["kieu"] == "cartoon"), \
        "video '3' phải Ở NGUYÊN trong 'cartoon', không bị chuyển"
    assert len(_thao_tac(db, lan_id)) == truoc, "không ghi thêm dòng nhật ký nào (ngoài duyệt)"


def test_ngoai_chu_de_danh_sach_tron_tu_choi_ca_yeu_cau(kho):
    """`ngoai_chu_de(['3' đã ở nghi, '1' hợp lệ])` phải từ chối CẢ yêu cầu —
    không tự lọc bỏ '3' rồi vẫn đưa '1' sang nghi."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu",
                            cum_nhap_id=_nhom_id(db, lan_id, "cartoon"))
    assert models_chia.lay_chia(db, lan_id, TOI)["nghi"] == ["3", "4"]
    truoc = len(_thao_tac(db, lan_id))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "ngoai_chu_de", video_ids=["3", "1"])
    assert ket == {"tu_choi": "khong_hop_le"}
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert "1" in next(k["video_ids"] for k in chia["kieu"] if k["kieu"] == "couple"), \
        "video '1' phải Ở NGUYÊN trong 'couple', không bị đưa sang nghi"
    assert chia["nghi"] == ["3", "4"], "làn nghi không đổi"
    assert len(_thao_tac(db, lan_id)) == truoc, "không ghi thêm dòng nhật ký nào (ngoài xoa_kieu)"


def test_tra_ve_danh_sach_tron_tu_choi_ca_yeu_cau(kho):
    """`tra_ve(['3' hợp lệ (nghi), '1' đang ở một kiểu — việc của chuyen])`
    phải từ chối CẢ yêu cầu — không tự lọc bỏ '1' rồi vẫn trả '3' về."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "xoa_kieu",
                            cum_nhap_id=_nhom_id(db, lan_id, "cartoon"))
    assert models_chia.lay_chia(db, lan_id, TOI)["nghi"] == ["3", "4"]
    truoc = len(_thao_tac(db, lan_id))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "tra_ve", video_ids=["3", "1"],
                                  den_cum_nhap_id=couple_id)
    assert ket == {"tu_choi": "khong_hop_le"}
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["nghi"] == ["3", "4"], "video '3' phải Ở NGUYÊN trong nghi, không được trả về"
    assert len(_thao_tac(db, lan_id)) == truoc, "không ghi thêm dòng nhật ký nào (ngoài xoa_kieu)"


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
#
# Drive id và link gốc trong các test dưới đây có HÌNH DẠNG THẬT (id Drive
# `[A-Za-z0-9_-]{10,128}`, link `https://…`): payload lọc theo đúng luật của
# bên nhận, nên id giả kiểu "d1" / link "u1" sẽ bị bỏ.

def _drive(vid: str) -> str:
    return f"1Drive_{vid}_AbCdEfGhIjKl"


def _dat_link_that(db) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE videos SET url = 'https://www.tiktok.com/@a/video/' || video_id")


def test_xay_payload_lo_chi_gom_video_co_drive_va_dung_thu_tu(kho):
    db, job = kho
    _dat_link_that(db)
    for vid, drive in (("1", _drive("1")), ("2", None), ("3", _drive("3"))):
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE videos SET drive_file_id = ?, tao_luc = ? WHERE video_id = ?",
                        (drive, f"2026-09-2{vid}T00:00:00+00:00", vid))
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "3"])
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    payload = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert payload["v"] == 1
    assert [i["f"] for i in payload["items"]] == [_drive("1"), _drive("3")], \
        "video không có drive_file_id bị bỏ"
    assert payload["so_video"] == 3, "so_video đếm lô TRƯỚC khi lọc Drive (3 video, 2 item)"
    assert payload["nhan"] == {"usecase": "Dance", "insight": "Badaboum couple",
                               "template": "Goc", "cum_id": cum_id, "lo": {"thu": 1, "tong": 1}}


def test_xay_payload_lo_bo_video_da_loai_sau_khi_vao_cum(kho):
    """Video bị "loại" SAU khi đã ở cụm vẫn còn hàng `video_cum`, nhưng không
    được sang Creative Desk — cùng bộ lọc mà `lay_cum` đếm, để lô gửi đi khớp
    số video người dùng thấy."""
    db, job = kho
    _dat_link_that(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE videos SET drive_file_id = '1Drive_' || video_id || '_AbCdEfGhIjKl'")
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "3"])
    models.danh_dau_da_loai(db, "2", TOI)
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    payload = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert [i["f"] for i in payload["items"]] == [_drive("1"), _drive("3")]


def test_xay_payload_lo_chi_gom_video_trong_pham_vi_chi_cua(kho):
    """Cụm có cả video thuộc job của người khác (gán khi không giới hạn phạm
    vi) — lô gửi đi dưới phạm vi `chi_cua` chỉ mang video của người đó, cùng
    bộ lọc `lay_cum` dùng để đếm."""
    db, job = kho
    job_ho = models.create_job(db, "https://www.tiktok.com/tag/b", 1, HO)
    models.record_video(db, job_id=job_ho, video_id="h1", url="uh1")
    _dat_link_that(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE videos SET drive_file_id = '1Drive_' || video_id || '_AbCdEfGhIjKl'")
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, None, ["1", "h1"])
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    payload = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert [i["f"] for i in payload["items"]] == [_drive("1")]


def test_xay_payload_lo_bo_item_sai_luat_ben_nhan(kho):
    """Bên nhận (Creative Desk) bỏ CẢ LÔ, không ack, nếu chỉ một item có Drive
    id sai hình dạng hoặc link gốc không phải http(s). Payload phải bỏ đúng
    những item đó (giống lọc của đường chọn tay) để phần còn lại vẫn qua."""
    db, job = kho
    _dat_link_that(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE videos SET drive_file_id = '1Drive_' || video_id || '_AbCdEfGhIjKl'")
        conn.execute("UPDATE videos SET url = 'u2' WHERE video_id = '2'")          # link không http(s)
        conn.execute("UPDATE videos SET drive_file_id = 'd3ab' WHERE video_id = '3'")   # id 4 ký tự
        conn.execute("UPDATE videos SET drive_file_id = 'x y/../zzzzzzzz' WHERE video_id = '4'")
        conn.execute("UPDATE videos SET url = 'HTTP://www.tiktok.com/@a/video/5' WHERE video_id = '5'")
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "3", "4", "5"])
    cum = models_cum.lay_cum(db, cum_id, TOI, TOI)
    payload = models_chia.xay_payload_lo(db, cum, TOI, TOI, 1)
    assert sorted(i["f"] for i in payload["items"]) == [_drive("1"), _drive("5")]


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


# --- video đã có nhà THẬT (gán tay) phải ẩn khỏi mọi làn nháp, KHÔNG bi_bo ----

def test_lay_chia_an_video_gan_tay_vao_cum_that_khoi_huong_dan(kho):
    """Root fix C2: một video làn "hướng dẫn" gán TAY vào cụm thật (không qua
    duyệt) phải biến khỏi `huong_dan` ngay — nó đã XONG, không phải "lạc" nên
    KHÔNG được rơi vào `bi_bo`. Và nút "cả làn" (gọi `ngoai_chu_de` với đúng
    danh sách `huong_dan` mà `lay_chia` vừa trả) phải chạy được cho phần còn
    lại — trước bản vá này, video đã ở cụm thật vẫn kẹt trong `huong_dan`, làm
    `_kiem_video_ids_thao_tac` chặn CẢ yêu cầu vì lý do `video_da_o_cum_that`."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",), huong_dan=["5", "6"])
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Motion", "Badaboum")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["5"])

    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["huong_dan"] == ["6"], "'5' đã có nhà (cụm thật) — phải ẩn khỏi huong_dan"
    assert chia["bi_bo"] == [], "không phải video lạc — KHÔNG được rơi vào bi_bo"
    assert chia["kieu"][0]["video_ids"] == ["1", "2"], "làn kiểu không đổi"

    truoc = len(_thao_tac(db, lan_id))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "ngoai_chu_de", video_ids=chia["huong_dan"])
    assert ket["so_video"] == 1 and ket["chi_tiet"]["video_ids"] == ["6"], \
        "nút cả làn phải chạy được cho phần CÒN LẠI, không bị chặn vì '5' đã ở cụm thật"
    assert len(_thao_tac(db, lan_id)) == truoc + 1

    chia2 = models_chia.lay_chia(db, lan_id, TOI)
    assert chia2["huong_dan"] == [] and chia2["nghi"] == ["6"]
    assert chia2["bi_bo"] == [], "'5' vẫn không phải bi_bo sau thao tác"


def test_lay_chia_an_video_gan_tay_vao_cum_that_khoi_mot_kieu(kho):
    """Cùng luật cho làn "kiểu" (khác nhánh mồ côi cũ, `cum_nhap_id` của hàng
    này VẪN CÒN — video bị gán tay trong khi kiểu chứa nó chưa được duyệt)."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Motion", "Badaboum")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1"])

    chia = models_chia.lay_chia(db, lan_id, TOI)
    couple = next(k for k in chia["kieu"] if k["kieu"] == "couple")
    assert couple["video_ids"] == ["2"], "'1' đã có nhà — phải ẩn khỏi kiểu 'couple'"
    assert chia["bi_bo"] == []


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


def test_ten_ghep_nhom_trung_ten_cuoi_cua_hang_khac_cung_ghep_nhom_thanh_ba_cum(kho):
    """Va chạm tên xét trên TÊN CUỐI (sau khi ghép nhóm), không phải `kieu`
    thô. "Vest"/"couple" ghép thành "Vest couple" — trùng tên cuối của hàng
    "khác"/"Vest couple" (một kiểu KHÁC) ⇒ hàng đó cũng ghép nhóm thành
    "khác Vest couple". Ba kiểu khác nhau ra ba cụm, cả khi duyệt hết một lần
    lẫn khi duyệt từng kiểu — không tự gộp hai kiểu khác nhau, không hỏi gộp."""
    db, job = kho
    de_xuat = [
        {"nhom": "Vest", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "Đồng phục", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "khác", "kieu": [{"kieu": "Vest couple", "video_ids": ["3"]}]}]
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, de_xuat)
    assert sorted(k["ten_cum"] for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]) == [
        "Vest couple", "khác Vest couple", "Đồng phục couple"]
    ket = models_chia.duyet_het(db, lan_id, TOI, TOI, "Motion", "Strom")
    assert ket["trung_cum_co_san"] == []
    assert len({k["cum_id"] for k in ket["cum"]}) == 3

    # Cùng đề xuất, job thứ hai, duyệt TỪNG kiểu (insight khác để không đụng
    # cụm của lượt trên): không kiểu nào bị hỏi gộp vào cụm kiểu kia vừa tạo.
    job2 = models.create_job(db, "https://www.tiktok.com/tag/b", 3, TOI)
    for vid in ("7", "8", "9"):
        models.record_video(db, job_id=job2, video_id=vid, url=f"u{vid}")
    lan2 = models_chia.tao_chia_lan(db, job2, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan2, TOI, [
        {"nhom": "Vest", "kieu": [{"kieu": "couple", "video_ids": ["7"]}]},
        {"nhom": "Đồng phục", "kieu": [{"kieu": "couple", "video_ids": ["8"]}]},
        {"nhom": "khác", "kieu": [{"kieu": "Vest couple", "video_ids": ["9"]}]}])
    id_cua = {(k["nhom"], k["kieu"]): k["cum_nhap_id"]
              for k in models_chia.lay_chia(db, lan2, TOI)["kieu"]}
    a = models_chia.duyet_kieu(db, lan2, id_cua[("Vest", "couple")], TOI, TOI, "Motion", "Khac")
    b = models_chia.duyet_kieu(db, lan2, id_cua[("khác", "Vest couple")], TOI, TOI)
    assert "trung_cum_co_san" not in b and b["cum_id"] != a["cum_id"]


def test_ghep_nhom_lan_truyen_qua_nhieu_vong_toi_khi_het_trung(kho):
    """Ghép nhóm có thể sinh va chạm MỚI với tên cuối của hàng thứ ba, rồi
    thứ tư…: lặp tới khi không còn hai kiểu KHÁC nhau chung tên cuối."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "B", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "C", "kieu": [{"kieu": "A couple", "video_ids": ["3"]}]},
        {"nhom": "D", "kieu": [{"kieu": "C A couple", "video_ids": ["4"]}]},
        {"nhom": "E", "kieu": [{"kieu": "D C A couple", "video_ids": ["5"]}]},
        {"nhom": "F", "kieu": [{"kieu": "khác", "video_ids": ["6"]}]},
    ])
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("A", "couple"): "A couple", ("B", "couple"): "B couple",
        ("C", "A couple"): "C A couple", ("D", "C A couple"): "D C A couple",
        ("E", "D C A couple"): "E D C A couple", ("F", "khác"): "khác"}
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom")
    assert ket["trung_cum_co_san"] == [] and _dem(db, "cum") == 6


def test_hai_kieu_khac_nhau_con_trung_ten_ghep_thi_them_hau_to_so_khong_gop(kho):
    """"A"/"B couple" và "A B"/"couple" đều đã ghép nhóm mà vẫn ra cùng "A B
    couple" — luật ghép nhóm hết cách tách. Hai kiểu KHÁC nhau không được âm
    thầm gộp một cụm: hàng đứng sau (theo `thu_tu`, `id`) thêm hậu tố số
    " 2". Duyệt hết ra 3 cụm riêng, không hỏi gộp."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "B couple", "video_ids": ["1"]}]},
        {"nhom": "A B", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "B", "kieu": [{"kieu": "couple", "video_ids": ["3"]}]},
    ])
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("A", "B couple"): "A B couple", ("A B", "couple"): "A B couple 2",
        ("B", "couple"): "B couple"}
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom")
    assert ket["trung_cum_co_san"] == [] and ket["loi_ten"] == []
    assert len({k["cum_id"] for k in ket["cum"]}) == 3 and _dem(db, "cum") == 3


def test_hau_to_so_bo_qua_ten_da_co_san_trong_luot(kho):
    """Hậu tố không được đâm vào một tên đã có: kiểu đơn "A B couple 2" có
    sẵn ⇒ hàng cần hậu tố nhận " 3", và không kiểu nào còn chung tên."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "B couple", "video_ids": ["1"]}]},
        {"nhom": "A B", "kieu": [{"kieu": "couple", "video_ids": ["2"]}]},
        {"nhom": "B", "kieu": [{"kieu": "couple", "video_ids": ["3"]}]},
        {"nhom": "C", "kieu": [{"kieu": "A B couple 2", "video_ids": ["4"]}]},
    ])
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("A", "B couple"): "A B couple", ("A B", "couple"): "A B couple 3",
        ("B", "couple"): "B couple", ("C", "A B couple 2"): "A B couple 2"}
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom")
    assert ket["trung_cum_co_san"] == [] and _dem(db, "cum") == 4


def _doi_ten_ra_couple_trung_ca_ten_ghep(db, job, x_truoc: bool, them: list[dict] = ()):
    """Lượt có "C"/"A B couple" (Y) và "D"/"couple" (W) đã chốt tên, cộng "A
    B"/"cartoon" (X) đứng TRƯỚC hoặc SAU Y trong `thu_tu`; đổi X thành
    "couple": tên trần trùng W, tên ghép "A B couple" trùng Y."""
    x = {"nhom": "A B", "kieu": [{"kieu": "cartoon", "video_ids": ["1"]}]}
    yw = [{"nhom": "C", "kieu": [{"kieu": "A B couple", "video_ids": ["2"]}]},
          {"nhom": "D", "kieu": [{"kieu": "couple", "video_ids": ["3"]}]}, *them]
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [x, *yw] if x_truoc else [*yw, x])
    truoc = _ten_cum_theo_nhom_kieu(db, lan_id)
    x_id = next(k["cum_nhap_id"] for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]
                if k["nhom"] == "A B")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=x_id, kieu="couple")
    return lan_id, truoc


def test_doi_ten_hang_dung_sau_nhan_hau_to_hang_khac_giu_ten_va_hoan_tac_tra_lai_dung(kho):
    """X đứng SAU Y: tên trần và tên ghép của X đều trùng tên đã chốt của hàng
    khác ⇒ X nhận hậu tố " 2"; Y và W giữ nguyên. Hoàn tác trả lại đúng."""
    db, job = kho
    lan_id, truoc = _doi_ten_ra_couple_trung_ca_ten_ghep(db, job, x_truoc=False)
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("C", "A B couple"): "A B couple", ("D", "couple"): "couple",
        ("A B", "couple"): "A B couple 2"}
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == truoc


def test_doi_ten_hang_dung_truoc_van_la_hang_nhan_hau_to_bo_qua_ten_co_san(kho):
    """X đứng TRƯỚC Y trong `thu_tu` — vẫn CHỈ X đổi (thứ tự không quyết định
    ai nhường), và hậu tố bỏ qua tên đã có "A B couple 2" ⇒ " 3"."""
    db, job = kho
    them = [{"nhom": "E", "kieu": [{"kieu": "A B couple 2", "video_ids": ["4"]}]}]
    lan_id, truoc = _doi_ten_ra_couple_trung_ca_ten_ghep(db, job, x_truoc=True, them=them)
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("C", "A B couple"): "A B couple", ("D", "couple"): "couple",
        ("E", "A B couple 2"): "A B couple 2", ("A B", "couple"): "A B couple 3"}
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom")
    assert ket["trung_cum_co_san"] == [] and _dem(db, "cum") == 4


def test_doi_ten_thanh_bien_the_hoa_thuong_cung_nhom_thi_lay_dung_ten_de_tu_gop(kho):
    """Đổi thành biến thể hoa/thường của một kiểu CÙNG nhóm (cùng một kiểu) ⇒
    hàng vừa đổi lấy ĐÚNG tên đã chốt của kiểu đó, không hậu tố — lúc duyệt
    hai hàng tự gộp một cụm."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "Vest", "kieu": [{"kieu": "couple", "video_ids": ["1"]},
                                  {"kieu": "cartoon", "video_ids": ["2"]}]},
        {"nhom": "Đồng phục", "kieu": [{"kieu": "couple", "video_ids": ["3"]}]},
    ])
    x_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=x_id, kieu="Couple")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("Vest", "couple"): "Vest couple", ("Vest", "Couple"): "Vest couple",
        ("Đồng phục", "couple"): "Đồng phục couple"}
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Motion", "Strom")
    assert ket["trung_cum_co_san"] == [] and _dem(db, "cum") == 2

def test_doi_ten_chi_doi_ten_hang_vua_doi_khong_lan_sang_hang_khac(kho):
    """Đổi tên CHỈ đổi `ten_cum` của hàng vừa đổi: "cartoon"→"couple" trùng
    tên đã chốt "couple" của "A"/"couple" ⇒ hàng vừa đổi ghép nhóm thành "C
    couple"; "A"/"couple" và "B"/"A couple" giữ nguyên tên (không lan tiền tố
    sang hàng khác). Hàng không dính va chạm cũng giữ tên."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "A", "kieu": [{"kieu": "couple", "video_ids": ["1"]}]},
        {"nhom": "B", "kieu": [{"kieu": "A couple", "video_ids": ["2"]}]},
        {"nhom": "C", "kieu": [{"kieu": "cartoon", "video_ids": ["3"]},
                               {"kieu": "dance", "video_ids": ["4"]}]},
    ])
    id_cua = {(k["nhom"], k["kieu"]): k["cum_nhap_id"]
              for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=id_cua[("C", "cartoon")],
                            kieu="couple")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("A", "couple"): "couple", ("B", "A couple"): "A couple",
        ("C", "couple"): "C couple", ("C", "dance"): "dance"}
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == {
        ("A", "couple"): "couple", ("B", "A couple"): "A couple",
        ("C", "cartoon"): "cartoon", ("C", "dance"): "dance"}

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
    """`doi_ten` "cartoon"→"dance" va chạm với "dance" có sẵn ⇒ CHỈ hàng vừa
    đổi ghép nhóm ("C dance"), "dance" giữ nguyên. Hoàn tác phải trả lại
    ĐÚNG tên cũ — kể cả một hàng không liên quan mà tên đã chốt ("A couple",
    còn tiền tố dù anh em "B couple" đã bị xoá) khác với cái một lần tính lại
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
        ("A", "couple"): "A couple", ("C", "dance"): "C dance", ("D", "dance"): "dance"}

    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert _ten_cum_theo_nhom_kieu(db, lan_id) == truoc


def test_duyet_kieu_id_khong_thuoc_luot_khong_ghi_doi_insight(kho):
    """`duyet_kieu` với `cum_nhap_id` không thuộc lượt trả `None` (404) và
    KHÔNG được để lại gì — kể cả `doi_insight` đi kèm trong body: kiểm id
    TRƯỚC khi ghi usecase/insight vào `chia_lan`/`jobs`/nhật ký."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    assert models_chia.duyet_kieu(db, lan_id, 987654, TOI, TOI, "Motion", "Strom") is None
    assert _thao_tac(db, lan_id) == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT usecase, insight_goc FROM jobs WHERE id = ?",
                            (job,)).fetchone() == (None, None)
        assert conn.execute("SELECT usecase, insight_goc FROM chia_lan WHERE id = ?",
                            (lan_id,)).fetchone() == (None, None)


# --- tach: tạo kiểu MỚI từ video chọn tay (phase 3+4) --------------------------

def test_tach_tao_kieu_moi_va_chuyen_video(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["1", "3"],
                                  nhom="mới", kieu="tách riêng")
    assert ket["so_video"] == 2
    chia = models_chia.lay_chia(db, lan_id, TOI)
    moi = next(k for k in chia["kieu"] if k["kieu"] == "tách riêng")
    assert sorted(moi["video_ids"]) == ["1", "3"] and moi["nhom"] == "mới"
    couple = next(k for k in chia["kieu"] if k["kieu"] == "couple")
    cartoon = next(k for k in chia["kieu"] if k["kieu"] == "cartoon")
    assert couple["video_ids"] == ["2"] and cartoon["video_ids"] == ["4"]
    assert [h["loai"] for h in _thao_tac(db, lan_id)] == ["tach"], "MỘT dòng nhật ký"


def test_tach_tu_choi_video_ids_rong_hoac_kieu_rong(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    with pytest.raises(ValueError):
        models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=[], nhom="n", kieu="k")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["1"], nhom="n", kieu="   ")
    assert ket == {"tu_choi": "khong_hop_le"}
    assert _thao_tac(db, lan_id) == []


def test_hoan_tac_tach_xoa_hang_moi_va_tra_video_ve_cho_cu(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    truoc = _dem(db, "cum_nhap")
    models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["1"], nhom="mới", kieu="riêng")
    assert _dem(db, "cum_nhap") == truoc + 1
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket["so_video"] == 1
    assert _dem(db, "cum_nhap") == truoc, "hàng mới PHẢI bị xoá, không chỉ trống video"
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert "riêng" not in [k["kieu"] for k in chia["kieu"]]
    assert sorted(next(k["video_ids"] for k in chia["kieu"] if k["cum_nhap_id"] == couple_id)) \
        == ["1", "2"]


# --- gop_nhom: gộp NHIỀU kiểu vào MỘT kiểu đích trong MỘT cú bấm (D15) --------

def _de_xuat_3_kieu(db, job, chu=TOI):
    lan_id = models_chia.tao_chia_lan(db, job, chu, "p1")
    models_chia.ghi_de_xuat(db, lan_id, chu, [
        {"nhom": "n", "kieu": [
            {"kieu": "a", "video_ids": ["1"]},
            {"kieu": "b", "video_ids": ["2"]},
            {"kieu": "c", "video_ids": ["3"]},
        ]},
    ])
    return lan_id


def test_gop_nhom_gop_nhieu_kieu_mot_dong_nhat_ky(kho):
    db, job = kho
    lan_id = _de_xuat_3_kieu(db, job)
    a_id, b_id, c_id = (_nhom_id(db, lan_id, k) for k in ("a", "b", "c"))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "gop_nhom",
                                  cum_nhap_ids=[a_id, b_id], den_cum_nhap_id=c_id)
    assert ket["so_video"] == 2
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert [k["cum_nhap_id"] for k in chia["kieu"]] == [c_id]
    assert sorted(chia["kieu"][0]["video_ids"]) == ["1", "2", "3"]
    assert [h["loai"] for h in _thao_tac(db, lan_id)] == ["gop_nhom"], "MỘT dòng, không phải N"


def test_gop_nhom_tu_choi_khi_mot_nguon_khong_thuoc_luot(kho):
    """VALIDATE mọi nguồn TRƯỚC khi đổi bất cứ gì — một nguồn giả ⇒ từ chối CẢ
    thao tác, không gộp phần còn lại."""
    db, job = kho
    lan_id = _de_xuat_3_kieu(db, job)
    a_id, c_id = _nhom_id(db, lan_id, "a"), _nhom_id(db, lan_id, "c")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "gop_nhom",
                                  cum_nhap_ids=[a_id, 999999], den_cum_nhap_id=c_id)
    assert ket == {"tu_choi": "khong_hop_le"}
    assert _thao_tac(db, lan_id) == []
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert sorted(k["kieu"] for k in chia["kieu"]) == ["a", "b", "c"], "KHÔNG gộp một phần"


def test_hoan_tac_gop_nhom_khoi_phuc_tat_ca(kho):
    db, job = kho
    lan_id = _de_xuat_3_kieu(db, job)
    a_id, b_id, c_id = (_nhom_id(db, lan_id, k) for k in ("a", "b", "c"))
    truoc = _dem(db, "cum_nhap")
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop_nhom",
                            cum_nhap_ids=[a_id, b_id], den_cum_nhap_id=c_id)
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket["so_video"] == 2
    assert _dem(db, "cum_nhap") == truoc
    chia = models_chia.lay_chia(db, lan_id, TOI)
    nhoms = {k["kieu"]: sorted(k["video_ids"]) for k in chia["kieu"]}
    assert nhoms == {"a": ["1"], "b": ["2"], "c": ["3"]}


# --- doi_ten_nhom: đổi tên MỘT NHÓM (mọi kiểu của nó), atomic, MỘT dòng ------

def test_doi_ten_nhom_doi_moi_hang_cua_nhom_mot_dong_nhat_ky(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten_nhom",
                                  nhom_cu="trang phục", nhom_moi="Đồng phục")
    assert ket["so_video"] == 4
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert {k["nhom"] for k in chia["kieu"]} == {"Đồng phục"}
    assert [h["loai"] for h in _thao_tac(db, lan_id)] == ["doi_ten_nhom"], "MỘT dòng, không phải N"


def test_doi_ten_nhom_khong_dung_den_ten_hang_ngoai_nhom(kho):
    """D19: chỉ hàng của NHÓM bị đổi tên tính lại `ten_cum` — hàng của nhóm
    khác giữ nguyên `nhom`/`ten_cum`."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["1"], nhom="khác nhóm", kieu="rieng")
    truoc = next(k for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"] if k["kieu"] == "rieng")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten_nhom",
                            nhom_cu="trang phục", nhom_moi="Đồng phục")
    sau = next(k for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"] if k["kieu"] == "rieng")
    assert (sau["nhom"], sau["ten_cum"]) == (truoc["nhom"], truoc["ten_cum"])


def test_doi_ten_nhom_tu_choi_khi_khong_co_hang_khop_hoac_ten_rong(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten_nhom",
                                  nhom_cu="không tồn tại", nhom_moi="x")
    assert ket == {"tu_choi": "khong_hop_le"}
    ket2 = models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten_nhom",
                                   nhom_cu="trang phục", nhom_moi="   ")
    assert ket2 == {"tu_choi": "khong_hop_le"}
    assert _thao_tac(db, lan_id) == [], "không có dòng nhật ký nào khi từ chối"


def test_doi_ten_nhom_so_dung_chinh_xac_khong_casefold(kho):
    """`doi_ten_nhom` phải so ĐÚNG chuỗi tên nhóm — như trang JS gom nhóm
    (`nhomsOf`: `k.nhom === nhom`), KHÔNG casefold. Nháp có hai nhóm "tp" và
    "TP" (hai thẻ RIÊNG trên UI) — đổi tên "tp" không được đụng tới "TP"."""
    db, job = kho
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "tp", "kieu": [{"kieu": "a", "video_ids": ["1", "2"]}]},
        {"nhom": "TP", "kieu": [{"kieu": "b", "video_ids": ["3"]}]},
    ])
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten_nhom",
                                  nhom_cu="tp", nhom_moi="z")
    assert ket["so_video"] == 2, "chỉ 2 video của nhóm 'tp' bị đổi, không phải cả 3"
    chia = models_chia.lay_chia(db, lan_id, TOI)
    nhoms = {k["kieu"]: k["nhom"] for k in chia["kieu"]}
    assert nhoms == {"a": "z", "b": "TP"}, "'TP' phải giữ nguyên, không bị gộp theo casefold"

    ket2 = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket2["so_video"] == 2
    chia2 = models_chia.lay_chia(db, lan_id, TOI)
    nhoms2 = {k["kieu"]: k["nhom"] for k in chia2["kieu"]}
    assert nhoms2 == {"a": "tp", "b": "TP"}, "hoan_tac phải trả lại đúng 'tp', không đụng 'TP'"


def test_hoan_tac_doi_ten_nhom_khoi_phuc_tat_ca(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    truoc = {k["kieu"]: (k["nhom"], k["ten_cum"])
             for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten_nhom",
                            nhom_cu="trang phục", nhom_moi="Đồng phục")
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert ket["so_video"] == 4
    sau = {k["kieu"]: (k["nhom"], k["ten_cum"])
           for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]}
    assert sau == truoc, "hoan_tac phải trả lại ĐÚNG nhom + ten_cum của MỌI hàng bị đổi"


# --- huy_luot: huỷ lượt, KHÔNG hoàn tác được, cho phép cả sau duyệt một phần --

def test_huy_luot_dat_trang_thai_huy_khong_hoan_tac_duoc(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "huy_luot")
    assert ket["so_video"] == 0
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "huy"
    with pytest.raises(ValueError, match="huy"):
        models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")


def test_huy_luot_cho_phep_sau_khi_duyet_mot_phan(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "de_xuat", "còn 'cartoon'"
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "huy_luot")
    assert ket is not None
    assert models_chia.lay_chia(db, lan_id, TOI)["trang_thai"] == "huy"


def test_nhap_de_xuat_mo_luot_moi_sau_khi_huy(kho):
    db, job = kho
    lan1 = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan1, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "a", "video_ids": ["1"]}]}])
    models_chia.ap_thao_tac(db, lan1, TOI, "huy_luot")
    ket = models_chia.nhap_de_xuat(db, job, "p1", None,
                                   [{"nhom": "n", "kieu": [{"kieu": "b", "video_ids": ["2"]}]}],
                                   [], [], [])
    assert ket["tao_moi"] is True and ket["chia_lan_id"] != lan1
    chia_moi = models_chia.lay_chia(db, ket["chia_lan_id"], TOI)
    assert [k["kieu"] for k in chia_moi["kieu"]] == ["b"]
    assert models_chia.lay_chia(db, lan1, TOI)["trang_thai"] == "huy", "lượt cũ giữ nguyên"


# --- duyet với gop_vao_cum_id: gộp vào cụm có sẵn TÊN KHÁC (D13 không bắt) ----

def test_duyet_kieu_gop_vao_cum_id_chuyen_video_vao_cum_co_san(kho):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Khac han", "khac")
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    ket = models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum",
                                 gop_vao_cum_id=cum_id)
    assert ket["cum_id"] == cum_id and ket["da_co"] is True
    assert sorted(ket["gan"]) == ["1", "2"]
    with sqlite3.connect(db) as conn:
        vc = {r[0] for r in conn.execute("SELECT video_id FROM video_cum WHERE cum_id = ?",
                                         (cum_id,))}
    assert vc == {"1", "2"}
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert "couple" not in [k["kieu"] for k in chia["kieu"]]
    hang = _thao_tac(db, lan_id)
    assert hang[-1]["loai"] == "duyet_kieu"
    assert json.loads(hang[-1]["chi_tiet_json"])["cum_id"] == cum_id, "id đích PHẢI có trong log"


def test_duyet_gop_vao_cum_id_tu_choi_cum_khong_thuoc_chu(kho):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, HO, "Dance", "Khac han", "khac")
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    with pytest.raises(ValueError, match="không phải của bạn"):
        models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum",
                               gop_vao_cum_id=cum_id)
    assert _dem(db, "video_cum") == 0
    assert _thao_tac(db, lan_id) == [], "không ghi dòng nào khi từ chối"


def test_duyet_gop_vao_cum_id_van_400_khi_insight_trong(kho):
    """D18 (ĐP-169): usecase/insight gốc trống chặn CẢ đường `gop_vao_cum_id`
    y hệt đường thường — không nới lỏng riêng."""
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Khac han", "khac")
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",))
    couple_id = _nhom_id(db, lan_id, "couple")
    with pytest.raises(ValueError, match="usecase/insight gốc"):
        models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "", "", gop_vao_cum_id=cum_id)
    assert _dem(db, "video_cum") == 0


# --- so_thao_tac: bộ đếm nghiệm thu D15 trong GET /chia/{job_id} --------------

def test_lay_chia_tra_so_thao_tac_dung_so_dong(kho):
    """Bộ đếm D15 chỉ đếm dòng SỬA CÁCH CHIA còn "sống" (`da_lui = 0`) của
    THẾ HỆ HIỆN TẠI — trước bản này nó đếm MỌI dòng nhật ký (`chap_nhan` từng
    làm bộ đếm tăng); nay `chap_nhan`/`doi_insight` không tính, `doi_ten`
    tính. `hoan_tac` KHÔNG tự tính — xem `test_so_thao_tac_gop_roi_hoan_tac`."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "chap_nhan", cum_nhap_id=couple_id)
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0, "chap_nhan không đếm"
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_insight", usecase="Motion", insight_goc="Strom Ai")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0, "doi_insight không đếm"
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1, "doi_ten đếm"


def test_so_thao_tac_khong_dem_duyet(kho):
    """`duyet_kieu`/`duyet_het` ghi nhật ký nhưng KHÔNG tính vào D15 — duyệt
    là chốt, không phải sửa cách chia (chia tay cũng phải duyệt)."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0, "duyet_kieu không đếm"
    models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["so_thao_tac"] == 0, "duyet_het không đếm"
    assert chia["trang_thai"] == "da_duyet"


def test_so_thao_tac_gop_roi_hoan_tac_ve_0(kho):
    """`gop` rồi `hoan_tac` ⇒ bộ đếm về 0 — `hoan_tac` không tự tính (nó
    không nằm trong `_HOAN_TAC_DUOC`), và dòng `gop` bị nó đánh `da_lui = 1`
    cũng rơi khỏi bộ đếm. `gop` lại sau đó ⇒ đếm lại từ 1 (dòng MỚI còn
    sống)."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop", tu_cum_nhap_id=couple_id,
                            den_cum_nhap_id=cartoon_id)
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0, \
        "hoan_tac không tự đếm, và gop bị nó lùi cũng không còn đếm"
    models_chia.ap_thao_tac(db, lan_id, TOI, "gop", tu_cum_nhap_id=couple_id,
                            den_cum_nhap_id=cartoon_id)
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1, \
        "gop lại sau khi hoàn tác vẫn đếm (dòng mới, còn sống)"


def test_so_thao_tac_khong_dem_the_he_cu_sau_ghi_de_xuat(kho):
    """Một `doi_ten` (sửa cách chia) ở thế hệ CŨ không được đếm sau khi
    `ghi_de_xuat` mở thế hệ MỚI — bộ đếm chỉ soi thế hệ HIỆN TẠI (`the_he`),
    không lùi xuyên thế hệ, đúng luật `hoan_tac` cũng phải theo."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "trang phục", "kieu": [{"kieu": "y", "video_ids": ["1", "2"]}]}])
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0, \
        "dòng của thế hệ cũ không được đếm sau khi ghi đề xuất mới"


def test_so_thao_tac_khong_tut_ve_0_sau_duyet_mot_phan(kho):
    """`so_thao_tac` KHÔNG được tụt về 0 sau khi duyệt MỘT PHẦN (khác thế hệ
    cũ bị GHI ĐÈ ở test trên) — `duyet_kieu`/`duyet_het` bump `the_he` (để
    khoá hoàn tác xuyên qua duyệt) nhưng KHÔNG bump `the_he_nhap` (không mở
    nháp mới), nên công sửa TRƯỚC lúc duyệt vẫn phải còn được đếm."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    cartoon_id = _nhom_id(db, lan_id, "cartoon")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1

    models_chia.duyet_kieu(db, lan_id, cartoon_id, TOI, None, "Dance", "Badaboum")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1, \
        "duyệt MỘT kiểu KHÁC không được xoá công đã sửa ở kiểu còn lại"

    x_id = _nhom_id(db, lan_id, "x")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=x_id, kieu="y")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 2, \
        "sửa TRƯỚC + sửa SAU một lần duyệt một phần đều phải được đếm"


def test_so_thao_tac_dem_du_sau_duyet_het_toan_bo(kho):
    """3 lần sửa rồi `duyet_het` xong CẢ LƯỢT (không còn kiểu nào ở nháp,
    `trang_thai` chuyển `da_duyet`) — bộ đếm vẫn phải giữ nguyên 3, không tụt
    về 0 (đây là con số D15 hiển thị "N thao tác sửa" ở màn đã duyệt)."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    x_id = _nhom_id(db, lan_id, "x")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=x_id, kieu="y")
    y_id = _nhom_id(db, lan_id, "y")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=y_id, kieu="z")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 3

    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert len(ket["cum"]) == 2, "cả hai kiểu còn lại (z + cartoon) phải được duyệt hết"
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["trang_thai"] == "da_duyet"
    assert chia["so_thao_tac"] == 3, "duyệt hết cả lượt không được xoá công đã sửa trước đó"


def test_the_he_nhap_bump_cung_gia_tri_moi_voi_the_he_khi_ghi_de(kho):
    """`ghi_de_xuat` (gọi TRỰC TIẾP — mô phỏng đường nhập đè nháp, khác
    `test_so_thao_tac_khong_dem_the_he_cu_sau_ghi_de_xuat` ở chỗ test này đo
    thêm CẢ giá trị cột lẫn công sửa SAU lần ghi đè): phải bump CẢ `the_he`
    VÀ `the_he_nhap` lên CÙNG một giá trị mới — dòng sửa của thế hệ CŨ (trước
    khi ghi đè) không còn được đếm sau đó dù `da_lui = 0`, và một sửa MỚI
    (sau khi ghi đè) phải đếm lại từ 1."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1

    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "trang phục", "kieu": [{"kieu": "moi", "video_ids": ["1", "2"]}]}])
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        hang = conn.execute("SELECT the_he, the_he_nhap FROM chia_lan WHERE id = ?",
                            (lan_id,)).fetchone()
    assert hang["the_he"] == hang["the_he_nhap"], \
        "the_he_nhap phải bằng the_he NGAY sau khi ghi đè (cùng bump)"
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0, \
        "chưa có sửa nào ở thế hệ MỚI"

    moi_id = _nhom_id(db, lan_id, "moi")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=moi_id, kieu="moi2")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 1, \
        "sửa MỚI (sau ghi đè) đếm lại từ 1 — sửa CŨ không lẫn vào"


def test_the_he_nhap_migration_tu_schema_cu_dem_dung_lich_su(kho):
    """DB có sẵn dữ liệu TỪ TRƯỚC khi có cột `the_he_nhap` (mô phỏng: xoá cột
    sau khi đã có nháp thật + 2 dòng sửa) — mở lại qua `init_db` (đường nâng
    cấp bình thường mọi lần khởi động đều chạy) phải tự thêm cột với giá trị
    MẶC ĐỊNH 0, và bộ đếm D15 phải đếm ĐÚNG toàn bộ lịch sử của nháp đó (nháp
    chưa từng bị `ghi_de_xuat` ghi đè lần hai, nên đếm cả từ đầu là đúng)."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    x_id = _nhom_id(db, lan_id, "x")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=x_id, kieu="y")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 2

    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE chia_lan DROP COLUMN the_he_nhap")
        cot = {r[1] for r in conn.execute("PRAGMA table_info(chia_lan)")}
        assert "the_he_nhap" not in cot, "phép mô phỏng phải thật sự bỏ cột trước khi nâng cấp lại"

    models.init_db(db)   # đường nâng cấp bình thường — chạy mỗi lần khởi động
    with sqlite3.connect(db) as conn:
        cot = {r[1] for r in conn.execute("PRAGMA table_info(chia_lan)")}
        assert "the_he_nhap" in cot, "init_db phải tự thêm lại cột"
        gia_tri = conn.execute("SELECT the_he_nhap FROM chia_lan WHERE id = ?",
                               (lan_id,)).fetchone()[0]
        assert gia_tri == 0, "hàng có TỪ TRƯỚC khi có cột phải nhận mặc định 0"

    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["so_thao_tac"] == 2, "mặc định 0 ⇒ đếm TOÀN BỘ lịch sử của nháp"


# --- nhap_de_xuat: LOAI_CHAN_GHI_DE_NHAP (rộng + khác cách lọc bộ đếm D15) ---

def test_nhap_de_xuat_chi_doi_insight_khong_chan_va_giu_nguyen_insight(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_insight", usecase="Motion",
                            insight_goc="Strom Ai")
    ket = models_chia.nhap_de_xuat(
        db, job, "p2", None,
        [{"nhom": "trang phục", "kieu": [{"kieu": "moi", "video_ids": ["1", "2"]}]}],
        [], [], [])
    assert ket is not None and ket["tao_moi"] is False and ket["chia_lan_id"] == lan_id
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert (chia["usecase"], chia["insight_goc"]) == ("Motion", "Strom Ai"), \
        "insight đã điền qua doi_insight phải được GIỮ NGUYÊN khi ghi đè nháp"
    assert [k["kieu"] for k in chia["kieu"]] == ["moi"], "nháp mới đã thay nháp cũ"


def test_nhap_de_xuat_chan_khi_co_dong_sua_cach_chia(kho):
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    with pytest.raises(models_chia.NhapBiChan):
        models_chia.nhap_de_xuat(db, job, "p2", None, [], [], [], [])


def test_nhap_de_xuat_chan_khi_da_duyet_mot_phan(kho):
    """Duyệt MỘT kiểu (kiểu khác còn ở lại nháp, không sửa gì khác) vẫn phải
    chặn ghi đè — công duyệt là công người dùng đã bỏ ra, và `duyet_kieu`
    luôn tự bump `the_he` ngay sau khi ghi nên KHÔNG được lọc theo thế hệ
    hiện tại (khác bộ đếm D15) — lọc theo thế hệ sẽ bỏ sót đúng ca này."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.duyet_kieu(db, lan_id, couple_id, TOI, None, "Dance", "Badaboum")
    with pytest.raises(models_chia.NhapBiChan):
        models_chia.nhap_de_xuat(db, job, "p2", None, [], [], [], [])


def test_nhap_de_xuat_chan_ngay_ca_khi_sua_da_bi_hoan_tac(kho):
    """`tach` rồi `hoan_tac` lùi lại — vẫn phải chặn ghi đè: người dùng ĐÃ
    sửa tay, không phải một nháp còn trắng — cửa chặn KHÔNG lọc `da_lui`
    (khác bộ đếm D15, vốn coi dòng đã lùi là không còn sống)."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    models_chia.ap_thao_tac(db, lan_id, TOI, "tach", video_ids=["1"], nhom="mới", kieu="riêng")
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert models_chia.lay_chia(db, lan_id, TOI)["so_thao_tac"] == 0, "đã lùi nên bộ đếm hiển thị = 0"
    with pytest.raises(models_chia.NhapBiChan):
        models_chia.nhap_de_xuat(db, job, "p2", None, [], [], [], [])


def test_nhap_de_xuat_chan_dua_tren_dong_da_lui_du_khong_co_dong_hoan_tac_song(kho):
    """Cô lập điều kiện `da_lui = 1` KHÔNG bị lọc bỏ ở cửa chặn: chèn thẳng
    MỘT dòng `tach` đã bị đánh `da_lui = 1`, KHÔNG kèm dòng `hoan_tac` nào —
    khác test trên (nơi dòng `hoan_tac` SỐNG cũng đủ tự chặn), test này buộc
    quyết định phải dựa đúng vào việc dòng `da_lui = 1` có được tính hay
    không."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO thao_tac_duyet (chia_lan_id, chu, loai, so_video, chi_tiet_json, luc, "
            "the_he, da_lui) VALUES (?, ?, 'tach', 1, '{}', '2020-01-01T00:00:00+00:00', 0, 1)",
            (lan_id, TOI))
    with pytest.raises(models_chia.NhapBiChan):
        models_chia.nhap_de_xuat(db, job, "p2", None, [], [], [], [])


def test_nhap_de_xuat_chan_khi_duyet_het_mot_phan_do_trung_cum_co_san(kho):
    """`duyet_het` khi MỘT kiểu trùng tên một cụm THẬT có sẵn (chưa xác nhận
    gộp): kiểu đó ở lại nháp (`trung_cum_co_san`), kiểu KIA vẫn được duyệt
    bình thường — lượt vẫn `de_xuat`. Trước đây bỏ RIÊNG `duyet_het` khỏi
    `LOAI_CHAN_GHI_DE_NHAP` không làm suite nào đỏ — ca thật này (đúng tình
    huống mô tả ở đầu tuple) phải chặn `nhap_de_xuat`: đã có công duyệt thật
    trên lượt, ghi đè nháp là xoá mất công đó."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3", "4"))
    couple_id = _nhom_id(db, lan_id, "couple")
    # Cụm THẬT có sẵn trùng tên với kiểu "couple" (insight_goc="Badaboum") —
    # `duyet_het` sẽ hỏi gộp cho "couple" và để nó Ở LẠI nháp.
    models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    ket = models_chia.duyet_het(db, lan_id, TOI, None, "Dance", "Badaboum")
    assert [t["cum_nhap_id"] for t in ket["trung_cum_co_san"]] == [couple_id]
    assert len(ket["cum"]) == 1, "kiểu 'cartoon' vẫn phải được duyệt bình thường"
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["trang_thai"] == "de_xuat"
    assert [k["kieu"] for k in chia["kieu"]] == ["couple"], "couple còn ở lại nháp chờ xác nhận gộp"
    with pytest.raises(models_chia.NhapBiChan):
        models_chia.nhap_de_xuat(db, job, "p2", None, [], [], [], [])


def test_co_the_hoan_tac_chi_bat_khi_co_thao_tac_lui_duoc(kho):
    """Nút "Hoàn tác" đọc cờ này: nhật ký có dòng (vd `doi_insight`) chưa
    chắc có gì để lùi, nên cờ không được suy từ `so_thao_tac` — càng đúng nay
    khi `doi_insight` không còn tính vào `so_thao_tac`."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job)
    assert models_chia.lay_chia(db, lan_id, TOI)["co_the_hoan_tac"] is False
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_insight", usecase="Motion", insight_goc="Strom Ai")
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["so_thao_tac"] == 0 and chia["co_the_hoan_tac"] is False
    couple_id = _nhom_id(db, lan_id, "couple")
    models_chia.ap_thao_tac(db, lan_id, TOI, "doi_ten", cum_nhap_id=couple_id, kieu="x")
    assert models_chia.lay_chia(db, lan_id, TOI)["co_the_hoan_tac"] is True
    models_chia.ap_thao_tac(db, lan_id, TOI, "hoan_tac")
    assert models_chia.lay_chia(db, lan_id, TOI)["co_the_hoan_tac"] is False


def test_lay_chia_an_video_da_loai_khoi_moi_lan(kho):
    """Video người dùng đã LOẠI khỏi thư viện (`/videos/loai`, kể cả bấm từ làn
    Nghi/Hướng dẫn của màn chia) phải biến khỏi mọi làn của lượt ĐÃ có — cùng
    luật `DIEU_KIEN_VAO_LUOT_CHIA` áp cho lượt mới."""
    db, job = kho
    lan_id = _de_xuat_2_kieu(db, job, a=("1", "2"), b=("3",), huong_dan=["5", "6"])
    truoc = models_chia.lay_chia(db, lan_id, TOI)
    assert truoc["huong_dan"] == ["5", "6"] and truoc["kieu"][0]["video_ids"] == ["1", "2"]   # đối chứng

    models.danh_dau_da_loai(db, "5", TOI)
    models.danh_dau_da_loai(db, "1", TOI)
    sau = models_chia.lay_chia(db, lan_id, TOI)
    assert sau["huong_dan"] == ["6"]
    assert sau["kieu"][0]["video_ids"] == ["2"]
    assert sau["bi_bo"] == [], "đã loại không phải 'lạc'"
