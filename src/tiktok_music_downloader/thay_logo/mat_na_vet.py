"""Mặt nạ thay logo = HỢP mọi vết theo khung: vùng mà `render` sẽ tô lấp + dán tấm nền ở từng khung.

Một nguồn sự thật cho cả render lẫn nghiệm thu: "watermark đã che ⟺ điểm của nó nằm trong mặt nạ ở đúng khung đó". Vùng của một ô =
box đã làm mượt nới `max(PAD_TO, plate_pad)` px (tô lấp nới PAD_TO, tấm nền A2 nới plate_pad).
"""
from __future__ import annotations

from .render import PAD_TAM_NEN, PAD_TO


def vung_o(e: dict) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) vùng bị thay của một ô vết."""
    p = max(PAD_TO, e.get("plate_pad", PAD_TAM_NEN))
    return e["x"] - p, e["y"] - p, e["x"] + e["w"] + p, e["y"] + e["h"] + p


def mat_na_theo_khung(vet) -> dict[int, list[tuple[int, int, int, int]]]:
    """`vet` = các KetQuaVet. Chỉ vết được phép render đóng góp. Trả {khung: [vùng, …]}."""
    out: dict[int, list] = {}
    for v in vet:
        if v.trang_thai != "render":
            continue
        for e in v.khung_render:
            out.setdefault(e["frame"], []).append(vung_o(e))
    return out


def diem_trong_mat_na(mat_na: dict[int, list], khung: int, x: float, y: float, dung_sai: float = 0.0) -> bool:
    """Điểm (x, y) pixel ở `khung` nằm trong mặt nạ (nới `dung_sai` px)?"""
    return any(x0 - dung_sai <= x <= x1 + dung_sai and y0 - dung_sai <= y <= y1 + dung_sai
               for x0, y0, x1, y1 in mat_na.get(khung, ()))
