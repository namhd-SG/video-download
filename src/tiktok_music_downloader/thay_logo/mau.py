"""Mẫu sạch của watermark: dựng từ box mồi, rồi tự học từ chính các khung chắc của video.

Chép từ `p0b_build_clean_template.py` (căn lặp + trung vị nửa crop khớp tốt nhất) và `p0b_self_train_template.py`.
Sửa theo plan §5c.1 (kongming): crop tự học CHỈ lấy khung đã qua mọi cổng; mẫu mới lệch xa mẫu cũ ⇒ giữ mẫu cũ + gắn cờ.
"""
from __future__ import annotations

import cv2
import numpy as np

from .box_moi import BoxMoi
from .nguon_khung import NguonKhung

BAN_KINH_CAN = 24  # px quanh box mồi khi căn lại vị trí (box agy 360px làm tròn lệch ~±6px full-res, để dư)
SO_VONG_CAN = 4
TU_HOC_TOI_DA = 120
NCC_TU_HOC_TOI_THIEU = 0.7  # ngưỡng ĐỀ XUẤT (plan §5c.1), chưa hiệu chỉnh; sai hướng chỉ làm giữ mẫu cũ ⇒ ít khung hơn


def _hp(g: np.ndarray, s: float) -> np.ndarray:
    g = g.astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), s)


def no_box_moi(b: BoxMoi) -> tuple[int, int, int, int]:
    """Nới box mồi 10% (box agy hay cắt hụt chữ — c09 hospital: 709 ⇒ 799 khung chắc khi nới)."""
    return max(0, b.x - b.w // 20), max(0, b.y - b.h // 20), b.w * 11 // 10, b.h * 11 // 10


def dung_mau_sach(nguon: NguonKhung, moi: BoxMoi, cum: list[BoxMoi]) -> np.ndarray | None:
    """Trung vị các crop đã căn quanh từng box của cụm ⇒ nền triệt tiêu, còn watermark. Trả ảnh xám float32 hoặc None."""
    g0 = nguon.doc(moi.khung)
    if g0 is None:
        return None
    x, y, w, h = no_box_moi(moi)
    seed = g0[y:y + h, x:x + w]
    if seed.shape != (h, w):
        return None
    tmpl = _hp(seed, 4)
    rois = []
    for b in cum:
        g = nguon.doc(b.khung)
        if g is None:
            continue
        H, W = g.shape
        x0, y0 = max(0, b.x - BAN_KINH_CAN), max(0, b.y - BAN_KINH_CAN)
        sub = g[y0:min(H, b.y + h + BAN_KINH_CAN), x0:min(W, b.x + w + BAN_KINH_CAN)]
        if sub.shape[0] >= h and sub.shape[1] >= w:
            rois.append((sub, _hp(sub, 4)))
    if not rois:
        return None
    med = seed.astype(np.float32)
    for _ in range(SO_VONG_CAN):
        crops, diem = [], []
        for sub, sub_hp in rois:
            _, s, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(sub_hp, tmpl, cv2.TM_CCOEFF_NORMED))
            crops.append(sub[ly:ly + h, lx:lx + w].astype(np.float32))
            diem.append(s)
        # Chỉ nửa crop khớp tốt nhất vào trung vị: crop lệch làm nhoè mẫu, mẫu nhoè lại làm căn lệch.
        giu = np.argsort(diem)[len(diem) // 2:]
        med = np.median(np.stack([crops[i] for i in giu]), axis=0)
        tmpl = _hp(med, 4)
    return med


def tu_hoc_mau(nguon: NguonKhung, track: list[dict], mau_cu: np.ndarray) -> tuple[np.ndarray, bool]:
    """Mẫu vòng sau = trung vị ≤120 crop trải đều trên khung `detected` (đã qua cổng), đưa về cỡ mẫu cũ.

    Trả (mẫu, đã_nhận). Không đủ crop hoặc NCC(mẫu cũ, mẫu mới) < ngưỡng ⇒ (mẫu cũ, False): mẫu trôi sang nội dung là
    lỗ phá nội dung mà mọi cổng phía sau đều không thấy (mẫu sai tự nhất quán)."""
    th, tw = mau_cu.shape
    chac = [e for e in track if e.get("state") == "detected"]
    chon = chac[:: max(1, len(chac) // TU_HOC_TOI_DA)][:TU_HOC_TOI_DA]
    crops = []
    can = {e["frame"]: e for e in chon}
    # Một lượt đọc tuần tự thay vì mở + seek từng khung: seek giải mã lại từ keyframe, đo 09/10 ~3,5 phút/video 17s.
    for i, g in enumerate(nguon.doc_tuan_tu() if can else ()):
        e = can.get(i)
        if e is not None:
            c = g[e["y"]:e["y"] + e["h"], e["x"]:e["x"] + e["w"]]
            if c.size:
                crops.append(cv2.resize(c, (tw, th), interpolation=cv2.INTER_AREA).astype(np.float32))
        if i >= max(can):
            break
    if len(crops) < 3:
        return mau_cu, False
    moi = np.median(np.stack(crops), axis=0)
    ncc = float(cv2.matchTemplate(_hp(moi, 2), _hp(mau_cu, 2), cv2.TM_CCOEFF_NORMED)[0, 0])
    return (moi, True) if ncc >= NCC_TU_HOC_TOI_THIEU else (mau_cu, False)


def mat_na_va_tuong_phan(mau: np.ndarray) -> tuple[np.ndarray, float]:
    """Mặt nạ nét watermark (lệch trung vị viền mẫu > 10) và tương phản nét–nền của chính mẫu."""
    t = mau.astype(np.float32)
    vien = np.concatenate([t[:2].ravel(), t[-2:].ravel(), t[:, :2].ravel(), t[:, -2:].ravel()])
    mask = (np.abs(t - np.median(vien)) > 10).astype(np.uint8)
    if mask.sum() and (mask == 0).sum():
        return mask, float(abs(t[mask > 0].mean() - t[mask == 0].mean()))
    return mask, 0.0
