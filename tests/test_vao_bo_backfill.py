"""Backfill md5 "đã vào bộ": dry-run mặc định, `--that` ghi đúng số dry-run báo,
lần hai ghi 0 hàng. Drive luôn là bản giả."""
from __future__ import annotations

import sqlite3

import pytest

from drive_gia_vao_bo import DriveGia
from web import models, vao_bo_cli
from web.vao_bo_backfill import chay_backfill, in_bang

TOI = "toi@astronex.ai"


def fid(i: int) -> str:
    return f"1Src{i:03d}_AbCdEfGhIjKl"


def _dem(db, bang="video_vao_bo"):
    with sqlite3.connect(db) as c:
        return c.execute(f"SELECT COUNT(*) FROM {bang}").fetchone()[0]


@pytest.fixture
def kho(tmp_path):
    """8 video. Kết quả mong đợi của backfill: v1, v2 (hai bộ) khớp; còn lại không."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 8, TOI)
    d = DriveGia(tra_ca_thung_rac=True)
    d.dat_ten_thu_muc("BO1", "N.2809C - Ten")
    d.dat_ten_thu_muc("BO2", "PN.2209E - Khac")
    for i in range(1, 9):
        models.record_video(db, job_id=job, video_id=f"v{i}", url=f"https://t.co/{i}",
                            drive_file_id=fid(i), tao_luc=f"2026-09-01T00:00:0{i}+00:00")
        d.them_nguon(fid(i), md5=f"M{i}", size=f"{1000 + i}")
    d.them_ban("b1", fid(1), folder="BO1", dau=False)                       # khớp
    d.them_ban("b2a", fid(2), folder="BO1", dau=False)                      # khớp, 2 bộ
    d.them_ban("b2b", fid(2), folder="BO2", dau=False)
    # v3: không có bản nào.
    d.them_ban("b4", fid(4), folder="BO1", dau=False, size="1")             # khác size
    d.them_ban("b5", fid(5), folder="BO1", dau=False, md5="SAI")            # khác md5
    d.them_ban("b6", fid(6), folder="BO1", dau=False, trashed=True)         # đã vào thùng rác
    d.them_ban("b7", fid(7), dau=False, parents=["SRC"])                    # cùng folder nguồn
    # v8: chỉ có chính nguồn (tự khớp chính nó) — không được tính.
    return db, d


def test_dry_run_khong_ghi_gi(kho):
    db, d = kho
    truoc = (_dem(db), _dem(db, "video_vao_bo_ban"))
    bc = chay_backfill(db, d, that=False)
    assert (_dem(db), _dem(db, "video_vao_bo_ban")) == truoc == (0, 0)
    assert sorted(m["video_id"] for m in bc.se_danh_dau) == ["v1", "v2"]
    assert bc.da_ghi == 0


def test_that_ghi_dung_so_dry_run_bao_voi_md5_backfill(kho):
    db, d = kho
    du_kien = len(chay_backfill(db, d, that=False).se_danh_dau)
    bc = chay_backfill(db, d, that=True)
    assert bc.da_ghi == du_kien == 2 and _dem(db) == 2
    with sqlite3.connect(db) as c:
        ban = c.execute("SELECT video_id, ban_copy_id, ma_bo, bang_chung FROM video_vao_bo_ban "
                        "ORDER BY ban_copy_id").fetchall()
        moc = c.execute("SELECT video_id, an_luc IS NOT NULL, drive_don_luc, chu "
                        "FROM video_vao_bo ORDER BY video_id").fetchall()
    assert ban == [("v1", "b1", "N.2809C", "md5_backfill"),
                   ("v2", "b2a", "N.2809C", "md5_backfill"),
                   ("v2", "b2b", "PN.2209E", "md5_backfill")]
    assert moc == [("v1", 1, None, TOI), ("v2", 1, None, TOI)]


def test_chay_lan_hai_them_0_dong(kho):
    db, d = kho
    chay_backfill(db, d, that=True)
    truoc = (_dem(db), _dem(db, "video_vao_bo_ban"))
    bc = chay_backfill(db, d, that=True)
    assert bc.da_ghi == 0 and (_dem(db), _dem(db, "video_vao_bo_ban")) == truoc
    assert bc.da_an_tu_truoc == 2 and bc.nguon_ok == 6


def test_khong_ha_tang_dau_nguon_video_da_loai_khong_bi_xet(kho):
    db, d = kho
    models.danh_dau_da_loai(db, "v1", TOI)
    bc = chay_backfill(db, d, that=True)
    assert bc.da_ghi == 1 and _dem(db) == 1


def test_ban_sao_la_nguon_cua_video_khac_khong_tinh(kho):
    """Hai video trùng nội dung không được tự chứng minh cho nhau."""
    db, d = kho
    models.record_video(db, job_id=1, video_id="v9", url="u9", drive_file_id=fid(9))
    d.them_nguon(fid(9), md5="M3", size="1003", parents=("SRC2",))   # cùng nội dung với v3
    bc = chay_backfill(db, d, that=True)
    assert "v3" not in {m["video_id"] for m in bc.se_danh_dau}
    assert "v9" not in {m["video_id"] for m in bc.se_danh_dau}
    assert bc.bo_vi_duong_gia >= 2


def test_loi_doc_drive_thi_khong_ghi_gi(kho):
    db, d = kho
    d.loi[("liet_ke_drive", "D1")] = ConnectionError("sập")
    with pytest.raises(ConnectionError):
        chay_backfill(db, d, that=True)
    assert _dem(db) == 0 == _dem(db, "video_vao_bo_ban")


def test_that_khong_ghi_khi_tra_ten_folder_trượt(kho):
    db, d = kho
    d.loi[("ten_thu_muc", "BO2")] = TimeoutError()
    with pytest.raises(TimeoutError):
        chay_backfill(db, d, that=True)
    assert _dem(db) == 0


def test_bang_in_co_cac_dong_cua_ban_dry_run(kho):
    db, d = kho
    ra = "\n".join(in_bang(chay_backfill(db, d, that=False)))
    for mau in ("video còn sống có drive_file_id: 8", "files.get nguồn OK: 8 · lỗi: 0",
                "số Shared Drive chứa nguồn: 1", "SẼ ĐÁNH DẤU (dry-run): 2 / 8 video nguồn",
                "số folder cha khác nhau của bản sao: 2", "10 mẫu (", "DRY-RUN: KHÔNG ghi gì"):
        assert mau in ra, mau


# --- lệnh quản trị -------------------------------------------------------------

def test_cli_mac_dinh_la_dry_run_khong_ghi(kho, capsys):
    db, d = kho
    rc = vao_bo_cli.main(["backfill", "--db", str(db)], tao_drive=lambda: d)
    assert rc == 0 and _dem(db) == 0
    assert "SẼ ĐÁNH DẤU (dry-run): 2 / 8" in capsys.readouterr().out


def test_cli_that_ghi_dung_so_dry_run_va_lan_hai_them_0(kho, capsys):
    db, d = kho
    assert vao_bo_cli.main(["backfill", "--db", str(db), "--that"], tao_drive=lambda: d) == 0
    assert _dem(db) == 2
    assert "ĐÃ GHI 2 hàng" in capsys.readouterr().out
    assert vao_bo_cli.main(["backfill", "--db", str(db), "--that"], tao_drive=lambda: d) == 0
    assert _dem(db) == 2
    assert "ĐÃ GHI 0 hàng" in capsys.readouterr().out


def test_cli_drive_chua_cau_hinh_thoat_3_khong_lam_gi(kho):
    db, d = kho
    d.cau_hinh = False
    assert vao_bo_cli.main(["backfill", "--db", str(db), "--that"], tao_drive=lambda: d) == 3
    assert d.goi == [] and _dem(db) == 0


def test_cli_loi_drive_thoat_6(kho):
    db, d = kho
    d.loi[("liet_ke_drive", "D1")] = ConnectionError()
    assert vao_bo_cli.main(["backfill", "--db", str(db), "--that"], tao_drive=lambda: d) == 6
    assert _dem(db) == 0
