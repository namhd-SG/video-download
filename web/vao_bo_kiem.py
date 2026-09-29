"""Bộ kiểm "đã vào bộ": đo bằng chứng trên Drive, và ẨN video khi bằng chứng đạt.

Bằng chứng cho video X = có ≥1 bản copy hợp lệ (`vao_bo_drive.ban_hop_le`) của tệp
nguồn của X. Bản copy được tìm bằng dấu `properties.videodesk_src` (bản Creative
Desk copy) — và, ở lượt kiểm lại ngày 7, thêm các bản đã ghi lúc ẩn (`video_vao_bo_ban`,
gồm cả bản backfill md5 không có dấu).

THỨ TỰ GHI (luật guard-marker): mốc ẩn `an_luc` và các hàng `video_vao_bo_ban` chỉ được
ghi SAU khi bằng chứng đạt — không bao giờ trước. Ghi mốc trước rồi đo trượt thì video
biến khỏi lưới trong khi chưa có gì chứng tỏ nó đã vào bộ, và không có gì báo.

Ba kết quả của một lần đo, KHÔNG gộp:
  * DAT            — Drive trả lời và có ≥1 bản hợp lệ.
  * AM             — Drive trả lời (200) ở MỌI lời gọi, đọc HẾT mọi trang, và 0 bản hợp lệ.
  * KHONG_DO_DUOC  — có lời gọi ném lỗi (403/5xx/timeout/…): KHÔNG suy ra gì về bằng chứng.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from web import models_vao_bo
from web.vao_bo_drive import (DriveKhongThay, DriveVaoBo, chon_folder, doc_het_trang,
                              ban_hop_le, id_drive_hop_le, ma_bo_tu_ten)

log = logging.getLogger("videodl.web.vao_bo")

DAT, AM, KHONG_DO_DUOC = "dat", "am", "khong_do_duoc"

# Bằng chứng ÂM mà tệp nguồn cũng đã chết: bản trong Thùng rác (hoặc đã mất) là bản DUY
# NHẤT còn lại, và Drive dọn Thùng rác sau ~30 ngày. Video được HIỆN LẠI (để ai đó khôi
# phục được) và báo động Ở MỌI LƯỢT khi điều này còn đúng — không dedupe.
LY_DO_NGUON_O_THUNG_RAC = "nguon_o_thung_rac_khong_ban_sao"
LY_DO_NGUON_404 = "nguon_404_khong_ban_sao"


def ly_do_nguon_chet(do: "KetQuaBangChung") -> str | None:
    """Mã lý do nếu nguồn đã chết (404 / trong Thùng rác); None nếu nguồn còn sống."""
    if do.nguon_khong_con:
        return LY_DO_NGUON_404
    if do.nguon is not None and do.nguon.get("trashed"):
        return LY_DO_NGUON_O_THUNG_RAC
    return None


def bao_dong_nguon_chet(video_id: str, nguon_id: str, ly_do: str) -> None:
    log.error("BÁO ĐỘNG %s: video %s, tệp nguồn %s đã chết và không còn bản sao nào — "
              "video được hiện lại để khôi phục kịp trước khi Drive dọn Thùng rác",
              ly_do, video_id, nguon_id)


@dataclass(frozen=True)
class KetQuaBangChung:
    trang_thai: str
    nguon: dict | None = None           # siêu dữ liệu nguồn; None nếu nguồn 404 / chưa đo
    nguon_khong_con: bool = False       # nguồn trả 404
    ban: tuple = ()                     # các bản hợp lệ (siêu dữ liệu thô của Drive)
    loi: str | None = None              # loại lỗi, khi KHONG_DO_DUOC


def do_bang_chung(drive: DriveVaoBo, nguon_id: str,
                  ban_da_biet: tuple[str, ...] = ()) -> KetQuaBangChung:
    """Đo bằng chứng cho tệp nguồn `nguon_id`. Không ghi gì, không ném."""
    try:
        try:
            nguon: dict | None = drive.lay_tep(nguon_id)
            khong_con = False
        except DriveKhongThay:
            nguon, khong_con = None, True
        tim_duoc = doc_het_trang(
            lambda token: drive.liet_ke_ban_sao_theo_dau(nguon_id, token))
        hop_le: dict[str, dict] = {
            b["id"]: b for b in tim_duoc
            if ban_hop_le(nguon_id, nguon, b, can_dau_nguon=True)}
        for ban_id in ban_da_biet:
            if ban_id in hop_le:
                continue
            try:
                b = drive.lay_tep(ban_id)
            except DriveKhongThay:
                continue                 # bản đã mất: một phép đo ÂM về bản đó
            if ban_hop_le(nguon_id, nguon, b, can_dau_nguon=False):
                hop_le[b["id"]] = b
    except Exception as exc:  # noqa: BLE001 — mọi lỗi Drive = "chưa đo được", không phải "không có"
        log.warning("đo bằng chứng cho nguồn %s trượt (%s)", nguon_id[:8], type(exc).__name__)
        return KetQuaBangChung(KHONG_DO_DUOC, loi=type(exc).__name__)
    return KetQuaBangChung(DAT if hop_le else AM, nguon, khong_con, tuple(hop_le.values()))


@dataclass
class KetQuaLuotKiem:
    da_xet: int = 0
    da_an: int = 0
    chua_co_bang_chung: int = 0
    khong_do_duoc: int = 0
    id_sai: int = 0
    nguon_mat: int = 0
    bao_dong: int = 0


def _dong_ban(drive: DriveVaoBo, nguon: dict | None, ban_hop_le_: tuple,
              ten_cache: dict[str, str]) -> list[dict]:
    """Hàng `video_vao_bo_ban` cho các bản hợp lệ. Ném nếu tra tên folder trượt —
    người gọi coi đó là "chưa đo được" (ghi `ma_bo` sai vĩnh viễn tệ hơn thử lại)."""
    ra = []
    for b in ban_hop_le_:
        folder = chon_folder(b, nguon)
        if folder is None:
            continue
        if folder not in ten_cache:
            ten_cache[folder] = drive.ten_thu_muc(folder)
        ra.append({"ban_copy_id": b["id"], "folder_id": folder,
                   "ma_bo": ma_bo_tu_ten(ten_cache[folder]), "bang_chung": "properties"})
    return ra


def chay_luot_kiem(db_path: Path, drive: DriveVaoBo, *,
                   dung: Callable[[], bool] = lambda: False) -> KetQuaLuotKiem:
    """Một lượt: với mỗi video còn sống chưa ẩn, đo bằng chứng và ẨN nếu đạt.

    Trả số đếm (không im lặng): `da_xet` = số ứng viên, `da_an` = số vừa ẩn.
    `dung()` (vd `stop_event.is_set`) được hỏi giữa hai ứng viên để thoát sạch.
    """
    kq = KetQuaLuotKiem()
    ten_cache: dict[str, str] = {}
    for u in models_vao_bo.ung_vien_can_kiem(db_path):
        if dung():
            break
        kq.da_xet += 1
        nguon_id = u["drive_file_id"]
        if not id_drive_hop_le(nguon_id):
            kq.id_sai += 1
            continue
        do = do_bang_chung(drive, nguon_id)
        if do.trang_thai == KHONG_DO_DUOC:
            kq.khong_do_duoc += 1
            continue
        if do.trang_thai == AM:
            ly_do = ly_do_nguon_chet(do)
            if ly_do:
                # Nguồn đã chết mà không có bản sao: báo ở MỌI lượt còn đúng.
                bao_dong_nguon_chet(u["video_id"], nguon_id, ly_do)
                models_vao_bo.ghi_bao_dong(db_path, u["video_id"], u["chu"], ly_do)
                kq.bao_dong += 1
            kq.chua_co_bang_chung += 1
            continue
        if do.nguon is None:
            # Nguồn đã mất nhưng có bản sao: không đủ để so md5/size/parents ⇒ không ẩn
            # (dọn ngày 7 mới dùng bằng chứng một phần cho ca này).
            kq.nguon_mat += 1
            continue
        try:
            dong = _dong_ban(drive, do.nguon, do.ban, ten_cache)
        except Exception as exc:  # noqa: BLE001
            log.warning("tra tên folder bộ trượt (%s) — thử lại lượt sau", type(exc).__name__)
            kq.khong_do_duoc += 1
            continue
        if not dong:
            kq.chua_co_bang_chung += 1
            continue
        # CHỈ TỚI ĐÂY mới ghi: bằng chứng đã đạt và tên bộ đã có.
        models_vao_bo.ghi_da_vao_bo(db_path, u["video_id"], u["chu"], dong)
        kq.da_an += 1
    if kq.da_an or kq.khong_do_duoc:
        log.info("lượt kiểm đã-vào-bộ: %s", kq)
    return kq
