"""Ảnh ĐI QUA máy vào bộ / backfill / dọn ngày 7 như video (một hàng = một tệp Drive).

Drive là bản giả (`drive_gia_vao_bo.DriveGia`, tệp `image/jpeg`); riêng truy vấn liệt kê thật
(`DriveThat`) được kiểm bằng dịch vụ giả bắt tham số `q`.

Đột biến (áp tạm ⇒ ĐỎ, hoàn nguyên ⇒ XANH):
  * Trong `web/vao_bo_drive.py` xoá vế ` or mimeType contains 'image/'` (và dấu ngoặc quanh nó) khỏi
    truy vấn `liet_ke_video_shared_drive` HOẶC `liet_ke_video_thung_rac` ⇒ `test_truy_van_drive_that_*` đỏ.
  * Thêm `AND v.loai = 'video'` vào `SQL_UNG_VIEN_CAN_KIEM` (`web/models_vao_bo.py`) hoặc vào câu của
    `ung_vien_don` ⇒ `test_ung_vien_can_kiem_*` / `test_don_ngay_7_*` đỏ (ảnh bị loại khỏi máy vào bộ/dọn).
"""
from __future__ import annotations

import sqlite3
import types
from datetime import datetime, timedelta, timezone

import pytest

from drive_gia_vao_bo import DriveGia
from tiktok_music_downloader.tai_anh_cau_hinh import bai_id_anh, file_id_anh
from web import models, models_anh, models_vao_bo
from web.vao_bo_backfill import chay_backfill
from web.vao_bo_don import chay_luot_don
from web.vao_bo_drive import DriveThat
from web.vao_bo_kiem import chay_luot_kiem
from web.vao_bo_drive import ban_hop_le

TOI = "toi@astronex.ai"
BAY_GIO = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

# SQL lùi bản ở kế hoạch (mục rủi ro/rollback) — phần `videos`; `<now>` thay bằng mốc cố định.
SQL_LUI_BAN = ("UPDATE videos SET da_loai_luc='2026-09-29T00:00:00+00:00', loai_boi='lui_ban' "
               "WHERE loai='anh' AND da_loai_luc IS NULL AND video_id NOT IN "
               "(SELECT video_id FROM video_vao_bo WHERE an_luc IS NOT NULL AND drive_don_luc IS NULL)")
SQL_HOAN_NGUYEN = "UPDATE videos SET da_loai_luc=NULL, loai_boi=NULL WHERE loai='anh' AND loai_boi='lui_ban'"


def fid(ten: str) -> str:
    return f"1{ten}_AbCdEfGhIjKlMn"


def luc(ngay_truoc: float) -> str:
    return (BAY_GIO - timedelta(days=ngay_truoc)).isoformat()


@pytest.fixture(autouse=True)
def don_ngay7_bat(monkeypatch):
    monkeypatch.setenv("VIDEODL_BAT_DON_NGAY7", "1")


@pytest.fixture
def kho(tmp_path):
    """1 video `v1` + bài ảnh X (X-01, X-02), tất cả có tệp nguồn trên Drive giả."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/@a", 3, TOI)
    models.record_video(db, job_id=job, video_id="v1", url="u1", drive_file_id=fid("v1"),
                        tao_luc="2026-09-01T00:00:01+00:00")
    bai = bai_id_anh("tt", "777")
    x1, x2 = file_id_anh(bai, 1), file_id_anh(bai, 2)
    models_anh.ghi_bai_anh(db, [
        {"video_id": x, "job_id": job, "url": "https://www.tiktok.com/@a/photo/777", "bai_id": bai,
         "thu_tu": i, "drive_file_id": fid(f"x{i}"), "tao_luc": f"2026-09-01T00:00:0{i + 1}+00:00"}
        for i, x in enumerate((x1, x2), 1)])
    d = DriveGia(tra_ca_thung_rac=True)
    d.dat_ten_thu_muc("BO1", "N.2809C - Ten")
    d.them_nguon(fid("v1"), md5="MV", size="10")
    d.them_nguon(fid("x1"), md5="MX1", size="11", mime="image/jpeg")
    d.them_nguon(fid("x2"), md5="MX2", size="12", mime="image/jpeg")
    return {"db": db, "job": job, "x1": x1, "x2": x2, "drive": d}


def _hang(db, vid):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM video_vao_bo WHERE video_id = ?", (vid,)).fetchone()
    return dict(r) if r else None


def _loai(db, vid):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT da_loai_luc, loai_boi FROM videos WHERE video_id = ?", (vid,)).fetchone()


def _da_trash(d):
    return [a for t, a in d.goi if t == "bo_vao_thung_rac"]


def test_ung_vien_can_kiem_co_ca_anh(kho):
    ids = {u["video_id"] for u in models_vao_bo.ung_vien_can_kiem(kho["db"])}
    assert ids == {"v1", kho["x1"], kho["x2"]}


def test_ban_copy_image_md5_size_dat_ban_hop_le_va_an_hang(kho):
    db, d = kho["db"], kho["drive"]
    d.them_ban("banx1", fid("x1"), folder="BO1")           # kế thừa md5+size+mime của nguồn ảnh
    assert d.tep["banx1"]["mimeType"] == "image/jpeg"
    assert ban_hop_le(fid("x1"), d.tep[fid("x1")], d.tep["banx1"], can_dau_nguon=True)
    kq = chay_luot_kiem(db, d)
    assert kq.da_an == 1
    h = _hang(db, kho["x1"])
    assert h and h["an_luc"] and h["drive_don_luc"] is None
    assert _hang(db, kho["x2"]) is None and _hang(db, "v1") is None, "chỉ tệp có bản copy mới ẩn"


def test_don_ngay_7_trash_tep_nguon_anh(kho):
    db, d = kho["db"], kho["drive"]
    d.them_ban("banx1", fid("x1"), folder="BO1")
    models_vao_bo.ghi_da_vao_bo(db, kho["x1"], TOI,
                                [{"ban_copy_id": "banx1", "folder_id": "BO1", "ma_bo": "N.2809C",
                                  "bang_chung": "properties"}], luc(8))
    kq = chay_luot_don(db, d, bay_gio=BAY_GIO)
    assert kq.da_bo_thung_rac == 1
    assert _da_trash(d) == [fid("x1")], "trash nhận id tệp nguồn ảnh, không phải bản trong bộ"
    assert d.tep[fid("x1")]["trashed"] is True and d.tep["banx1"]["trashed"] is False
    assert _hang(db, kho["x1"])["drive_don_luc"]


def test_backfill_va_liet_ke_thung_rac_thay_anh(kho):
    db, d = kho["db"], kho["drive"]
    d.them_ban("banx2", fid("x2"), folder="BO1", dau=False)   # không dấu nguồn: chỉ md5+size nối được
    bc = chay_backfill(db, d, that=True)
    assert {m["video_id"] for m in bc.se_danh_dau} == {kho["x2"]}
    assert _hang(db, kho["x2"])["an_luc"]
    d.tep[fid("x1")]["trashed"] = True
    trang, _ = d.liet_ke_video_thung_rac(None)
    assert [t["id"] for t in trang] == [fid("x1")]
    tep, _ = d.liet_ke_video_shared_drive("D1", None)
    assert {t["id"] for t in tep} >= {fid("x2"), "banx2"}


class _DichVu:
    def __init__(self):
        self.q: list[str] = []

    def files(self):
        return self

    def list(self, **kw):
        self.q.append(kw["q"])
        return types.SimpleNamespace(execute=lambda: {"files": [], "nextPageToken": None})


class _NguoiUpload:
    def __init__(self, dv):
        self.dv = dv

    def is_configured(self):
        return True

    def _build_service(self):
        return self.dv


def test_truy_van_drive_that_xin_ca_video_lan_anh(monkeypatch):
    monkeypatch.setenv("VIDEODL_TAI_ANH_BAT", "1")
    dv = _DichVu()
    d = DriveThat(_NguoiUpload(dv))
    d.liet_ke_video_shared_drive("D1", None)
    d.liet_ke_video_thung_rac(None)
    assert len(dv.q) == 2
    for q in dv.q:
        assert "mimeType contains 'video/'" in q and "mimeType contains 'image/'" in q, q
        assert " or " in q and q.count("(") == q.count(")") == 1, "vế mime phải gói trong ngoặc, `trashed` đứng ngoài"


# --- lùi bản: ảnh hiện như video với code cũ nên phải ẩn đi ---------------------------

def _an(db, vid, ngay):
    models_vao_bo.ghi_da_vao_bo(db, vid, TOI, [{"ban_copy_id": f"ban-{vid}", "folder_id": "BO1",
                                                "ma_bo": "N.2809C", "bang_chung": "properties"}], luc(ngay))


def test_lui_ban_anh_cho_don_van_bi_trash_anh_chua_vao_bo_bi_an_dau_bo_tay_giu(kho):
    db, d = kho["db"], kho["drive"]
    x1, x2 = kho["x1"], kho["x2"]
    d.them_ban("ban-" + x1, fid("x1"), folder="BO1")
    _an(db, x1, 8)                                         # đã ẩn từ 8 ngày: chờ dọn
    models.danh_dau_da_loai(db, x2, TOI)                   # người dùng Bỏ tay x2
    bo_tay = _loai(db, x2)
    bai2 = bai_id_anh("tt", "888")
    y1 = file_id_anh(bai2, 1)
    models_anh.ghi_bai_anh(db, [{"video_id": y1, "job_id": kho["job"], "url": "u", "bai_id": bai2, "thu_tu": 1,
                                 "drive_file_id": fid("y1")}])   # ảnh chưa vào bộ

    with sqlite3.connect(db) as c:
        c.execute(SQL_LUI_BAN)
    assert _loai(db, x1) == (None, None), "ảnh đã ẩn chờ dọn KHÔNG bị đánh da_loai"
    assert _loai(db, y1)[1] == "lui_ban" and _loai(db, y1)[0], "ảnh chưa vào bộ bị ẩn"
    assert _loai(db, x2) == bo_tay, "dấu Bỏ tay giữ nguyên"

    kq = chay_luot_don(db, d, bay_gio=BAY_GIO + timedelta(days=8))
    assert kq.da_loai == 0 and kq.da_bo_thung_rac == 1
    assert _da_trash(d) == [fid("x1")], "ảnh chờ dọn vẫn bị trash nguồn"
    assert _hang(db, x1)["ly_do_don"] != "da_loai"

    with sqlite3.connect(db) as c:
        c.execute(SQL_HOAN_NGUYEN)
    assert _loai(db, y1) == (None, None), "hoàn nguyên đưa ảnh bị ẩn trở lại"
    assert _loai(db, x2) == bo_tay, "hoàn nguyên không đụng dấu Bỏ tay"
