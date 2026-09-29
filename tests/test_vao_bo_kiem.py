"""Bộ kiểm "đã vào bộ": luật bằng chứng, thứ tự ghi mốc, đọc hết trang.

Drive luôn là bản giả (`drive_gia_vao_bo.DriveGia`) — không có lời gọi Drive thật.
"""
from __future__ import annotations

import sqlite3

import pytest

from drive_gia_vao_bo import DriveGia
from web import models, models_vao_bo
from web.vao_bo_drive import ban_hop_le, doc_het_trang, ma_bo_tu_ten
from web.vao_bo_kiem import AM, DAT, KHONG_DO_DUOC, chay_luot_kiem, do_bang_chung

TOI = "toi@astronex.ai"
FID = "1SourceFile_AbCdEfGh"          # id nguồn hợp lệ (≥10 ký tự)


def fid(i: int) -> str:
    return f"1Src{i:03d}_AbCdEfGhIjKl"


@pytest.fixture
def kho(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/a", 5, TOI)
    return db, job


def them_video(db, job, i, drive_id=None):
    models.record_video(db, job_id=job, video_id=f"v{i}", url=f"https://t.co/{i}",
                        drive_file_id=drive_id or fid(i), tao_luc=f"2026-09-01T00:00:0{i}+00:00")


def drive_co_ban(n_nguon=1, *, ten_bo="N.2809C - Ten dai", **kw):
    d = DriveGia(**kw)
    d.dat_ten_thu_muc("BO1", ten_bo)
    for i in range(1, n_nguon + 1):
        d.them_nguon(fid(i))
        d.them_ban(f"ban{i}", fid(i), folder="BO1")
    return d


def hang_vao_bo(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return ([dict(r) for r in c.execute("SELECT * FROM video_vao_bo ORDER BY video_id")],
                [dict(r) for r in c.execute("SELECT * FROM video_vao_bo_ban ORDER BY ban_copy_id")])


# --- luật bằng chứng: đủ năm vế ------------------------------------------------

def _nguon():
    return {"id": FID, "md5Checksum": "M1", "size": "1000", "parents": ["SRC"]}


def _ban(**sua):
    b = {"id": "ban1", "md5Checksum": "M1", "size": "1000", "parents": ["BO1"], "trashed": False,
         "properties": {"videodesk_src": FID}}
    b.update(sua)
    return b


def test_ban_hop_le_du_nam_ve():
    assert ban_hop_le(FID, _nguon(), _ban(), can_dau_nguon=True)


@pytest.mark.parametrize("sua, ly_do", [
    ({"md5Checksum": "KHAC"}, "md5 khác"),
    ({"size": "999"}, "size khác"),
    ({"trashed": True}, "đã vào thùng rác"),
    ({"parents": ["SRC"]}, "cùng folder với nguồn"),
    ({"id": FID}, "chính là nguồn"),
    ({"md5Checksum": None}, "thiếu md5"),
    ({"size": None}, "thiếu size"),
    ({"properties": {}}, "thiếu dấu nguồn"),
    ({"properties": {"videodesk_src": "1KhacKhacKhacKhac"}}, "dấu trỏ nguồn khác"),
    ({"parents": []}, "không có folder cha"),
])
def test_ban_thieu_mot_ve_khong_dat(sua, ly_do):
    assert not ban_hop_le(FID, _nguon(), _ban(**sua), can_dau_nguon=True), ly_do


def test_ban_backfill_khong_can_dau_nguon():
    assert ban_hop_le(FID, _nguon(), _ban(properties={}), can_dau_nguon=False)


def test_nguon_da_mat_chi_con_ve_bo_sung():
    assert ban_hop_le(FID, None, _ban(), can_dau_nguon=True)
    assert not ban_hop_le(FID, None, _ban(trashed=True), can_dau_nguon=True)


@pytest.mark.parametrize("ten, ma", [
    ("N.2809C - Tên rất dài", "N.2809C"),
    ("PN.2209E - x", "PN.2209E"),
    ("N.2609", "N.2609"),
    ("Bộ khác hẳn", "Bộ khác hẳn"),
    ("N.28 - x", "N.28 - x"),
    ("N.2809CX - y", "N.2809CX - y"),
])
def test_ma_bo_tu_ten_folder(ten, ma):
    assert ma_bo_tu_ten(ten) == ma


# --- đọc hết trang -----------------------------------------------------------------

def test_doc_het_trang_khong_dung_o_trang_rong_co_token():
    trang = {None: ([], "a"), "a": ([{"id": 1}], "b"), "b": ([{"id": 2}], None)}
    assert doc_het_trang(lambda t: trang[t]) == [{"id": 1}, {"id": 2}]


def test_doc_het_trang_token_lap_la_khong_do_duoc():
    with pytest.raises(RuntimeError):
        doc_het_trang(lambda t: ([], "mai"))


def test_ban_hop_le_nam_o_trang_thu_ba_van_duoc_thay():
    d = DriveGia(trang=100)
    d.them_nguon(FID)
    for k in range(250):        # 250 bản hỏng (trashed) không tính; bản đạt nằm CUỐI
        d.them_ban(f"x{k:03d}", FID, folder="BO1", md5="SAI")
    d.them_ban("tot", FID, folder="BO1")
    kq = do_bang_chung(d, FID)
    assert kq.trang_thai == DAT and [b["id"] for b in kq.ban] == ["tot"]
    assert d.so_lan("liet_ke_ban_sao") == 3, "251 bản = 3 trang, phải đọc đủ cả ba"


def test_trang_dau_rong_co_token_khong_bi_doc_thanh_am():
    d = DriveGia(trang_rong_dau=True)
    d.them_nguon(FID)
    d.them_ban("tot", FID)
    assert do_bang_chung(d, FID).trang_thai == DAT
    assert d.so_lan("liet_ke_ban_sao") == 2


# --- ba kết quả đo ------------------------------------------------------------------

def test_do_am_khi_drive_tra_loi_ma_khong_co_ban_hop_le():
    d = DriveGia()
    d.them_nguon(FID)
    assert do_bang_chung(d, FID).trang_thai == AM


def test_do_khong_do_duoc_khi_co_loi_goi_khong_phai_404():
    d = DriveGia()
    d.them_nguon(FID)
    d.loi[("liet_ke_ban_sao", FID)] = TimeoutError("mạng")
    kq = do_bang_chung(d, FID)
    assert kq.trang_thai == KHONG_DO_DUOC and kq.loi == "TimeoutError"


def test_nguon_404_do_duoc_voi_bang_chung_mot_phan():
    d = DriveGia()
    d.them_ban("ban1", FID, md5="M1", size="1000")   # nguồn không có trong kho ⇒ 404
    kq = do_bang_chung(d, FID)
    assert kq.nguon is None and kq.nguon_khong_con and kq.trang_thai == DAT


# --- lượt kiểm (ẨN) ----------------------------------------------------------------

def test_luot_kiem_an_video_co_bang_chung_va_ghi_ma_bo_va_folder(kho):
    db, job = kho
    them_video(db, job, 1)
    d = drive_co_ban(1)
    kq = chay_luot_kiem(db, d)
    assert (kq.da_xet, kq.da_an) == (1, 1)
    vao_bo, ban = hang_vao_bo(db)
    assert [(r["video_id"], r["chu"], bool(r["an_luc"]), r["drive_don_luc"]) for r in vao_bo] == [
        ("v1", TOI, True, None)]
    assert [(b["ban_copy_id"], b["folder_id"], b["ma_bo"], b["bang_chung"]) for b in ban] == [
        ("ban1", "BO1", "N.2809C", "properties")]


def test_video_o_hai_bo_ghi_hai_dong_ban_mot_dong_moc(kho):
    db, job = kho
    them_video(db, job, 1)
    d = drive_co_ban(1)
    d.dat_ten_thu_muc("BO2", "N.2909B - khac")
    d.them_ban("ban1b", fid(1), folder="BO2")
    chay_luot_kiem(db, d)
    vao_bo, ban = hang_vao_bo(db)
    assert len(vao_bo) == 1
    assert sorted(b["ma_bo"] for b in ban) == ["N.2809C", "N.2909B"]
    assert models_vao_bo.vao_bo_cho_videos(db, ["v1"])["v1"]["ma_bo"] == ["N.2809C", "N.2909B"]


def test_khong_ghi_gi_khi_bang_chung_am(kho):
    """Mốc ẩn ghi SAU bằng chứng: đo ra âm ⇒ 0 hàng, kể cả hàng bản sao."""
    db, job = kho
    them_video(db, job, 1)
    d = DriveGia()
    d.them_nguon(fid(1))
    kq = chay_luot_kiem(db, d)
    assert (kq.da_an, kq.chua_co_bang_chung) == (0, 1)
    assert hang_vao_bo(db) == ([], [])


def test_khong_ghi_gi_khi_drive_loi(kho):
    db, job = kho
    them_video(db, job, 1)
    d = drive_co_ban(1)
    d.loi[("liet_ke_ban_sao", fid(1))] = ConnectionError("sập")
    kq = chay_luot_kiem(db, d)
    assert (kq.da_an, kq.khong_do_duoc) == (0, 1)
    assert hang_vao_bo(db) == ([], [])


def test_khong_ghi_gi_khi_tra_ten_folder_loi(kho):
    db, job = kho
    them_video(db, job, 1)
    d = drive_co_ban(1)
    d.loi[("ten_thu_muc", "BO1")] = TimeoutError()
    kq = chay_luot_kiem(db, d)
    assert (kq.da_an, kq.khong_do_duoc) == (0, 1)
    assert hang_vao_bo(db) == ([], [])


def test_nguon_da_mat_khong_bi_an(kho):
    db, job = kho
    them_video(db, job, 1)
    d = DriveGia()
    d.dat_ten_thu_muc("BO1", "N.2809C - x")
    d.them_ban("ban1", fid(1), md5="M1", size="1000")   # có bản có dấu nhưng nguồn 404
    kq = chay_luot_kiem(db, d)
    assert (kq.da_an, kq.nguon_mat) == (0, 1)
    assert hang_vao_bo(db) == ([], [])


def test_copy_hong_1_tren_n_chi_an_n_tru_1(kho):
    db, job = kho
    for i in (1, 2, 3):
        them_video(db, job, i)
    d = drive_co_ban(3)
    d.tep["ban2"]["md5Checksum"] = "HONG"      # bản của video 2 hỏng
    kq = chay_luot_kiem(db, d)
    assert (kq.da_xet, kq.da_an) == (3, 2)
    assert {r["video_id"] for r in hang_vao_bo(db)[0]} == {"v1", "v3"}


def test_luot_thu_hai_khong_ghi_them_va_khong_doi_moc(kho):
    db, job = kho
    them_video(db, job, 1)
    d = drive_co_ban(1)
    chay_luot_kiem(db, d)
    moc = hang_vao_bo(db)[0][0]["an_luc"]
    kq = chay_luot_kiem(db, d)
    assert (kq.da_xet, kq.da_an) == (0, 0), "video đã ẩn không còn là ứng viên"
    assert hang_vao_bo(db)[0][0]["an_luc"] == moc


def test_ghi_da_vao_bo_hai_lan_giu_moc_dau_va_them_ban_moi(kho):
    db, job = kho
    them_video(db, job, 1)
    b1 = [{"ban_copy_id": "c1", "folder_id": "F1", "ma_bo": "N.1", "bang_chung": "properties"}]
    b2 = [{"ban_copy_id": "c2", "folder_id": "F2", "ma_bo": "N.2", "bang_chung": "properties"}]
    assert models_vao_bo.ghi_da_vao_bo(db, "v1", TOI, b1, "2026-09-20T00:00:00+00:00") is True
    assert models_vao_bo.ghi_da_vao_bo(db, "v1", TOI, b2, "2026-09-25T00:00:00+00:00") is False
    vao_bo, ban = hang_vao_bo(db)
    assert vao_bo[0]["an_luc"] == "2026-09-20T00:00:00+00:00", "mốc không dời"
    assert [b["ban_copy_id"] for b in ban] == ["c1", "c2"]


def test_hai_luot_an_cung_luc_chi_mot_luot_dat_moc(kho):
    import threading
    db, job = kho
    them_video(db, job, 1)
    ban = [{"ban_copy_id": "c1", "folder_id": "F", "ma_bo": "N.1", "bang_chung": "properties"}]
    rao = threading.Barrier(2)
    ket: list[bool] = []

    def chay(luc):
        rao.wait()
        ket.append(models_vao_bo.ghi_da_vao_bo(db, "v1", TOI, ban, luc))
    ts = [threading.Thread(target=chay, args=(x,)) for x in ("2026-09-20T00:00:00+00:00",
                                                          "2026-09-21T00:00:00+00:00")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(ket) == [False, True], "đúng MỘT lượt đặt mốc, lượt kia thấy mốc và không dời"
    assert hang_vao_bo(db)[0][0]["an_luc"] in ("2026-09-20T00:00:00+00:00",
                                                "2026-09-21T00:00:00+00:00")


def test_video_da_loai_hoac_da_don_khong_la_ung_vien(kho):
    db, job = kho
    for i in (1, 2, 3):
        them_video(db, job, i)
    models.danh_dau_da_loai(db, "v1", TOI)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc, drive_don_luc, ly_do_don) "
                  "VALUES ('v2', 'x', 'y', 'da_don')")
    assert [u["video_id"] for u in models_vao_bo.ung_vien_can_kiem(db)] == ["v3"]


def test_video_id_drive_sai_hinh_dang_bi_dem_khong_dung_vao_truy_van(kho):
    db, job = kho
    them_video(db, job, 1, drive_id="x' or '1'='1")
    d = DriveGia()
    kq = chay_luot_kiem(db, d)
    assert kq.id_sai == 1 and d.goi == []


def test_dung_giua_luot_thoat_sach(kho):
    db, job = kho
    for i in (1, 2, 3):
        them_video(db, job, i)
    d = drive_co_ban(3)
    dem = {"n": 0}

    def dung():
        dem["n"] += 1
        return dem["n"] > 1
    kq = chay_luot_kiem(db, d, dung=dung)
    assert kq.da_an == 1


# --- một điều kiện ứng viên duy nhất cho chọn ứng viên và tỉa R --------------------------------------

def test_tap_tia_R_bang_dung_tap_ung_vien_qua_ca_ba_nhanh(kho):
    """`cap_nhat_tap_thu_lai` tỉa R theo cùng điều kiện với `ung_vien_can_kiem`, ở đủ ba nhánh:
    đã loại, đã ẩn (`an_luc`), đã dọn (`drive_don_luc`); cộng ứng viên sống để đối chứng."""
    db, job = kho
    for i in range(1, 6):
        them_video(db, job, i)
    models.danh_dau_da_loai(db, "v2", TOI)                                   # nhánh da_loai
    models_vao_bo.ghi_da_vao_bo(db, "v3", TOI, [{"ban_copy_id": "c3", "folder_id": "F",
                                                 "ma_bo": "N.1", "bang_chung": "properties"}])
    with sqlite3.connect(db) as c:                                            # nhánh drive_don_luc
        c.execute("INSERT INTO video_vao_bo (video_id, an_luc, drive_don_luc, ly_do_don) "
                  "VALUES ('v4', 'x', 'y', 'da_don')")
    ung_vien = {u["video_id"] for u in models_vao_bo.ung_vien_can_kiem(db)}
    assert ung_vien == {"v1", "v5"}
    models_vao_bo.ghi_tap_thu_lai(db, {f"v{i}": 1 for i in range(1, 6)} | {"khong-co": 1})
    tia = models_vao_bo.cap_nhat_tap_thu_lai(db, set(), set())
    assert set(tia) == ung_vien, "R được tỉa đúng bằng tập ứng viên"


def test_hai_noi_dung_chung_mot_hang_so_khong_tu_viet_lai_dieu_kien():
    import inspect
    nguon = inspect.getsource(models_vao_bo)
    assert nguon.count("NOT EXISTS (SELECT 1 FROM video_vao_bo b WHERE b.video_id = v.video_id "
                       "\"\n    \"                AND b.an_luc IS NOT NULL)") == 1
    assert nguon.count("SQL_UNG_VIEN_CAN_KIEM") >= 3, "định nghĩa + hai nơi dùng"


def test_R_json_long_sau_100000_tang_la_hong_khong_phai_recursion_error(kho):
    db, job = kho
    sau = "[" * 100000 + "]" * 100000
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO vao_bo_kv (khoa, gia_tri) VALUES ('tap_thu_lai', ?)", (sau,))
    with pytest.raises(models_vao_bo.TapThuLaiHong):
        models_vao_bo.doc_tap_thu_lai(db)
    assert models_vao_bo.doc_tap_thu_lai_an_toan(db) == {}
    assert models_vao_bo.cap_nhat_tap_thu_lai(db, set(), set()) == {}, "bị ghi đè bằng giá trị hợp lệ"
    assert models_vao_bo.doc_tap_thu_lai(db) == {}
