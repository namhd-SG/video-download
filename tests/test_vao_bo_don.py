"""Dọn ngày thứ 7: tệp nguồn của video đã vào bộ đi vào Thùng rác.

Drive là bản giả (`drive_gia_vao_bo.DriveGia`); test KHÔNG gọi Drive thật.
"""
from __future__ import annotations

import ast
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from drive_gia_vao_bo import DriveGia
from web import models, models_vao_bo
from web.vao_bo_don import chay_luot_don

TOI = "toi@astronex.ai"
BAY_GIO = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
GOC = Path(__file__).resolve().parent.parent


def fid(i: int) -> str:
    return f"1Src{i:03d}_AbCdEfGhIjKl"


def luc(ngay_truoc: float) -> str:
    return (BAY_GIO - timedelta(days=ngay_truoc)).isoformat()


@pytest.fixture
def kho(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 5, TOI)
    return db, job


def an_video(db, job, i, *, ngay=8, bang_chung="properties", ma_bo="N.2809C"):
    """Video `v{i}` đã ẩn `ngay` ngày trước, có một bản sao `ban{i}` ghi trong sổ."""
    models.record_video(db, job_id=job, video_id=f"v{i}", url=f"https://t.co/{i}",
                        drive_file_id=fid(i), tao_luc=f"2026-09-01T00:00:0{i}+00:00")
    models_vao_bo.ghi_da_vao_bo(
        db, f"v{i}", TOI,
        [{"ban_copy_id": f"ban{i}", "folder_id": "BO1", "ma_bo": ma_bo, "bang_chung": bang_chung}],
        luc(ngay))


def drive_dat_bang_chung(*ids, dau=True):
    d = DriveGia()
    for i in ids:
        d.them_nguon(fid(i))
        d.them_ban(f"ban{i}", fid(i), folder="BO1", dau=dau)
    return d


def hang(db, vid):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM video_vao_bo WHERE video_id = ?", (vid,)).fetchone()
    return dict(r) if r else None


def da_trash(d):
    return [a for t, a in d.goi if t == "bo_vao_thung_rac"]


# --- mốc 7 ngày ------------------------------------------------------------------

def test_chua_du_7_ngay_khong_dung_toi_va_khong_goi_drive(kho):
    db, job = kho
    an_video(db, job, 1, ngay=6.99)
    d = drive_dat_bang_chung(1)
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.ung_vien == 0 and d.goi == []
    assert hang(db, "v1")["drive_don_luc"] is None


def test_dung_7_ngay_thi_don(kho):
    db, job = kho
    an_video(db, job, 1, ngay=7)
    d = drive_dat_bang_chung(1)
    assert chay_luot_don(db, d, bay_gio=BAY_GIO).da_bo_thung_rac == 1


# --- đường chính -------------------------------------------------------------------

def test_don_trash_tep_NGUON_chi_khi_ok_roi_moi_ghi_moc(kho):
    db, job = kho
    an_video(db, job, 1)
    d = drive_dat_bang_chung(1)
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.da_bo_thung_rac == 1
    assert da_trash(d) == [fid(1)], "trash nhận id của NGUỒN, không phải id bản sao"
    r = hang(db, "v1")
    assert r["drive_don_luc"] and r["ly_do_don"] == "da_don" and r["so_lan_truot"] == 0
    assert d.tep["ban1"]["trashed"] is False, "không đụng bản trong bộ"
    assert all(a != "ban1" for _, a in d.goi if _ == "bo_vao_thung_rac")


def test_khong_xoa_hang_videos_va_known_video_ids_van_nho(kho):
    db, job = kho
    an_video(db, job, 1)
    chay_luot_don(db, drive_dat_bang_chung(1), bay_gio=BAY_GIO)
    assert models.known_video_ids(db, ["v1"]) == {"v1"}
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM videos WHERE video_id = 'v1'").fetchone()[0] == 1


def test_video_da_don_bien_khoi_luoi_va_chip_da_vao_bo(kho):
    db, job = kho
    an_video(db, job, 1)
    assert {v["video_id"] for v in models.list_videos(db, TOI)} == {"v1"}
    chay_luot_don(db, drive_dat_bang_chung(1), bay_gio=BAY_GIO)
    assert models.list_videos(db, TOI) == []
    assert models_vao_bo.vao_bo_cho_videos(db, ["v1"]) == {}


# --- trash trượt: mốc KHÔNG ghi, báo động MỖI lượt ---------------------------------

def test_trash_truot_khong_ghi_moc_va_bao_dong_moi_luot(kho, caplog):
    db, job = kho
    an_video(db, job, 1)
    d = drive_dat_bang_chung(1)
    d.trash_ket_qua[fid(1)] = False
    with caplog.at_level(logging.ERROR, logger="videodl.web.vao_bo"):
        for lan in (1, 2, 3):
            kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
            assert kq.trash_truot == 1 and kq.da_bo_thung_rac == 0
            r = hang(db, "v1")
            assert r["drive_don_luc"] is None, "mốc không dời khi trash trượt"
            assert r["so_lan_truot"] == lan
    bao = [r for r in caplog.records if r.levelno == logging.ERROR and "BÁO ĐỘNG" in r.getMessage()]
    assert len(bao) == 3, "3 lượt trượt liên tiếp = 3 lần báo"
    assert hang(db, "v1")["an_luc"] == luc(8), "mốc ẩn không dời"


def test_trash_truot_roi_lan_sau_ok_thi_ghi_moc_va_xoa_loi(kho):
    db, job = kho
    an_video(db, job, 1)
    d = drive_dat_bang_chung(1)
    d.trash_ket_qua[fid(1)] = False
    chay_luot_don(db, d, bay_gio=BAY_GIO)
    d.trash_ket_qua[fid(1)] = True
    chay_luot_don(db, d, bay_gio=BAY_GIO)
    r = hang(db, "v1")
    assert r["drive_don_luc"] and r["loi_cuoi"] is None


def test_trash_nem_ngoai_le_cung_la_trượt(kho):
    db, job = kho
    an_video(db, job, 1)
    d = drive_dat_bang_chung(1)
    d.loi[("bo_vao_thung_rac", fid(1))] = TimeoutError()
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.trash_truot == 1 and hang(db, "v1")["drive_don_luc"] is None


# --- kiểm lại bằng chứng ngày 7 ------------------------------------------------------

def test_ban_sao_da_bi_xoa_thi_khong_trash_va_hien_lai_video(kho):
    db, job = kho
    an_video(db, job, 1)
    d = DriveGia()
    d.them_nguon(fid(1))                 # KHÔNG còn bản sao nào
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.hien_lai == 1 and da_trash(d) == []
    assert hang(db, "v1") is None, "hàng sổ xoá ⇒ video hiện lại"
    assert {v["video_id"] for v in models.list_videos(db, TOI)} == {"v1"}
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT COUNT(*) FROM video_vao_bo_ban").fetchone()[0] == 0


def test_khong_do_duoc_thi_giu_nguyen_moc_khong_hien_lai_khong_trash(kho, caplog):
    db, job = kho
    an_video(db, job, 1)
    d = drive_dat_bang_chung(1)
    d.loi[("liet_ke_ban_sao", fid(1))] = ConnectionError("mạng")
    with caplog.at_level(logging.ERROR, logger="videodl.web.vao_bo"):
        kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.khong_do_duoc == 1 and da_trash(d) == []
    r = hang(db, "v1")
    assert r is not None and r["an_luc"] == luc(8), "không reset đồng hồ 7 ngày"
    assert r["so_lan_truot"] == 1 and r["drive_don_luc"] is None
    assert any("BÁO ĐỘNG" in x.getMessage() for x in caplog.records)


def test_ban_backfill_khong_dau_van_duoc_kiem_lai_bang_id_da_ghi(kho):
    db, job = kho
    an_video(db, job, 1, bang_chung="md5_backfill")
    d = drive_dat_bang_chung(1, dau=False)      # bản sao KHÔNG có `properties`
    assert chay_luot_don(db, d, bay_gio=BAY_GIO).da_bo_thung_rac == 1


def test_ban_backfill_da_vao_thung_rac_thi_hien_lai(kho):
    db, job = kho
    an_video(db, job, 1, bang_chung="md5_backfill")
    d = drive_dat_bang_chung(1, dau=False)
    d.tep["ban1"]["trashed"] = True             # vế `trashed=false` khi kiểm lại
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.hien_lai == 1 and da_trash(d) == []


def test_ban_backfill_bi_doi_ve_folder_nguon_thi_hien_lai(kho):
    db, job = kho
    an_video(db, job, 1, bang_chung="md5_backfill")
    d = drive_dat_bang_chung(1, dau=False)
    d.tep["ban1"]["parents"] = ["SRC"]          # vế parent ≠ parent nguồn khi kiểm lại
    assert chay_luot_don(db, d, bay_gio=BAY_GIO).hien_lai == 1


def test_ban_backfill_bi_thay_noi_dung_thi_hien_lai(kho):
    db, job = kho
    an_video(db, job, 1, bang_chung="md5_backfill")
    d = drive_dat_bang_chung(1, dau=False)
    d.tep["ban1"]["md5Checksum"] = "DA_SUA"
    assert chay_luot_don(db, d, bay_gio=BAY_GIO).hien_lai == 1


def test_ban_backfill_bi_doi_size_thi_hien_lai(kho):
    db, job = kho
    an_video(db, job, 1, bang_chung="md5_backfill")
    d = drive_dat_bang_chung(1, dau=False)
    d.tep["ban1"]["size"] = "1"
    assert chay_luot_don(db, d, bay_gio=BAY_GIO).hien_lai == 1


# --- nguồn đã ở Thùng rác / đã mất -----------------------------------------------------

def test_nguon_da_o_thung_rac_ghi_ly_do_khong_goi_trash_khong_bao_dong(kho, caplog):
    db, job = kho
    an_video(db, job, 1)
    d = drive_dat_bang_chung(1)
    d.tep[fid(1)]["trashed"] = True
    with caplog.at_level(logging.ERROR, logger="videodl.web.vao_bo"):
        kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.da_o_thung_rac == 1 and da_trash(d) == []
    assert hang(db, "v1")["ly_do_don"] == "da_o_thung_rac"
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_nguon_404_ghi_khong_con_khong_goi_trash(kho):
    db, job = kho
    an_video(db, job, 1)
    d = DriveGia()
    d.them_ban("ban1", fid(1), md5="M1", size="1000")      # nguồn không còn trong kho
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.khong_con == 1 and da_trash(d) == []
    assert hang(db, "v1")["ly_do_don"] == "khong_con"


# --- video đã Loại tay -----------------------------------------------------------------------

def test_da_loai_tay_trong_7_ngay_ghi_moc_da_loai_khong_goi_drive(kho):
    db, job = kho
    an_video(db, job, 1)
    models.danh_dau_da_loai(db, "v1", TOI)
    d = drive_dat_bang_chung(1)
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.da_loai == 1 and d.goi == [], "không gọi Drive: user untrash tay thì không trash lại"
    r = hang(db, "v1")
    assert r["ly_do_don"] == "da_loai" and r["drive_don_luc"]


# --- chống ghi đôi ------------------------------------------------------------------------------

def test_hai_luot_cung_luc_ghi_moc_don_dung_mot_lan(kho):
    db, job = kho
    an_video(db, job, 1)
    thanh_cong: list[bool] = []
    rao = threading.Barrier(2)

    def chay(ly_do):
        rao.wait()
        thanh_cong.append(models_vao_bo.ghi_don_drive(db, "v1", ly_do, luc(0)))
    ts = [threading.Thread(target=chay, args=(x,)) for x in ("a", "b")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(thanh_cong) == [False, True]
    assert hang(db, "v1")["ly_do_don"] in ("a", "b")


def test_luot_thu_hai_khong_dan_lai_video_da_don(kho):
    db, job = kho
    an_video(db, job, 1)
    d = drive_dat_bang_chung(1)
    chay_luot_don(db, d, bay_gio=BAY_GIO)
    moc = hang(db, "v1")["drive_don_luc"]
    d.goi.clear()
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.ung_vien == 0 and d.goi == [] and hang(db, "v1")["drive_don_luc"] == moc


# --- không bao giờ xoá vĩnh viễn -----------------------------------------------------------------

def _goi_files_delete(ma_nguon: str) -> bool:
    """Có lời gọi `<x>.files().delete(...)` trong mã (AST: bỏ qua chú thích/docstring)."""
    for n in ast.walk(ast.parse(ma_nguon)):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "delete" and isinstance(n.func.value, ast.Call)
                and isinstance(n.func.value.func, ast.Attribute)
                and n.func.value.func.attr == "files"):
            return True
    return False


def test_khong_co_files_delete_o_bat_ky_dau():
    vi_pham = [str(p.relative_to(GOC)) for thu_muc in ("web", "src")
               for p in (GOC / thu_muc).rglob("*.py") if _goi_files_delete(p.read_text())]
    assert vi_pham == []
    assert _goi_files_delete("svc.files().delete(fileId=x).execute()"), \
        "đối chứng dương: bộ quét bắt được mẫu xấu"
    assert not _goi_files_delete('"""không files().delete() ở đâu cả"""')


def test_giao_dien_drive_khong_co_ham_xoa():
    from web.vao_bo_drive import DriveThat
    assert not [n for n in dir(DriveThat) if "delete" in n.lower() or "xoa" in n.lower()]
