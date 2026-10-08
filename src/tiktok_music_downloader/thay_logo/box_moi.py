"""Box mồi: đầu vào DUY NHẤT để lõi biết watermark trông ra sao (ĐP-1492).

Nguồn box là agy học mẫu (vài khung thưa mỗi video) HOẶC người tạo job kéo khung tay. Lõi không phân biệt nguồn khi dựng
mẫu; nguồn chỉ được ghi lại để báo cáo. Gom vết + chọn mồi đồng thuận chép từ `p1a_t2_pipeline_v2.py` (đã tune trên Test 02).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .nguon_khung import NguonKhung

# Gom vết theo CỠ: box cùng video có (w, h) trong ±35% trung vị cụm ⇒ cùng một watermark. Cụm < MIN_BOX box ⇒ không đủ
# bằng chứng, vết đó "chờ người". (Plan §5c.1 đề xuất ≥4/6 & ±20%; số đã đo trên Test 02 là 3 & ±35%.)
DUNG_SAI_CO = 0.35
MIN_BOX = 3


@dataclass(frozen=True)
class BoxMoi:
    khung: int  # chỉ số khung trong video
    x: int
    y: int
    w: int
    h: int
    nguon: str = "agy"  # "agy" | "tay"


def box_tu_box_2d(box_2d, khung: int, rong: int, cao: int, nguon: str = "agy") -> BoxMoi | None:
    """Đổi box chuẩn agy `[ymin, xmin, ymax, xmax]` thang 0–1000 sang pixel. Box sai khuôn / rỗng ⇒ None (bỏ, không đoán)."""
    if not isinstance(box_2d, (list, tuple)) or len(box_2d) != 4:
        return None
    try:
        y0, x0, y1, x1 = (float(v) for v in box_2d)
    except (TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        return None
    return BoxMoi(khung, int(x0 * rong // 1000), int(y0 * cao // 1000),
                  max(4, int((x1 - x0) * rong // 1000)), max(4, int((y1 - y0) * cao // 1000)), nguon)


def gom_vet(boxes: list[BoxMoi]) -> list[list[BoxMoi]]:
    """Gom box theo cỡ, box lớn xét trước. Trả MỌI cụm (kể cả cụm thiếu box) — người gọi lọc theo MIN_BOX."""
    cum: list[list[BoxMoi]] = []
    for b in sorted(boxes, key=lambda z: -z.w * z.h):
        for cl in cum:
            w0 = float(np.median([z.w for z in cl]))
            h0 = float(np.median([z.h for z in cl]))
            if abs(b.w - w0) <= DUNG_SAI_CO * w0 and abs(b.h - h0) <= DUNG_SAI_CO * h0:
                cl.append(b)
                break
        else:
            cum.append([b])
    return cum


def _hp(g: np.ndarray, s: float = 2.0) -> np.ndarray:
    g = g.astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), s)


def chon_moi_dong_thuan(nguon: NguonKhung, cum: list[BoxMoi]) -> tuple[BoxMoi, float]:
    """Mồi = box có NCC trung bình cao nhất với mọi box còn lại của cụm (crop thông cao, đưa về cỡ trung vị).

    Lý do (Test 02 lượt 1): mồi = box agy ĐẦU học sai khi box đầu nằm trên màn kết/UI ⇒ mẫu sai tự nhất quán ⇒ phá nội dung.
    Trả (box mồi, NCC TB của nó)."""
    w0 = int(np.median([z.w for z in cum]))
    h0 = int(np.median([z.h for z in cum]))
    crops: list[np.ndarray | None] = []
    for b in cum:
        g = nguon.doc(b.khung)
        c = g[b.y:b.y + b.h, b.x:b.x + b.w] if g is not None else None
        crops.append(_hp(cv2.resize(c, (w0, h0))) if c is not None and c.size else None)
    ok = [i for i, c in enumerate(crops) if c is not None]
    if not ok:
        return cum[0], 0.0
    diem = {i: float(np.mean([float(cv2.matchTemplate(crops[i], crops[j], cv2.TM_CCOEFF_NORMED)[0, 0])
                              for j in ok if j != i] or [0.0])) for i in ok}
    i = max(diem, key=diem.get)
    return cum[i], diem[i]
