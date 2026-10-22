"""Truy vấn hop 1 sinh TỪ chữ ký (ĐK4): từ vựng cấu trúc chỉ dùng khi chữ ký có cấu trúc đó.

GĐ1: truy vấn chủ đề ("ai clone fashion video") ra 0–1/10 đúng dạng; truy vấn cấu trúc/tên trend ("7 pose ai trend") ra 9/10.
⇒ Nhóm cấu trúc luôn đứng trước. Bản ES/PT của từ vựng cấu trúc CHƯA đo hiệu quả (IP VN, chưa có proxy).
"""
from __future__ import annotations

from dataclasses import dataclass

from .cham import ChuKy


@dataclass(frozen=True)
class TruyVan:
    text: str
    nhom: str   # "cau_truc" | "chu_de" | "san_pham" | "mo_rong"
    lang: str   # en | es | pt | <mã ngôn ngữ caption gốc>
    loai: str = "search"   # "search" | "tag"


def _cau_truc(ck: ChuKy) -> list[TruyVan]:
    if ck.bac == ">=3":
        n = ck.so_ban_sao
        return [TruyVan(f"{n} pose ai trend", "cau_truc", "en"),
                TruyVan("lookbook ai multi pose collage outfit", "cau_truc", "en"),
                TruyVan(f"ai collage {n} poses", "cau_truc", "en"),
                TruyVan(f"tendencia ia {n} poses", "cau_truc", "es"),
                TruyVan(f"trend ia {n} poses", "cau_truc", "pt")]
    if ck.bac == "1" and ck.hanh_dong == "catwalk":
        return [TruyVan("ai catwalk", "cau_truc", "en"),
                TruyVan("ai runway walk fashion", "cau_truc", "en"),
                TruyVan("ia pasarela moda", "cau_truc", "es"),
                TruyVan("ia desfile passarela", "cau_truc", "pt")]
    return []   # dạng khác: chưa có từ vựng đã đo ⇒ dựa vào nhóm agy sinh


def sinh_truy_van(ck: ChuKy, tu_agy: list[TruyVan], toi_da: int) -> list[TruyVan]:
    """Cấu trúc trước, rồi tới truy vấn agy sinh (chủ đề/sản phẩm). Bỏ trùng không phân biệt hoa thường; cắt ở `toi_da`."""
    ra: list[TruyVan] = []
    da: set[str] = set()
    for tv in _cau_truc(ck) + list(tu_agy):
        khoa = " ".join(tv.text.lower().split())
        if not khoa or khoa in da:
            continue
        if ck.bac != ">=3" and any(t in khoa for t in ("collage", "multi pose", "kolase")):
            continue   # chữ ký không có bản sao ⇒ không kéo về video ghép (tiêu chí nghiệm thu video 2)
        da.add(khoa)
        ra.append(tv)
    return ra[:toi_da]
