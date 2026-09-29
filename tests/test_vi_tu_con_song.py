"""Vị từ "còn sống" — một nơi duy nhất, và 11 chỗ dùng nó.

Bốn video mẫu trong `kho`:
  "1" còn sống · "2" đã vào bộ, đang ẩn (`an_luc`) · "3" đã dọn khỏi Drive
  (`drive_don_luc`) · "4" người dùng đã loại (`da_loai_luc`). "5", "6" còn sống.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from web import models, models_chia, models_cum
from web import vi_tu_con_song

TOI = "toi@astronex.ai"
LUC = "2026-09-29T01:00:00+00:00"
GOC = Path(__file__).resolve().parent.parent


@pytest.fixture
def kho(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 6, TOI)
    for vid in ("1", "2", "3", "4", "5", "6"):
        models.record_video(db, job_id=job, video_id=vid, url=f"u{vid}")
    an(db, "2")
    don(db, "3")
    models.danh_dau_da_loai(db, "4", TOI)
    return db, job


def an(db, vid):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc) VALUES (?, ?)", (vid, LUC))


def don(db, vid, ly_do="da_don"):
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc, drive_don_luc, ly_do_don) "
                  "VALUES (?, ?, ?, ?)", (vid, LUC, LUC, ly_do))


def _de_xuat(db, job, a, b=("6",), huong_dan=None):
    lan_id = models_chia.tao_chia_lan(db, job, TOI, "p1")
    models_chia.ghi_de_xuat(db, lan_id, TOI, [
        {"nhom": "n", "kieu": [{"kieu": "couple", "video_ids": list(a)},
                               {"kieu": "cartoon", "video_ids": list(b)}]}],
        huong_dan=huong_dan)
    return lan_id


def _kieu_id(db, lan_id, kieu):
    return next(k["cum_nhap_id"] for k in models_chia.lay_chia(db, lan_id, TOI)["kieu"]
                if k["kieu"] == kieu)


# --- quét mã nguồn ----------------------------------------------------------

_CAU_LOAI = re.compile(r"da_loai_luc\s+IS\s+(NOT\s+)?NULL", re.IGNORECASE)


def _tep_ma_nguon():
    ra = []
    for thu_muc in ("web", "src"):
        ra += [p for p in (GOC / thu_muc).rglob("*.py") if "__pycache__" not in p.parts]
    return ra


def test_khong_con_da_loai_luc_is_null_ngoai_tep_vi_tu():
    vi_pham = [f"{p.relative_to(GOC)}:{n}" for p in _tep_ma_nguon()
               if p.name != "vi_tu_con_song.py"
               for n, dong in enumerate(p.read_text().splitlines(), 1) if _CAU_LOAI.search(dong)]
    assert vi_pham == [], f"viết lại điều kiện 'loại' ngoài hằng dùng chung: {vi_pham}"


def test_bo_quet_thay_duoc_ca_duong_tinh_va_ca_dang_viet_khac():
    """Đối chứng dương: bộ quét phải BẮT được mẫu xấu, kể cả xuống dòng/chữ thường."""
    assert _CAU_LOAI.search("WHERE v.da_loai_luc IS NULL")
    assert _CAU_LOAI.search("and da_loai_luc  is not   null")
    assert _CAU_LOAI.search(Path(vi_tu_con_song.__file__).read_text())


# --- từng chỗ dùng ------------------------------------------------------------

def test_thu_vien_list_va_count_giu_video_an_bo_video_da_don_va_da_loai(kho):
    db, _ = kho
    ids = {v["video_id"] for v in models.list_videos(db, TOI)}
    assert ids == {"1", "2", "5", "6"}
    assert models.count_videos(db, TOI) == 4


def test_video_de_loai_khong_nhan_video_da_don(kho):
    db, _ = kho
    got = {h["video_id"] for h in models.video_de_loai(db, ["1", "2", "3", "4"], TOI)}
    assert got == {"1", "2"}, "tab cũ bấm Loại lên video đã dọn không được trash lần hai"


def test_known_video_ids_van_tra_moi_video_ke_ca_da_don_va_da_loai(kho):
    db, _ = kho
    assert models.known_video_ids(db, ["1", "2", "3", "4", "zz"]) == {"1", "2", "3", "4"}


def test_gan_video_vao_cum_bo_qua_video_da_don(kho):
    db, _ = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    assert models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "3", "4"]) == ["1", "2"]


def test_dem_video_cua_cum_khong_tinh_video_da_don(kho):
    db, _ = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, TOI, TOI, ["1", "2", "5"])
    assert models_cum.lay_cum(db, cum_id, TOI, TOI)["so_video"] == 3
    don(db, "5")
    assert models_cum.lay_cum(db, cum_id, TOI, TOI)["so_video"] == 2
    assert models_cum.dem_da_vao_cum(db, TOI, TOI) == 2


def test_vao_luot_chia_bo_video_da_vao_bo_da_don_va_da_loai(kho):
    db, job = kho
    with models._connect(db) as conn:
        ids = [r["video_id"] for r in models_chia.video_vao_luot_chia(conn, job)]
        bi_loc = models_chia.dem_bi_loc_theo_ly_do(conn, job)
    assert ids == ["1", "5", "6"]
    assert bi_loc == {"da_loai": 1, "da_vao_bo": 2, "da_don_drive": 1, "da_o_cum": 0}
    # "da_vao_bo" đếm cả video đã dọn (đã dọn ⇒ đã từng vào bộ) — một video trượt hai
    # điều kiện được đếm ở cả hai (hợp đồng của `dem_bi_loc_theo_ly_do`).


def test_lay_chia_an_video_da_don_khoi_moi_lan_va_khong_bao_bi_bo(kho):
    db, job = kho
    lan_id = _de_xuat(db, job, a=("1", "3"), huong_dan=["5"])
    chia = models_chia.lay_chia(db, lan_id, TOI)
    assert chia["kieu"][0]["video_ids"] == ["1"]
    assert chia["bi_bo"] == []


def test_duyet_kieu_bo_qua_video_da_don(kho):
    db, job = kho
    lan_id = _de_xuat(db, job, a=("1", "3"))
    ket = models_chia.duyet_kieu(db, lan_id, _kieu_id(db, lan_id, "couple"), TOI, TOI,
                                 "Dance", "Badaboum")
    assert ket["gan"] == ["1"]


def test_duyet_kieu_gop_vao_cum_co_san_bo_qua_video_da_don(kho):
    db, job = kho
    cum_id, _ = models_cum.tao_cum(db, TOI, "Dance", "Khac han", "khac")
    lan_id = _de_xuat(db, job, a=("1", "3"))
    ket = models_chia.duyet_kieu(db, lan_id, _kieu_id(db, lan_id, "couple"), TOI, TOI,
                                 "Dance", "Badaboum", gop_vao_cum_id=cum_id)
    assert ket["gan"] == ["1"]
    assert "3" in ket["bi_bo"]


def test_thao_tac_theo_id_tu_choi_video_da_don_cung_ma_voi_da_loai(kho):
    db, job = kho
    lan_id = _de_xuat(db, job, a=("1", "3"), huong_dan=["5"])
    ket = models_chia.ap_thao_tac(db, lan_id, TOI, "ngoai_chu_de", video_ids=["3"])
    assert ket == {"tu_choi": "video_da_loai", "video_ids": ["3"]}
