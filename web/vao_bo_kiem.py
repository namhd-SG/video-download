"""Bộ kiểm "đã vào bộ": đo bằng chứng trên Drive, và ẨN video khi bằng chứng đạt.

Bằng chứng cho video X = có ≥1 bản copy hợp lệ (`vao_bo_drive.ban_hop_le`) của tệp
nguồn của X. Bản copy được tìm bằng dấu `properties.videodesk_src` (bản Creative
Desk copy) — và, ở lượt kiểm lại ngày 7, thêm các bản đã ghi lúc ẩn (`video_vao_bo_ban`,
gồm cả bản backfill md5 không có dấu).

THỨ TỰ GHI (luật guard-marker): mốc ẩn `an_luc` và các hàng `video_vao_bo_ban` chỉ được
ghi SAU khi bằng chứng đạt — không bao giờ trước. Ghi mốc trước rồi đo trượt thì video
biến khỏi lưới trong khi chưa có gì chứng tỏ nó đã vào bộ, và không có gì báo.

KHOẢNG HỞ ĐÃ CHẤP NHẬN của lượt 15 phút (pha (a) chọn A ∪ T ∪ H, `chay_luot_kiem`): một
nguồn CHƯA TỪNG bị ẩn và CHƯA TỪNG có hàng báo động mà bị XOÁ HẲN / bị dọn khỏi Thùng rác
(không còn trong danh sách Thùng rác), hoặc có `mimeType` không phải `video/*` (nên truy vấn
Thùng rác không thấy), hoặc mất quyền/404 từng tệp — CHỈ được lượt QUÉT ĐẦY ĐỦ mỗi ngày VN
bắt, trễ ≤ 24 giờ. Ngoài ra: video ĐÃ ẨN không được đo lại khi dọn ngày 7 đang TẮT (lượt
kiểm ẩn chỉ xét video chưa ẩn; đo lại lúc dọn nằm trong `vao_bo_don`, mà nó tắt).

Ba kết quả của một lần đo, KHÔNG gộp:
  * DAT            — Drive trả lời và có ≥1 bản hợp lệ.
  * AM             — Drive trả lời (200) ở MỌI lời gọi, đọc HẾT mọi trang, và 0 bản hợp lệ.
  * KHONG_DO_DUOC  — có lời gọi ném lỗi (403/5xx/timeout/…): KHÔNG suy ra gì về bằng chứng.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from web import models_vao_bo
from web.vao_bo_drive import (KHOA_DAU_NGUON, TOI_DA_ID_MOI_LO, DriveKhongThay, DriveVaoBo,
                              chon_folder, doc_het_trang, ban_hop_le, id_drive_hop_le,
                              ma_bo_tu_ten)

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


def bao_dong_nguon_chet(video_id: str, nguon_id: str, ly_do: str, *, da_an: bool) -> None:
    """`da_an`: video ĐÃ bị ẩn nên được hiện lại (ngày 7). False: chưa từng bị ẩn, vẫn hiện
    từ đầu — câu "được hiện lại" sẽ là nói sai."""
    hau_qua = ("video được hiện lại để khôi phục kịp trước khi Drive dọn Thùng rác" if da_an
               else "video chưa từng bị ẩn (vẫn hiện) — cần khôi phục tệp nguồn kịp trước khi "
                    "Drive dọn Thùng rác")
    log.error("BÁO ĐỘNG %s: video %s, tệp nguồn %s đã chết và không còn bản sao nào — %s",
              ly_do, video_id, nguon_id, hau_qua)


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
    # Nhật ký chi phí của lượt (in ở cuối MỖI lượt): |A|, |T|, |H| — None nếu pha (a) không
    # chạy (lượt quét đầy đủ, hoặc pha (a) trượt) — cùng số lời gọi Drive thật đã tốn.
    n_a: int | None = None
    n_t: int | None = None
    n_h: int | None = None
    n_r: int | None = None              # |R|: tập thử-lại đọc được lúc chọn ứng viên
    so_goi_drive: int = 0
    fallback: bool = False
    quet_day_du: bool = False


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


class _DemGoi:
    """Bọc một `DriveVaoBo` để ĐẾM mọi lời gọi Drive của lượt (trừ `dang_cau_hinh`)."""

    def __init__(self, drive: DriveVaoBo):
        self._drive = drive
        self.so_goi = 0

    def __getattr__(self, ten):
        f = getattr(self._drive, ten)
        if ten == "dang_cau_hinh" or not callable(f):
            return f

        def boc(*a, **k):
            self.so_goi += 1
            return f(*a, **k)
        return boc


def _pha_a(drive: DriveVaoBo, nguon_ids: list[str]) -> tuple[set[str], set[str]]:
    """Pha (a) của lượt 15 phút — RẺ, chỉ để CHỌN ứng viên đáng đo bằng chứng đầy đủ.

    A = nguồn ứng viên có ≥1 bản mang dấu, hỏi theo lô ≤ `TOI_DA_ID_MOI_LO` id, đọc HẾT
        trang của từng lô (trang rỗng kèm token KHÔNG phải hết).
    T = nguồn ứng viên đang ở Thùng rác: MỘT truy vấn liệt kê video trong thùng rác,
        đọc hết trang, giao với tập ứng viên.
    Lời gọi nào ném (403/404/5xx/timeout…) thì hàm này ném — người gọi QUÉT ĐỦ, tuyệt đối
    không đọc lỗi thành "không có".
    """
    tap = set(nguon_ids)
    a: set[str] = set()
    for i in range(0, len(nguon_ids), TOI_DA_ID_MOI_LO):
        lo = nguon_ids[i:i + TOI_DA_ID_MOI_LO]
        tep = doc_het_trang(lambda t, lo=lo: drive.liet_ke_ban_sao_theo_lo(lo, t))
        a |= {(f.get("properties") or {}).get(KHOA_DAU_NGUON) for f in tep} & tap
    thung = doc_het_trang(lambda t: drive.liet_ke_video_thung_rac(t))
    return a, {f["id"] for f in thung} & tap


def chay_luot_kiem(db_path: Path, drive: DriveVaoBo, *,
                   dung: Callable[[], bool] = lambda: False,
                   bay_gio: datetime | None = None) -> KetQuaLuotKiem:
    """Một lượt: đo bằng chứng và ẨN video khi bằng chứng đạt.

    MỖI lượt = pha (a) rồi pha (b):
      (a) chọn ứng viên đáng đo: A ∪ T ∪ H ∪ R (xem `_pha_a`; H = ứng viên đã có hàng báo
          động; R = tập THỬ LẠI: ứng viên mà lần đo trước trả "chưa đo được").
      (b) `do_bang_chung` ĐẦY ĐỦ (không đổi) cho các ứng viên được chọn.
    Pha (a) trượt ở BẤT KỲ lời gọi nào ⇒ log lỗi và pha (b) cho MỌI ứng viên lượt này.
    Lượt đầu tiên sau 00:00 giờ VN của mỗi ngày là lượt QUÉT ĐẦY ĐỦ: pha (b) cho MỌI ứng
    viên, không cần pha (a) — bắt ca mất quyền/404 từng tệp mà chưa từng báo, trễ ≤ 24 giờ.
    Ngày quét đầy đủ được ghi SAU khi lượt quét chạy hết (khởi động lại không bỏ/lặp), kể cả
    khi vài ứng viên "chưa đo được": chúng vào tập R và được đo lại ở MỖI lượt 15 phút cho
    tới khi đo được (rời R khi ra DAT hoặc AM; trượt lại thì ở lại) — một tệp hỏng vĩnh viễn
    không kéo cả lượt quét đầy đủ về mỗi 15 phút. NGOẠI LỆ: quét hỏng TOÀN BỘ (mọi ứng
    viên đã xét đều "chưa đo được", ≥1) là một cú chớp Drive, không phải một lượt quét ⇒
    KHÔNG ghi ngày, lượt sau quét lại.

    Không có giới hạn theo tuổi video: mọi ứng viên đều có thể được chọn ở pha (a).
    `dung()` được hỏi giữa hai ứng viên để thoát sạch.
    """
    bay_gio = bay_gio or datetime.now(timezone.utc)
    hom_nay = models_vao_bo.ngay_vn(bay_gio)
    kq = KetQuaLuotKiem()
    d = _DemGoi(drive)
    ten_cache: dict[str, str] = {}
    ung_vien = []
    for u in models_vao_bo.ung_vien_can_kiem(db_path):
        if id_drive_hop_le(u["drive_file_id"]):
            ung_vien.append(u)
        else:
            kq.id_sai += 1

    kq.quet_day_du = models_vao_bo.doc_ngay_quet_day_du(db_path) != hom_nay
    tap_r = models_vao_bo.doc_tap_thu_lai(db_path)
    kq.n_r = len(tap_r)
    if kq.quet_day_du:
        chon = ung_vien
    else:
        h = models_vao_bo.video_da_bao_dong(db_path)
        try:
            a, t = _pha_a(d, [u["drive_file_id"] for u in ung_vien]) if ung_vien else (set(), set())
        except Exception as exc:  # noqa: BLE001 — MỌI lỗi pha (a): quét đủ, không nuốt, không đọc là âm
            kq.fallback = True
            log.error("pha (a) của lượt kiểm trượt (%s%s) — QUÉT ĐỦ pha (b) cho mọi %d ứng viên "
                      "lượt này", type(exc).__name__,
                      f" HTTP {exc.resp.status}" if getattr(exc, "resp", None) is not None else "",
                      len(ung_vien))
            chon = ung_vien
        else:
            kq.n_a, kq.n_t = len(a), len(t)
            kq.n_h = sum(1 for u in ung_vien if u["video_id"] in h)
            chon = [u for u in ung_vien if u["drive_file_id"] in a or u["drive_file_id"] in t
                    or u["video_id"] in h or u["video_id"] in tap_r]

    bi_dung = False
    do_duoc: set[str] = set()       # ứng viên lượt này ĐO ĐƯỢC (DAT/AM) ⇒ rời R
    khong_duoc: set[str] = set()    # ứng viên lượt này "chưa đo được" ⇒ vào/ở lại R
    for u in chon:
        if dung():
            bi_dung = True
            break
        kq.da_xet += 1
        nguon_id = u["drive_file_id"]
        do = do_bang_chung(d, nguon_id)
        if do.trang_thai == KHONG_DO_DUOC:
            kq.khong_do_duoc += 1
            khong_duoc.add(u["video_id"])
            continue
        do_duoc.add(u["video_id"])
        if do.trang_thai == AM:
            ly_do = ly_do_nguon_chet(do)
            if ly_do:
                # Nguồn đã chết mà không có bản sao: báo ở MỌI lượt còn đúng.
                bao_dong_nguon_chet(u["video_id"], nguon_id, ly_do, da_an=False)
                models_vao_bo.ghi_bao_dong(db_path, u["video_id"], u["chu"], ly_do)
                kq.bao_dong += 1
            else:
                # Nguồn đã SỐNG lại (khôi phục khỏi Thùng rác…): hết báo động, gỡ dấu để
                # badge quản trị và tập H thôi phình.
                models_vao_bo.xoa_bao_dong(db_path, u["video_id"])
            kq.chua_co_bang_chung += 1
            continue
        if do.nguon is None:
            # Nguồn đã mất nhưng có bản sao: không đủ để so md5/size/parents ⇒ không ẩn
            # (dọn ngày 7 mới dùng bằng chứng một phần cho ca này).
            kq.nguon_mat += 1
            continue
        try:
            dong = _dong_ban(d, do.nguon, do.ban, ten_cache)
        except Exception as exc:  # noqa: BLE001
            log.warning("tra tên folder bộ trượt (%s) — thử lại lượt sau", type(exc).__name__)
            kq.khong_do_duoc += 1
            do_duoc.discard(u["video_id"])
            khong_duoc.add(u["video_id"])
            continue
        if not dong:
            kq.chua_co_bang_chung += 1
            continue
        # CHỈ TỚI ĐÂY mới ghi: bằng chứng đã đạt và tên bộ đã có.
        models_vao_bo.ghi_da_vao_bo(db_path, u["video_id"], u["chu"], dong)
        kq.da_an += 1

    # Tập R mới = (R cũ ∩ ứng viên còn lại − vừa đo được) ∪ vừa "chưa đo được". Ứng viên đã
    # ẩn/loại/dọn tự rời R; ứng viên chưa tới lượt này (bị dừng giữa chừng) giữ nguyên.
    con_ung_vien = {u["video_id"] for u in ung_vien}
    models_vao_bo.ghi_tap_thu_lai(db_path, ((tap_r & con_ung_vien) - do_duoc) | khong_duoc)
    # Ghi ngày quét khi lượt quét chạy HẾT (không bị dừng) VÀ không hỏng toàn bộ. Vài ứng
    # viên "chưa đo được" thì đã nằm trong R (được thử lại mỗi lượt). Hỏng TOÀN BỘ thì không
    # ai được đo: đánh dấu xong là bịt cửa sổ phát hiện đến hết ngày ⇒ để lượt sau quét lại.
    hong_toan_bo = kq.da_xet > 0 and kq.khong_do_duoc == kq.da_xet
    if kq.quet_day_du and not bi_dung and not hong_toan_bo:
        models_vao_bo.ghi_ngay_quet_day_du(db_path, hom_nay)   # SAU khi quét xong
    kq.so_goi_drive = d.so_goi
    log.info("lượt kiểm đã-vào-bộ: |A|=%s |T|=%s |H|=%s |R|=%s ứng_viên=%d đã_đo=%d lời_gọi_drive=%d "
             "fallback=%s quét_đầy_đủ=%s đã_ẩn=%d không_đo_được=%d",
             kq.n_a, kq.n_t, kq.n_h, kq.n_r, len(ung_vien), kq.da_xet, kq.so_goi_drive, kq.fallback,
             kq.quet_day_du, kq.da_an, kq.khong_do_duoc)
    return kq
