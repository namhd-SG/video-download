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
from web.vao_bo_kiem import (AM, KHONG_DO_DUOC, bao_dong_nguon_chet, do_bang_chung,
                             ly_do_nguon_chet)

log = logging.getLogger("videodl.web.vao_bo")

LY_DO_DA_LOAI = "da_loai"
LY_DO_DA_O_THUNG_RAC = "da_o_thung_rac"
LY_DO_KHONG_CON = "khong_con"
LY_DO_DA_DON = "da_don"

# CÔNG TẮC dọn ngày 7, MẶC ĐỊNH TẮT. Bật bằng biến môi trường này (`1`/`true`/`yes`/`on`).
# Khi tắt, `chay_luot_don` không gọi Drive và không ghi mốc nào — chỉ log số hàng đủ hạn
# đang chờ. Cổng này phủ MỌI đường dọn: hàng do backfill lẫn hàng do bộ kiểm ẩn.
# (Định nghĩa ở `models_vao_bo` — dùng chung với lọc hạn ở payload/thẻ; import lại ở đây.)
ENV_BAT_DON_NGAY7 = models_vao_bo.ENV_BAT_DON_NGAY7

# Trần số lần gọi `trash_file` MỖI LƯỢT; hàng vượt trần để lượt sau, không bao giờ bị bỏ.
# ⚠ 50 CHƯA hiệu chỉnh — không có phép đo nào về tốc độ/hạn ngạch Drive đứng sau con số
# này; nó được chọn theo chiều AN TOÀN (lượt đầu sau khi bật chỉ đụng tối đa 50 tệp).
TOI_DA_TRASH_MOI_LUOT = 50


don_ngay7_dang_bat = models_vao_bo.don_ngay7_dang_bat


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
    nguon_chet: int = 0
    dang_tat: bool = False              # công tắc tắt: không làm gì, chỉ đếm hàng đang chờ
    dang_cho: int = 0                   # số hàng đủ hạn khi công tắc tắt
    so_lan_trash: int = 0                   # số lần gọi trash (tính vào trần)
    truot: list = field(default_factory=list)      # [(video_id, so_lan_truot, loi)]


def _bao_dong(db_path: Path, kq: KetQuaLuotDon, video_id: str, loi: str, viec: str) -> None:
    """Ghi trượt + báo động. Gọi Ở MỌI LƯỢT còn trượt — không có nhánh "đã báo rồi"."""
    so_lan = models_vao_bo.ghi_truot_don(db_path, video_id, loi)
    kq.truot.append((video_id, so_lan, loi))
    log.error("BÁO ĐỘNG dọn video %s: %s trượt lần thứ %d (%s) — mốc dọn CHƯA ghi, "
              "lượt sau thử lại", video_id, viec, so_lan, loi)


def _bo_thung_rac(drive: DriveVaoBo, nguon_id: str) -> tuple[bool, str]:
    """MỘT chỗ duy nhất gọi Thùng rác cho tệp nguồn: `(ok, lỗi)`. Không ném."""
    try:
        return (True, "") if drive.bo_vao_thung_rac(nguon_id) else (False, "trash_file không ok")
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def chay_luot_don(db_path: Path, drive: DriveVaoBo, *, bay_gio: datetime | None = None,
                  dung: Callable[[], bool] = lambda: False) -> KetQuaLuotDon:
    kq = KetQuaLuotDon()
    ung_vien = models_vao_bo.ung_vien_don(db_path, bay_gio)
    if not don_ngay7_dang_bat():
        kq.dang_tat, kq.dang_cho = True, len(ung_vien)
        log.warning("dọn ngày 7 đang TẮT, %d hàng đủ hạn đang chờ (bật bằng %s=1)",
                    len(ung_vien), ENV_BAT_DON_NGAY7)
        return kq
    for u in ung_vien:
        if dung() or kq.so_lan_trash >= TOI_DA_TRASH_MOI_LUOT:
            break               # hàng còn lại sang lượt sau (không mất: vẫn là ứng viên)
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
            ly_do = ly_do_nguon_chet(do)
            if ly_do:
                # Bản trong Thùng rác / đã mất là bản DUY NHẤT: hiện lại video và báo động.
                bao_dong_nguon_chet(vid, nguon_id, ly_do, da_an=True)
                kq.nguon_chet += 1
            if models_vao_bo.bo_an(db_path, vid, u["an_luc"], giu_bao_dong=ly_do):
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
        kq.so_lan_trash += 1
        ok, loi = _bo_thung_rac(drive, nguon_id)
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
