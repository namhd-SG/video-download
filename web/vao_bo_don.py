"""Dọn ngày thứ 7: tệp NGUỒN của video đã vào bộ đi vào Thùng rác Drive.

"Dọn" = bỏ vào THÙNG RÁC (`trash_file`, cùng cơ chế nút Loại; giữ nguyên hợp đồng của
nó). KHÔNG `files().delete()` (service account không có quyền và không nên có), KHÔNG
đụng bản trong bộ, KHÔNG xoá hàng `videos` (phải còn để `known_video_ids` né tải lại).

Với mỗi video đã ẩn đủ 7 ngày mà chưa dọn (`models_vao_bo.ung_vien_don`, BẤT KỂ
`da_loai_luc`):
  1. Người dùng đã Loại tay ⇒ ghi mốc dọn lý do `da_loai`, KHÔNG gọi Drive (tệp đã ở
     Thùng rác; nếu họ khôi phục tay thì không được trash lại).
  2. Kiểm lại TRỌN bằng chứng (`vao_bo_kiem.do_bang_chung`, gồm cả bản đã ghi lúc ẩn):
        · KHÔNG ĐO ĐƯỢC (lỗi Drive)  ⇒ giữ nguyên mốc, tăng `so_lan_truot`, báo động;
        · ĐO RA ÂM (200 + 0 bản đạt sau khi đọc hết trang) ⇒ HIỆN LẠI video, không trash;
        · ĐẠT ⇒ sang bước 3.
  3. Nguồn đã ở Thùng rác ⇒ mốc `da_o_thung_rac`; nguồn 404 ⇒ mốc `khong_con` (đều
     KHÔNG gọi `trash_file`); còn lại ⇒ `trash_file(drive_file_id của NGUỒN)` và CHỈ
     khi Drive báo ok mới ghi mốc `da_don`. Trượt ⇒ không ghi mốc, `so_lan_truot`+1,
     và BÁO ĐỘNG Ở MỌI LƯỢT còn trượt (mốc "đã báo động" khác mốc "đã xong").

Mốc ghi bằng `UPDATE … WHERE drive_don_luc IS NULL` trong `BEGIN IMMEDIATE`. Không có
cờ khoá "đang dọn".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from web import models_vao_bo
from web.vao_bo_drive import DriveVaoBo, id_drive_hop_le
from web.vao_bo_kiem import AM, KHONG_DO_DUOC, do_bang_chung

log = logging.getLogger("videodl.web.vao_bo")

LY_DO_DA_LOAI = "da_loai"
LY_DO_DA_O_THUNG_RAC = "da_o_thung_rac"
LY_DO_KHONG_CON = "khong_con"
LY_DO_DA_DON = "da_don"


@dataclass
class KetQuaLuotDon:
    ung_vien: int = 0
    da_loai: int = 0
    da_o_thung_rac: int = 0
    khong_con: int = 0
    da_bo_thung_rac: int = 0
    hien_lai: int = 0
    khong_do_duoc: int = 0
    trash_truot: int = 0
    truot: list = field(default_factory=list)      # [(video_id, so_lan_truot, loi)]


def _bao_dong(db_path: Path, kq: KetQuaLuotDon, video_id: str, loi: str, viec: str) -> None:
    """Ghi trượt + báo động. Gọi Ở MỌI LƯỢT còn trượt — không có nhánh "đã báo rồi"."""
    so_lan = models_vao_bo.ghi_truot_don(db_path, video_id, loi)
    kq.truot.append((video_id, so_lan, loi))
    log.error("BÁO ĐỘNG dọn video %s: %s trượt lần thứ %d (%s) — mốc dọn CHƯA ghi, "
              "lượt sau thử lại", video_id, viec, so_lan, loi)


def chay_luot_don(db_path: Path, drive: DriveVaoBo, *, bay_gio: datetime | None = None,
                  dung: Callable[[], bool] = lambda: False) -> KetQuaLuotDon:
    kq = KetQuaLuotDon()
    for u in models_vao_bo.ung_vien_don(db_path, bay_gio):
        if dung():
            break
        kq.ung_vien += 1
        vid, nguon_id = u["video_id"], u["drive_file_id"]
        if u["da_loai"]:
            if models_vao_bo.ghi_don_drive(db_path, vid, LY_DO_DA_LOAI):
                kq.da_loai += 1
            continue
        if not id_drive_hop_le(nguon_id):
            _bao_dong(db_path, kq, vid, "drive_file_id sai hình dạng", "kiểm lại")
            kq.khong_do_duoc += 1
            continue
        ban_da_ghi = tuple(b["ban_copy_id"] for b in models_vao_bo.ban_cua_video(db_path, vid))
        do = do_bang_chung(drive, nguon_id, ban_da_ghi)
        if do.trang_thai == KHONG_DO_DUOC:
            # Giữ NGUYÊN mốc ẩn (không reset đồng hồ 7 ngày): chưa đo được ≠ đo ra âm.
            kq.khong_do_duoc += 1
            _bao_dong(db_path, kq, vid, do.loi or "loi", "kiểm lại bằng chứng")
            continue
        if do.trang_thai == AM:
            if models_vao_bo.bo_an(db_path, vid, u["an_luc"]):
                kq.hien_lai += 1
            continue
        if do.nguon_khong_con:
            if models_vao_bo.ghi_don_drive(db_path, vid, LY_DO_KHONG_CON):
                kq.khong_con += 1
            continue
        if do.nguon.get("trashed"):
            if models_vao_bo.ghi_don_drive(db_path, vid, LY_DO_DA_O_THUNG_RAC):
                kq.da_o_thung_rac += 1
            continue
        try:
            ok = drive.bo_vao_thung_rac(nguon_id)
            loi = "trash_file không ok"
        except Exception as exc:  # noqa: BLE001
            ok, loi = False, type(exc).__name__
        if not ok:
            kq.trash_truot += 1
            _bao_dong(db_path, kq, vid, loi, "bỏ vào Thùng rác")
            continue
        # CHỈ SAU khi Drive báo ok.
        if models_vao_bo.ghi_don_drive(db_path, vid, LY_DO_DA_DON):
            kq.da_bo_thung_rac += 1
    if kq.ung_vien:
        log.info("lượt dọn ngày 7: %s", kq)
    return kq
