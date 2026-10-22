"""Trường NHÌN THẤY mà agy bóc từ một ảnh (khung video hoặc ảnh bìa). agy không chấm điểm: điểm do `cham.py` tính.

Giá trị ngoài bảng ⇒ "khac" (không đoán ý agy). Số bản sao không đọc được ⇒ None, ảnh đó không được xếp hạng.
"""
from __future__ import annotations

from dataclasses import dataclass

CHU_THE = ("nguoi mau thoi trang", "nguoi thuong", "dong vat", "khac")
LOAI_NEN = ("trang_tron", "mau_tron", "studio", "san_dien", "ngoai_troi", "trong_nha", "khac")
HANH_DONG = ("tao_dang", "catwalk", "nhay", "noi_chuyen", "khac")


@dataclass(frozen=True)
class TruongAnh:
    id: str
    so_ban_sao: int | None   # số lần CÙNG MỘT người xuất hiện trong ảnh; 0 = không có người
    chu_the: str
    loai_nen: str
    hanh_dong: str
    la_luoi: bool            # ảnh chia ô vuông rõ ràng (ghép nhiều ảnh rời)
    la_tutorial: bool        # tutorial / giao diện app / chữ hướng dẫn lớn
    chu_ocr: str = ""
    mo_ta: str = ""


def _enum(gia_tri: object, bang: tuple[str, ...]) -> str:
    return gia_tri if isinstance(gia_tri, str) and gia_tri in bang else "khac"


def _so(gia_tri: object) -> int | None:
    if isinstance(gia_tri, bool) or not isinstance(gia_tri, int) or gia_tri < 0:
        return None
    return gia_tri


def tu_json(muc: dict) -> TruongAnh:
    """Một mục agy trả về ⇒ `TruongAnh`. Nhận cả tên trường cũ của GĐ1 để đọc lại dữ liệu đã đo."""
    return TruongAnh(
        id=str(muc.get("id", "")),
        so_ban_sao=_so(muc.get("so_ban_sao", muc.get("so_ban_sao_cung_mot_nguoi"))),
        chu_the=_enum(muc.get("chu_the"), CHU_THE),
        loai_nen=_enum(muc.get("loai_nen"), LOAI_NEN),
        hanh_dong=_enum(muc.get("hanh_dong"), HANH_DONG),
        la_luoi=bool(muc.get("la_luoi", muc.get("la_luoi_chia_o", False))),
        la_tutorial=bool(muc.get("la_tutorial", muc.get("la_tutorial_hoac_giao_dien_app", False))),
        chu_ocr=str(muc.get("chu_ocr", muc.get("chu_ocr_tren_hinh", "")) or ""),
        mo_ta=str(muc.get("mo_ta", "") or ""),
    )
