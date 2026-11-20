"""Vòng đời một bài ảnh: đủ K tệp lên Drive → mới ghi K hàng → xoá local; trượt thì trash thư mục bài, 0 hàng.

Uploader giả MỚI (có `create_folder`) ghi lại thứ tự gọi; ảnh mẫu sinh bằng Pillow; không mạng, không Drive thật.

Đột biến (áp tạm trong `web/lifecycle_anh.py` ⇒ test đỏ, hoàn nguyên ⇒ xanh):
  * Ghi hàng DB trước upload: chuyển khối `ghi_bai_anh(...)` lên trước vòng `for ... _upload_co_thu_lai` (kèm
    `drive_file_id` tạm) ⇒ `test_upload_tep_thu_ba_truot_khong_hang_trash_thu_muc` đỏ (còn hàng).
  * Không trash thư mục Drive dở: biến thân `_bo_thu_muc_dang` thành `return` ngay ⇒ cùng test đó đỏ (không có
    lệnh trash).
  * Không gọi `_note_upload_outcome`: xoá mọi lời gọi `lifecycle._note_upload_outcome(...)` (gồm nhánh không tạo
    được thư mục job) ⇒ `test_upload_tep_thu_ba_truot_...` và `test_thu_muc_job_khong_tao_duoc_...` đỏ.
"""
from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from tiktok_music_downloader.utils import VideoRef
from web import lifecycle, lifecycle_anh, models

BAI = "anh-tt-7000000000000000002"


def _anh(i: int) -> bytes:
    buf = io.BytesIO()
    Image.effect_noise((320, 240), 60 + i).convert("RGB").save(buf, "JPEG")
    return buf.getvalue()


class UploaderGia:
    def __init__(self, *, job_folder_ok=True, hong_tep: int | None = None, trash_ok=True, cau_hinh=True):
        self.job_folder_ok, self.hong_tep, self.trash_ok, self.cau_hinh = job_folder_ok, hong_tep, trash_ok, cau_hinh
        self.cay: dict[str, list[str]] = {}          # id thư mục -> tên tệp theo thứ tự đẩy lên
        self.thu_muc: dict[str, tuple[str, str | None]] = {}
        self.da_trash: list[str] = []
        self.so_upload = 0
        self.hang_luc_upload: list[int] = []         # số hàng DB tại mỗi lần upload (để canh thứ tự)
        self.db_path: Path | None = None

    def is_configured(self):
        return self.cau_hinh

    def create_job_folder(self, job_id):
        if not self.job_folder_ok:
            return UploadResult(outcome=UploadOutcome.FAILED, reason="HttpError")
        self.thu_muc["F-job"] = (f"job-{job_id}", None)
        self.cay["F-job"] = []
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id="F-job", drive_id="D", web_view_link="http://x")

    def create_folder(self, name, parent_id=None):
        fid = f"F-{name}"
        self.thu_muc[fid] = (name, parent_id)
        self.cay[fid] = []
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=fid, drive_id="D")

    def upload_file(self, path, parent_folder_id=None):
        self.so_upload += 1
        if self.db_path is not None:
            with sqlite3.connect(self.db_path) as c:
                self.hang_luc_upload.append(c.execute("SELECT COUNT(*) FROM videos WHERE loai='anh'").fetchone()[0])
        if self.hong_tep == self.so_upload:
            return UploadResult(outcome=UploadOutcome.FAILED, reason="Forbidden")   # không đáng thử lại
        self.cay[parent_folder_id].append(path.name)
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=f"T{self.so_upload}", drive_id="D")

    def trash_file(self, file_id):
        self.da_trash.append(file_id)
        if not self.trash_ok:
            return UploadResult(outcome=UploadOutcome.FAILED, reason="HttpError")
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=file_id)


@pytest.fixture
def moi_truong(tmp_path):
    lifecycle.reset_backpressure_state()
    lifecycle.reset_job_folder_cache()
    db = tmp_path / "jobs.db"
    models.init_db(db)
    job_id = models.create_job(db, "https://nguon.invalid/u", 5, "chu@dev.local")
    yield db, job_id, tmp_path
    lifecycle.reset_backpressure_state()
    lifecycle.reset_job_folder_cache()


def _tao_tep(thu_muc: Path, k: int) -> list[Path]:
    d = thu_muc / "tai" / BAI
    d.mkdir(parents=True)
    ra = []
    for i in range(1, k + 1):
        p = d / f"{i:02d}.jpg"
        p.write_bytes(_anh(i))
        ra.append(p)
    return ra


def _ref():
    return VideoRef(video_id=BAI, url="https://nguon.invalid/bai", title="t", author="a", loai="anh")


def _hang(db):
    with sqlite3.connect(db) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM videos ORDER BY thu_tu")]


def test_bai_8_anh_len_drive_dung_thu_tu_ghi_8_hang_co_thumb_va_sach_local(moi_truong):
    db, job_id, tmp = moi_truong
    tep = _tao_tep(tmp, 8)
    up = UploaderGia()
    up.db_path = db
    kq = lifecycle_anh.on_bai_anh_verified(job_id=job_id, ref=_ref(), tep=tep, db_path=db, uploader=up)
    assert kq.ok
    assert up.thu_muc[f"F-{BAI}"] == (BAI, "F-job")
    assert up.cay[f"F-{BAI}"] == [f"{i:02d}.jpg" for i in range(1, 9)]
    assert up.hang_luc_upload == [0] * 8                       # chưa có hàng nào khi còn đang upload
    hang = _hang(db)
    assert [h["thu_tu"] for h in hang] == list(range(1, 9))
    assert {h["loai"] for h in hang} == {"anh"} and {h["bai_id"] for h in hang} == {BAI}
    assert [h["video_id"] for h in hang] == [f"{BAI}-{i:02d}" for i in range(1, 9)]
    assert {h["bai_thu_muc_id"] for h in hang} == {f"F-{BAI}"}
    assert [h["drive_file_id"] for h in hang] == [f"T{i}" for i in range(1, 9)]
    thumb = lifecycle.thumb_path_for(db, f"{BAI}-01")
    assert thumb.is_file() and thumb.stat().st_size > 0
    with Image.open(thumb) as im:
        assert im.format == "WEBP" and im.width <= lifecycle.THUMB_WIDTH
    assert not (tmp / "tai" / BAI).exists()
    assert up.da_trash == []


def test_upload_tep_thu_ba_truot_khong_hang_trash_thu_muc(moi_truong):
    db, job_id, tmp = moi_truong
    tep = _tao_tep(tmp, 5)
    up = UploaderGia(hong_tep=3)
    kq = lifecycle_anh.on_bai_anh_verified(job_id=job_id, ref=_ref(), tep=tep, db_path=db, uploader=up)
    assert not kq.ok
    assert _hang(db) == []
    assert up.da_trash == [f"F-{BAI}"]                         # thư mục bài dở bị trash
    assert not (tmp / "tai" / BAI).exists()                    # local xoá: chạy lại sẽ tải lại
    assert lifecycle.get_backpressure_status().consecutive_failures == 1   # cầu dao đếm đúng một lần trượt
    assert up.so_upload == 3                                   # dừng ngay, không đẩy nốt


def test_trash_truot_van_failed_khong_hang_va_log_he_qua(moi_truong, caplog):
    db, job_id, tmp = moi_truong
    tep = _tao_tep(tmp, 3)
    up = UploaderGia(hong_tep=2, trash_ok=False)
    with caplog.at_level("ERROR", logger="ttmd.lifecycle_anh"):
        kq = lifecycle_anh.on_bai_anh_verified(job_id=job_id, ref=_ref(), tep=tep, db_path=db, uploader=up)
    assert not kq.ok and _hang(db) == []
    assert any("trùng" in r.getMessage() for r in caplog.records)
    assert not (tmp / "tai" / BAI).exists()


def test_thu_muc_job_khong_tao_duoc_bai_failed_cau_dao_dem_khong_hang(moi_truong):
    db, job_id, tmp = moi_truong
    tep = _tao_tep(tmp, 3)
    up = UploaderGia(job_folder_ok=False)
    kq = lifecycle_anh.on_bai_anh_verified(job_id=job_id, ref=_ref(), tep=tep, db_path=db, uploader=up)
    assert not kq.ok and kq.outcome is UploadOutcome.FAILED
    assert up.so_upload == 0                                   # KHÔNG rơi về gốc Shared Drive
    assert _hang(db) == []
    assert lifecycle.get_backpressure_status().consecutive_failures == 1
    assert not (tmp / "tai" / BAI).exists()


def test_drive_chua_cau_hinh_khong_tinh_vao_cau_dao(moi_truong):
    db, job_id, tmp = moi_truong
    up = UploaderGia(job_folder_ok=False, cau_hinh=False)
    kq = lifecycle_anh.on_bai_anh_verified(job_id=job_id, ref=_ref(), tep=_tao_tep(tmp, 2), db_path=db, uploader=up)
    assert kq.outcome is UploadOutcome.NOT_CONFIGURED
    assert lifecycle.get_backpressure_status().consecutive_failures == 0


def test_ghi_db_trat_thi_trash_thu_muc_va_bai_failed(moi_truong, monkeypatch):
    db, job_id, tmp = moi_truong
    from web import models_anh

    def hong(*a, **k):
        raise sqlite3.OperationalError("khoa")
    monkeypatch.setattr(models_anh, "ghi_bai_anh", hong)
    up = UploaderGia()
    kq = lifecycle_anh.on_bai_anh_verified(job_id=job_id, ref=_ref(), tep=_tao_tep(tmp, 2), db_path=db, uploader=up)
    assert not kq.ok and up.da_trash == [f"F-{BAI}"]
    assert not (tmp / "tai" / BAI).exists()
