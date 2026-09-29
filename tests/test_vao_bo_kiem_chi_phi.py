"""Lượt kiểm 15 phút RẺ: pha (a) chọn ứng viên (A ∪ T ∪ H), pha (b) đo đầy đủ; quét đầy đủ
mỗi ngày VN; pha (a) trượt ⇒ quét đủ.

Drive luôn là bản giả; lỗi 403/404/5xx là `HttpError` GIẢ dựng tại chỗ — không có lời gọi
Drive thật nào và không đụng quyền của Shared Drive / service account thật.
"""
from __future__ import annotations

import logging
import sqlite3
import types
from datetime import datetime, timedelta, timezone

import pytest
from googleapiclient.errors import HttpError

from drive_gia_vao_bo import DriveGia
from web import models, models_vao_bo
from web.vao_bo_kiem import (LY_DO_NGUON_404, LY_DO_NGUON_O_THUNG_RAC, chay_luot_kiem)

TOI = "toi@astronex.ai"
# 12:00 UTC = 19:00 ngày 29/09 giờ VN.
BAY_GIO = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
NGAY_VN = "2026-09-29"


def fid(i: int) -> str:
    return f"1Src{i:04d}_AbCdEfGhIjKl"


def http_loi(status: int) -> HttpError:
    return HttpError(types.SimpleNamespace(status=status, reason="gia"), b"{}")


@pytest.fixture
def kho(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 5, TOI)
    return db, job


def them(db, job, i, *, tao_luc=None):
    models.record_video(db, job_id=job, video_id=f"v{i}", url=f"https://t.co/{i}",
                        drive_file_id=fid(i),
                        tao_luc=tao_luc or f"2026-09-01T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}+00:00")


def da_quet_hom_nay(db):
    models_vao_bo.ghi_ngay_quet_day_du(db, NGAY_VN)


def drive(*, nguon=(), co_ban=(), thung=(), **kw):
    d = DriveGia(**kw)
    d.dat_ten_thu_muc("BO1", "N.2809C - x")
    for i in nguon:
        d.them_nguon(fid(i), trashed=i in thung)
    for i in co_ban:
        d.them_ban(f"ban{i}", fid(i), folder="BO1")
    return d


def da_lay_tep(d) -> set[str]:
    return {a for t, a in d.goi if t == "lay_tep" and a.startswith("1Src")}


def loi_bao_dong(caplog, ly_do):
    return [r for r in caplog.records if r.levelno == logging.ERROR and ly_do in r.getMessage()]


def hang(db):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT video_id, an_luc IS NOT NULL FROM video_vao_bo "
                         "ORDER BY video_id").fetchall()


# --- pha (a) trượt ⇒ quét đủ ------------------------------------------------------------------

@pytest.mark.parametrize("status", [403, 404, 500])
@pytest.mark.parametrize("cho", ["liet_ke_lo", "liet_ke_thung_rac"])
def test_pha_a_nem_http_error_thi_quet_du_pha_b_cho_moi_ung_vien(kho, caplog, status, cho):
    db, job = kho
    for i in (1, 2, 3):
        them(db, job, i)
    da_quet_hom_nay(db)
    d = drive(nguon=(1, 2, 3), co_ban=(1,))
    d.loi[(cho, "*")] = http_loi(status)
    with caplog.at_level(logging.ERROR, logger="videodl.web.vao_bo"):
        kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO)          # KHÔNG được ném
    assert kq.fallback is True and kq.da_xet == 3, "không bỏ sót ứng viên nào"
    assert da_lay_tep(d) == {fid(1), fid(2), fid(3)}, "mọi ứng viên đều được do_bang_chung"
    assert [r for r in caplog.records if r.levelno == logging.ERROR
            and "pha (a)" in r.getMessage() and str(status) in r.getMessage()], \
        "lỗi được log kèm mã HTTP"
    assert hang(db) == [("v1", 1)], "video có bản sao hợp lệ vẫn được ẩn nhờ pha (b)"
    assert kq.chua_co_bang_chung == 2, "hai video kia được ĐO ra chưa có, không phải bị bỏ qua"


def test_pha_a_loi_khong_bi_doc_thanh_am_khong_ghi_bao_dong_oan(kho, caplog):
    db, job = kho
    them(db, job, 1)
    da_quet_hom_nay(db)
    d = drive(nguon=(1,), co_ban=(1,))
    d.loi[("liet_ke_lo", "*")] = http_loi(500)
    chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    assert loi_bao_dong(caplog, LY_DO_NGUON_404) == [] == loi_bao_dong(caplog, LY_DO_NGUON_O_THUNG_RAC)


# --- T và H: ca nguồn chết vẫn báo ở lượt 15 phút -----------------------------------------------

def test_khong_ban_sao_va_nguon_o_thung_rac_van_bao_dong_o_luot_15_phut(kho, caplog):
    db, job = kho
    them(db, job, 1)          # nguồn trong Thùng rác, 0 bản
    them(db, job, 2)          # nguồn sống, 0 bản: KHÔNG được đo ở lượt này
    da_quet_hom_nay(db)
    d = drive(nguon=(1, 2), thung=(1,))
    with caplog.at_level(logging.ERROR, logger="videodl.web.vao_bo"):
        kq1 = chay_luot_kiem(db, d, bay_gio=BAY_GIO)
        kq2 = chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    assert (kq1.n_t, kq1.bao_dong) == (1, 1) and kq2.bao_dong == 1
    assert len(loi_bao_dong(caplog, LY_DO_NGUON_O_THUNG_RAC)) == 2, "mỗi lượt báo lại"
    assert fid(1) in loi_bao_dong(caplog, LY_DO_NGUON_O_THUNG_RAC)[0].getMessage()
    assert da_lay_tep(d) == {fid(1)}, "chỉ ứng viên thuộc T bị đo"


def test_hang_bao_dong_h_van_bao_moi_luot_du_nguon_chi_404(kho, caplog):
    db, job = kho
    them(db, job, 1)           # nguồn 404 (không có trong kho) — pha (a) không thấy được
    them(db, job, 2)
    da_quet_hom_nay(db)
    models_vao_bo.ghi_bao_dong(db, "v1", TOI, LY_DO_NGUON_404)
    d = drive(nguon=(2,))
    with caplog.at_level(logging.ERROR, logger="videodl.web.vao_bo"):
        kqs = [chay_luot_kiem(db, d, bay_gio=BAY_GIO) for _ in range(3)]
    assert [k.n_h for k in kqs] == [1, 1, 1]
    assert len(loi_bao_dong(caplog, LY_DO_NGUON_404)) == 3, "H báo ở MỖI lượt"
    assert da_lay_tep(d) == {fid(1)}, "video 2 (nguồn sống, 0 bản) không bị đo"


# --- chi phí: 0 bản + nguồn sống chỉ được đo ở lượt quét đầy đủ mỗi ngày ------------------------------

def test_nguon_song_khong_ban_sao_khong_bi_lay_o_luot_15_phut_nhung_bi_lay_o_luot_quet_ngay(kho):
    db, job = kho
    them(db, job, 1)
    d = drive(nguon=(1,))
    kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO)                 # lượt đầu trong ngày ⇒ quét đủ
    assert kq.quet_day_du and da_lay_tep(d) == {fid(1)}
    d.goi.clear()
    kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO + timedelta(minutes=15))
    assert not kq.quet_day_du and da_lay_tep(d) == set(), "lượt 15 phút: không đo nguồn sống 0 bản"
    d.goi.clear()
    chay_luot_kiem(db, d, bay_gio=BAY_GIO + timedelta(days=1))  # ngày VN kế tiếp ⇒ quét đủ lại
    assert da_lay_tep(d) == {fid(1)}


def test_khong_gioi_han_theo_tuoi_video(kho):
    db, job = kho
    them(db, job, 1, tao_luc="2001-01-01T00:00:00+00:00")
    them(db, job, 2)
    da_quet_hom_nay(db)
    d = drive(nguon=(1, 2), co_ban=(1,))
    chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    assert hang(db) == [("v1", 1)], "video rất cũ có bản sao vẫn được ẩn"


# --- quét đầy đủ mỗi ngày VN, sống sót qua khởi động lại ---------------------------------------------

def test_quet_day_du_dung_mot_lan_moi_ngay_vn_qua_khoi_dong_lai(kho):
    db, job = kho
    them(db, job, 1)
    d = drive(nguon=(1,))

    def chay(utc):
        # Mỗi lần gọi = "một tiến trình mới": trạng thái chỉ nằm trong DB.
        return chay_luot_kiem(db, d, bay_gio=utc).quet_day_du
    vn = timezone(timedelta(hours=7))
    ngay1_0010 = datetime(2026, 9, 29, 0, 10, tzinfo=vn)
    assert chay(ngay1_0010) is True
    assert chay(ngay1_0010 + timedelta(minutes=15)) is False
    assert chay(datetime(2026, 9, 29, 23, 59, tzinfo=vn)) is False, "23:59 vẫn cùng ngày VN"
    assert chay(datetime(2026, 9, 30, 0, 1, tzinfo=vn)) is True, "00:01 ngày mới: quét lại"
    assert chay(datetime(2026, 9, 30, 0, 16, tzinfo=vn)) is False
    assert models_vao_bo.doc_ngay_quet_day_du(db) == "2026-09-30"


def test_ranh_gioi_ngay_la_gio_VN_khong_phai_UTC(kho):
    db, job = kho
    them(db, job, 1)
    d = drive(nguon=(1,))
    # 16:59 UTC = 23:59 VN ngày 29; 17:01 UTC = 00:01 VN ngày 30 (UTC vẫn là ngày 29).
    assert chay_luot_kiem(db, d, bay_gio=datetime(2026, 9, 29, 16, 59, tzinfo=timezone.utc)).quet_day_du
    assert not chay_luot_kiem(db, d, bay_gio=datetime(2026, 9, 29, 16, 59, tzinfo=timezone.utc)).quet_day_du
    assert chay_luot_kiem(db, d, bay_gio=datetime(2026, 9, 29, 17, 1, tzinfo=timezone.utc)).quet_day_du


def test_quet_bi_dung_giua_chung_khong_ghi_ngay_nen_lan_sau_quet_lai(kho):
    db, job = kho
    for i in (1, 2, 3):
        them(db, job, i)
    d = drive(nguon=(1, 2, 3))
    kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO, dung=lambda: True)
    assert kq.quet_day_du and models_vao_bo.doc_ngay_quet_day_du(db) is None
    assert chay_luot_kiem(db, d, bay_gio=BAY_GIO).quet_day_du, "chưa quét xong ⇒ quét lại"
    assert models_vao_bo.doc_ngay_quet_day_du(db) == NGAY_VN


# --- lô ≤200 và đọc hết trang -------------------------------------------------------------------------

def test_chia_lo_200_doc_het_trang_ke_ca_trang_rong_co_token(kho):
    db, job = kho
    tong = 450
    for i in range(1, tong + 1):
        them(db, job, i)
    da_quet_hom_nay(db)
    d = DriveGia(trang=100, trang_rong_dau=True)
    d.dat_ten_thu_muc("BO1", "N.2809C - x")
    for i in range(1, tong + 1):
        d.them_nguon(fid(i))
    for i in range(1, 251):              # 250 bản có dấu (>100/trang ⇒ nhiều trang) nhưng SAI md5
        d.them_ban(f"ban{i}", fid(i), folder="BO1", md5="SAI")
    kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    lo = [int(a) for t, a in d.goi if t == "liet_ke_lo"]
    # 3 lô (200, 200, 50), mỗi lô đọc ≥1 trang: kích thước các LỜI GỌI theo lô.
    assert sorted(set(lo)) == [50, 200] and lo.count(200) >= 2 and lo.count(50) >= 1
    assert d.so_lan("liet_ke_lo") > 3, "nhiều trang + trang rỗng đầu ⇒ nhiều lời gọi hơn số lô"
    assert kq.n_a == 250, "đọc HẾT trang mới thấy đủ 250 nguồn có bản có dấu"
    assert da_lay_tep(d) == {fid(i) for i in range(1, 251)}, "chỉ A ∪ T ∪ H được đo"
    assert kq.so_goi_drive == len(d.goi)


# --- ghi mốc ẩn chỉ sau bằng chứng đầy đủ ---------------------------------------------------------------

def test_co_dau_nhung_sai_bang_chung_thi_khong_an_chi_an_khi_dat(kho):
    db, job = kho
    for i in (1, 2):
        them(db, job, i)
    da_quet_hom_nay(db)
    d = drive(nguon=(1, 2))
    d.them_ban("ban1", fid(1), folder="BO1")                      # đủ bằng chứng
    d.them_ban("ban2", fid(2), folder="BO1", md5="SAI")           # có dấu nhưng md5 sai
    kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    assert kq.n_a == 2 and kq.da_an == 1
    assert hang(db) == [("v1", 1)]


# --- nhật ký chi phí ------------------------------------------------------------------------------------

def test_log_moi_luot_co_A_T_H_so_loi_goi_fallback_va_quet_day_du(kho, caplog):
    db, job = kho
    for i in (1, 2, 3):
        them(db, job, i)
    da_quet_hom_nay(db)
    d = drive(nguon=(1, 2, 3), co_ban=(1,), thung=(2,))
    with caplog.at_level(logging.INFO, logger="videodl.web.vao_bo"):
        kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    dong = next(r.getMessage() for r in caplog.records if "|A|=" in r.getMessage())
    assert f"|A|=1 |T|=1 |H|=0" in dong
    assert f"lời_gọi_drive={len(d.goi)}" in dong and kq.so_goi_drive == len(d.goi)
    assert "fallback=False" in dong and "quét_đầy_đủ=False" in dong

    caplog.clear()
    d.loi[("liet_ke_lo", "*")] = http_loi(500)
    with caplog.at_level(logging.INFO, logger="videodl.web.vao_bo"):
        chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    assert "fallback=True" in next(r.getMessage() for r in caplog.records if "|A|=" in r.getMessage())
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="videodl.web.vao_bo"):
        chay_luot_kiem(db, d, bay_gio=BAY_GIO + timedelta(days=1))
    assert "quét_đầy_đủ=True" in next(r.getMessage() for r in caplog.records if "|A|=" in r.getMessage())


# --- S-2: ngày quét chỉ ghi khi lượt quét THẬT SỰ đo được ------------------------------------------------

def test_quet_ma_moi_lay_tep_deu_nem_thi_khong_ghi_ngay_va_lan_sau_quet_lai(kho):
    db, job = kho
    for i in (1, 2, 3):
        them(db, job, i)
    d = drive(nguon=(1, 2, 3))
    for i in (1, 2, 3):
        d.loi[("lay_tep", fid(i))] = http_loi(403)
    kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    assert kq.quet_day_du and kq.khong_do_duoc == 3
    assert models_vao_bo.doc_ngay_quet_day_du(db) is None, "quét không đo được gì ⇒ chưa xong"
    assert chay_luot_kiem(db, d, bay_gio=BAY_GIO + timedelta(minutes=15)).quet_day_du, \
        "lượt kế tiếp quét lại"
    d.loi.clear()
    assert chay_luot_kiem(db, d, bay_gio=BAY_GIO + timedelta(minutes=30)).quet_day_du
    assert models_vao_bo.doc_ngay_quet_day_du(db) == NGAY_VN
    assert not chay_luot_kiem(db, d, bay_gio=BAY_GIO + timedelta(minutes=45)).quet_day_du


def test_quet_khong_co_ung_vien_nao_van_ghi_ngay(kho):
    db, _ = kho
    assert chay_luot_kiem(db, drive(), bay_gio=BAY_GIO).quet_day_du
    assert models_vao_bo.doc_ngay_quet_day_du(db) == NGAY_VN


# --- S-4: nguồn SỐNG lại ⇒ gỡ dấu báo động; lời log đúng cho video chưa từng ẩn ----------------------------

def test_nguon_song_lai_thi_go_dau_bao_dong_va_h_thoi_phinh(kho):
    db, job = kho
    them(db, job, 1)
    da_quet_hom_nay(db)
    models_vao_bo.ghi_bao_dong(db, "v1", TOI, LY_DO_NGUON_O_THUNG_RAC)
    assert models_vao_bo.video_da_bao_dong(db) == {"v1"}
    d = drive(nguon=(1,))                       # nguồn đã được khôi phục: sống, 0 bản
    kq = chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    assert kq.n_h == 1 and kq.bao_dong == 0
    assert models_vao_bo.hang_don_loi(db) == [] and models_vao_bo.video_da_bao_dong(db) == set()
    assert chay_luot_kiem(db, d, bay_gio=BAY_GIO).n_h == 0, "H không còn phình"


def test_xoa_bao_dong_chi_dung_toi_ma_bao_dong_khong_dung_loi_don_thuong(kho):
    db, job = kho
    them(db, job, 1)
    models_vao_bo.ghi_da_vao_bo(db, "v1", TOI, [{"ban_copy_id": "c", "folder_id": "F",
                                                 "ma_bo": "N.1", "bang_chung": "properties"}])
    models_vao_bo.ghi_truot_don(db, "v1", "trash_file không ok")
    assert models_vao_bo.xoa_bao_dong(db, "v1") is False
    assert [h["loi_cuoi"] for h in models_vao_bo.hang_don_loi(db)] == ["trash_file không ok"]


def test_log_bao_dong_video_chua_tung_an_khong_noi_duoc_hien_lai(kho, caplog):
    db, job = kho
    them(db, job, 1)
    da_quet_hom_nay(db)
    d = drive(nguon=(1,), thung=(1,))
    with caplog.at_level(logging.ERROR, logger="videodl.web.vao_bo"):
        chay_luot_kiem(db, d, bay_gio=BAY_GIO)
    msg = loi_bao_dong(caplog, LY_DO_NGUON_O_THUNG_RAC)[0].getMessage()
    assert "chưa từng bị ẩn" in msg and "được hiện lại" not in msg
