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


# --- S6: lưới dương giả dựng từ MỌI nguồn Video Desk -----------------------------------------------

def _them_video_nguon(db, d, i, *, md5, size, parents, da_an=False, da_loai=False, fetch_hong=False):
    models.record_video(db, job_id=1, video_id=f"x{i}", url=f"u{i}", drive_file_id=fid(i),
                        tao_luc=f"2026-09-02T00:00:{i:02d}+00:00")
    d.them_nguon(fid(i), md5=md5, size=size, parents=parents)
    if da_an:
        from web import models_vao_bo
        models_vao_bo.ghi_da_vao_bo(db, f"x{i}", TOI, [{"ban_copy_id": f"k{i}", "folder_id": "F",
                                                        "ma_bo": "N.1", "bang_chung": "properties"}])
    if da_loai:
        models.danh_dau_da_loai(db, f"x{i}", TOI)
    if fetch_hong:
        d.loi[("lay_tep", fid(i))] = ConnectionError("get hỏng")


@pytest.mark.parametrize("cach", ["da_an", "da_loai"])
def test_ban_sao_nam_trong_folder_nguon_cua_video_da_an_hoac_da_loai_khong_tinh(kho, cach):
    """Video A (ứng viên) có một tệp trùng nội dung nằm trong folder đang chứa nguồn của
    video H ĐÃ ẨN / ĐÃ LOẠI. Tệp đó là dương giả — lưới folder phải dựng từ nguồn của MỌI
    video, không chỉ ứng viên đang xét."""
    db, d = kho
    _them_video_nguon(db, d, 20, md5="MH", size="7", parents=("SRC_H",),
                      da_an=cach == "da_an", da_loai=cach == "da_loai")
    _them_video_nguon(db, d, 21, md5="MA", size="9", parents=("SRC",))
    d.them_ban("dup", fid(21), folder="SRC_H", dau=False)          # bản trùng A nằm ở folder của H
    bc = chay_backfill(db, d, that=False)
    assert "x21" not in {m["video_id"] for m in bc.se_danh_dau}
    assert bc.bo_vi_duong_gia >= 1


def test_ban_sao_la_nguon_cua_video_lay_truot_van_bi_loai_theo_id(kho):
    """B có `files.get` nguồn HỎNG ⇒ không biết folder của B; tệp nguồn của B nằm trong danh
    sách Shared Drive và trùng nội dung A. Chỉ lưới theo ID còn che được ca này."""
    db, d = kho
    _them_video_nguon(db, d, 30, md5="MB", size="5", parents=("ODD",), fetch_hong=True)
    _them_video_nguon(db, d, 31, md5="MB", size="5", parents=("SRC",))      # A trùng nội dung B
    bc = chay_backfill(db, d, that=False)
    assert "x31" not in {m["video_id"] for m in bc.se_danh_dau}
    assert bc.nguon_phu_loi >= 0 and bc.nguon_loi >= 1


# --- S7: dry-run mở DB chỉ-đọc, không init_db, thiếu bảng thì dừng sạch ---------------------------

def _sha_thu_muc(thu_muc):
    import hashlib
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(thu_muc.iterdir())}


def test_dry_run_khong_dong_toi_tep_db_ke_ca_khi_db_chua_o_che_do_wal(kho):
    db, d = kho
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA journal_mode=DELETE")       # DB "sạch": không -wal/-shm, tiêu đề không phải WAL
    truoc = _sha_thu_muc(db.parent)
    assert vao_bo_cli.main(["backfill", "--db", str(db)], tao_drive=lambda: d) == 0
    assert _sha_thu_muc(db.parent) == truoc, "dry-run không được đổi byte nào / tạo tệp nào"


def test_dry_run_doc_duoc_db_dang_o_che_do_wal(kho, capsys):
    db, d = kho          # `init_db` để DB ở chế độ WAL — đúng như trên mini
    assert vao_bo_cli.main(["backfill", "--db", str(db)], tao_drive=lambda: d) == 0
    assert "SẼ ĐÁNH DẤU (dry-run): 2 / 8" in capsys.readouterr().out


def test_dry_run_khong_goi_init_db(kho, monkeypatch):
    db, d = kho
    goi = []
    monkeypatch.setattr(models, "init_db", lambda p: goi.append(p))
    assert vao_bo_cli.main(["backfill", "--db", str(db)], tao_drive=lambda: d) == 0
    assert goi == []
    vao_bo_cli.main(["backfill", "--db", str(db), "--that"], tao_drive=lambda: d)
    assert goi == [db], "chỉ --that mới dựng lược đồ"


def test_dry_run_thieu_bang_dung_sach_ma_7_khong_tao_bang(tmp_path, capsys):
    db = tmp_path / "cu.db"
    with sqlite3.connect(db) as c:      # jobs.db đời cũ: có `videos`, chưa có `video_vao_bo`
        c.execute("CREATE TABLE videos (video_id TEXT PRIMARY KEY, drive_file_id TEXT, "
                  "da_loai_luc TEXT, job_id INTEGER, tao_luc TEXT)")
    truoc = _sha_thu_muc(tmp_path)
    d = DriveGia()
    rc = vao_bo_cli.main(["backfill", "--db", str(db)], tao_drive=lambda: d)
    assert rc == 7 and d.goi == []
    assert "video_vao_bo" in capsys.readouterr().err
    assert _sha_thu_muc(tmp_path) == truoc
    with sqlite3.connect(db) as c:
        assert "video_vao_bo" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master")}


def test_dry_run_thieu_tep_db_dung_sach_khong_tao_tep(tmp_path, capsys):
    db = tmp_path / "khong-co.db"
    assert vao_bo_cli.main(["backfill", "--db", str(db)], tao_drive=lambda: DriveGia()) == 7
    assert not db.exists() and list(tmp_path.iterdir()) == []
