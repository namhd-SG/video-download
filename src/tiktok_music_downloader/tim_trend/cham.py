"""Chữ ký DẠNG của video đầu vào + hạng khớp TẤT ĐỊNH của một ảnh ứng viên so với chữ ký đó.

Hạng: "3" đúng dạng · "2A" đúng dạng nhưng là tutorial · "2B" lệch đúng 1 tiêu chí phụ · "1" lệch cấu trúc · "0" khác chủ thể.
Ngưỡng mặc định giữ {3, 2A}: thước người 22/10 (user chấm 70 ảnh bìa) ⇒ precision 0,95 / recall 0,90.

Thứ tự luật là một phần của hợp đồng (agy plan-R1b ĐK2): chủ thể ⇒ lưới ⇒ bậc bản sao ⇒ cổng hành động ⇒ đếm lệch.
Xét lưới SAU bản sao thì ảnh lưới 4 ô có n≥3 lọt lên hạng 3 (lỗi GĐ1, agy R3b bắt).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median

from .truong import TruongAnh

NHOM_NGUOI = frozenset({"nguoi mau thoi trang", "nguoi thuong"})
NEN_TRON = frozenset({"trang_tron", "mau_tron", "studio"})
# Hành động đủ đặc trưng để làm cổng cứng khi chữ ký chỉ có 1 người (ĐK3): 1 người thì cổng bản sao gần như không lọc gì.
HANH_DONG_CONG = frozenset({"catwalk", "nhay", "noi_chuyen"})
NGUONG_MAC_DINH = frozenset({"3", "2A"})


def bac_ban_sao(n: int) -> str:
    return "0" if n <= 0 else "1" if n == 1 else "2" if n == 2 else ">=3"


def nhom_chu_the(chu_the: str) -> str:
    return "nguoi" if chu_the in NHOM_NGUOI else chu_the


def nhom_nen(loai_nen: str) -> str:
    return "tron" if loai_nen in NEN_TRON else loai_nen


@dataclass(frozen=True)
class ChuKy:
    so_ban_sao: int
    bac: str
    chu_the: str      # đã gom nhóm
    nen: str          # đã gom nhóm
    hanh_dong: str
    la_luoi: bool


def _da_so(gia_tri: list) -> object:
    return Counter(gia_tri).most_common(1)[0][0]


def chu_ky(khung: list[TruongAnh]) -> ChuKy:
    """Gộp các khung của video đầu vào: bản sao lấy trung vị, còn lại lấy đa số. Khung không đọc được số bị bỏ."""
    doc_duoc = [t for t in khung if t.so_ban_sao is not None]
    if not doc_duoc:
        raise ValueError("không khung nào của video đầu vào đọc được số bản sao")
    n = int(median(t.so_ban_sao for t in doc_duoc))
    return ChuKy(
        so_ban_sao=n,
        bac=bac_ban_sao(n),
        chu_the=_da_so([nhom_chu_the(t.chu_the) for t in doc_duoc]),
        nen=_da_so([nhom_nen(t.loai_nen) for t in doc_duoc]),
        hanh_dong=_da_so([t.hanh_dong for t in doc_duoc]),
        la_luoi=bool(_da_so([t.la_luoi for t in doc_duoc])),
    )


def hang(t: TruongAnh, ck: ChuKy) -> str | None:
    """Hạng của ảnh `t` so với chữ ký `ck`; None nếu agy không đọc được số bản sao (không đoán)."""
    if t.so_ban_sao is None:
        return None
    if nhom_chu_the(t.chu_the) != ck.chu_the or (ck.bac != "0" and t.so_ban_sao == 0):
        return "0"
    if t.la_luoi != ck.la_luoi:
        return "1"
    if bac_ban_sao(t.so_ban_sao) != ck.bac:
        return "1"
    if ck.bac == "1" and ck.hanh_dong in HANH_DONG_CONG:
        # 1 người làm một hành động đặc trưng: hành động là cổng cứng, nền chỉ phụ (catwalk ở sàn diễn/phố/studio đều tính).
        if t.hanh_dong != ck.hanh_dong:
            return "1"
        lech = 0
    else:
        lech = int(nhom_nen(t.loai_nen) != ck.nen)
        if "khac" not in (t.hanh_dong, ck.hanh_dong):
            lech += int(t.hanh_dong != ck.hanh_dong)
    if t.la_tutorial:
        return "2A" if lech == 0 else "1"
    return "3" if lech == 0 else "2B" if lech == 1 else "1"
