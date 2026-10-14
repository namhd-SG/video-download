"""Box mồi: đầu vào DUY NHẤT để lõi biết watermark trông ra sao (ĐP-1492).

Nguồn box là agy học mẫu (vài khung thưa mỗi video) HOẶC người tạo job kéo khung tay. Lõi không phân biệt nguồn khi dựng
mẫu; nguồn chỉ được ghi lại để báo cáo. Gom vết + chọn mồi đồng thuận chép từ `p1a_t2_pipeline_v2.py` (đã tune trên Test 02).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .nguon_khung import NguonKhung

# Gom vết theo SỐ CỤM agy (nếu có) + độ GIỐNG HÌNH (NCC thông cao giữa hai crop) + VỊ TRÍ. Không còn gom theo cỡ: box agy lúc rộng
# lúc hẹp ±35% nên cỡ vừa cắt đôi một watermark vừa dán hai thương hiệu khác nhau vào một cụm. Cụm 1–2 box vẫn là cụm
# hợp lệ (hạt giống): lõi dò mẫu trên các khung còn lại rồi mới quyết thành vết hay không.
NCC_KHONG_NHAN = 0.50    # thiếu số cụm ở một bên: phải giống hơn
NCC_KHAC_NHAN = 0.80     # số cụm khác nhau: chỉ nhập khi gần như y hệt VÀ nằm chồng nhau (agy gán một watermark hai số cụm)
IOU_CUNG_CHO = 0.30
CANH_SO_SANH = 64        # cạnh dài tối đa của crop khi so NCC


@dataclass(frozen=True)
class BoxMoi:
    khung: int  # chỉ số khung trong video
    x: int
    y: int
    w: int
    h: int
    nguon: str = "agy"  # "agy" | "tay"
    cum: int | None = None  # số nguyên cụm agy gán (cùng số trong cùng video ⇒ agy cho là cùng watermark); None = không có. Chỉ là GỢI Ý
    # gom (agy gán không ổn định giữa ảnh) — vẫn kết hợp hình + vị trí. Field CUỐI để giữ tương thích vị trí tham số.


def box_tu_box_2d(box_2d, khung: int, rong: int, cao: int, nguon: str = "agy", cum: int | None = None) -> BoxMoi | None:
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
                  max(4, int((x1 - x0) * rong // 1000)), max(4, int((y1 - y0) * cao // 1000)), nguon, cum)


def _iou(a: BoxMoi, b: BoxMoi) -> float:
    iw = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
    ih = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
    if iw <= 0 or ih <= 0:
        return 0.0
    return iw * ih / (a.w * a.h + b.w * b.h - iw * ih)


def _crop_thong_cao(nguon: NguonKhung, b: BoxMoi, bo_nho: dict) -> np.ndarray | None:
    if b.khung not in bo_nho:
        bo_nho[b.khung] = nguon.doc(b.khung)
    g = bo_nho[b.khung]
    c = g[max(0, b.y):b.y + b.h, max(0, b.x):b.x + b.w] if g is not None else None
    return c if c is not None and c.size else None


def _ncc_hai_box(nguon: NguonKhung, a: BoxMoi, b: BoxMoi, bo_nho: dict) -> float:
    """NCC thông cao giữa hai crop, đưa về cỡ của box lớn hơn (tối đa CANH_SO_SANH). Không đọc được crop ⇒ -1 (không nhập)."""
    ca, cb = _crop_thong_cao(nguon, a, bo_nho), _crop_thong_cao(nguon, b, bo_nho)
    if ca is None or cb is None:
        return -1.0
    lon = a if a.w * a.h >= b.w * b.h else b
    t = min(1.0, CANH_SO_SANH / max(lon.w, lon.h))
    kt = (max(4, round(lon.w * t)), max(4, round(lon.h * t)))
    return float(cv2.matchTemplate(_hp(cv2.resize(ca, kt, interpolation=cv2.INTER_AREA)),
                                   _hp(cv2.resize(cb, kt, interpolation=cv2.INTER_AREA)), cv2.TM_CCOEFF_NORMED)[0, 0])


def _cung_vet(a: BoxMoi, b: BoxMoi, ncc: float | None) -> bool:
    """Cùng số cụm agy ⇒ nhập NGAY, không đòi hình giống: NCC giữa hai crop của cùng một watermark trong suốt dao động −0,3…0,9 theo
    nền (đo 15 video) nên không phân định được; box nào vết sau đó không giải thích được sẽ được xử lý lại ở vòng hai (xem
    `duong_ong.xu_ly_video`). Số cụm khác nhau: chỉ nhập khi chồng vị trí VÀ hình gần y hệt. Thiếu số cụm: hình hoặc vị trí.
    `ncc` None (không có nguồn khung) hoặc -1 (không đọc được crop) = không có bằng chứng hình."""
    chong = _iou(a, b) >= IOU_CUNG_CHO
    co_hinh = ncc is not None and ncc > -0.999
    if a.cum is not None and b.cum is not None:
        return a.cum == b.cum or (chong and co_hinh and ncc >= NCC_KHAC_NHAN)
    return chong or (co_hinh and ncc >= NCC_KHONG_NHAN)


def gom_vet(boxes: list[BoxMoi], nguon: NguonKhung | None = None) -> list[list[BoxMoi]]:
    """Gom box thành cụm = một watermark: nhãn + hình + vị trí (union-find, mọi cặp). Trả MỌI cụm, kể cả cụm 1 box.
    `nguon=None` ⇒ không có hình để so: chỉ nhãn + chồng vị trí. Cụm sắp lớn trước, cùng cỡ thì theo khung đầu."""
    cha = list(range(len(boxes)))

    def goc(i):
        while cha[i] != i:
            cha[i] = cha[cha[i]]
            i = cha[i]
        return i

    bo_nho: dict = {}
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if goc(i) == goc(j):
                continue
            a, b = boxes[i], boxes[j]
            ncc = _ncc_hai_box(nguon, a, b, bo_nho) if nguon is not None else None
            if _cung_vet(a, b, ncc):
                cha[goc(i)] = goc(j)
    cum: dict[int, list[BoxMoi]] = {}
    for i, b in enumerate(boxes):
        cum.setdefault(goc(i), []).append(b)
    return sorted(cum.values(), key=lambda c: (-len(c), min(z.khung for z in c)))


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
