"""Bám lại watermark qua đoạn MẤT DẤU bằng hai bộ bám ngược chiều — chỉ nhận chỗ hai bộ bám GẶP NHAU.

Vì sao: logo bán trong suốt chạy qua nền sáng / rối thì điểm khớp từng khung chìm vào nhiễu (đo v04 14/10: logo k229 điểm 0,23 hạng
1 nhưng nhiễu 0,21; k794 0,175 ngoài top-6) ⇒ `theo_vet` mất dấu cả đoạn 90–150 khung, logo lộ. Không ngưỡng / khung nào tách được.
Logo Test3 chạy theo đường cong mượt rồi thỉnh thoảng nhảy chỗ (v04: đoạn 60–200 khung), nên ngoại suy vận tốc một chiều qua đoạn
dài sẽ trật, và bám một chiều với ngưỡng thấp sẽ bám rác (agy R2b: nền đứng yên ở chỗ cũ).

Cách làm: mỗi đoạn mất dấu kẹp giữa hai khung `detected` (dài `DOAN_TOI_THIEU`–`DOAN_TOI_DA` khung), chạy một bộ bám XUÔI từ đầu đoạn
và một bộ bám NGƯỢC từ cuối đoạn, mỗi bộ dò cục bộ quanh dự đoán (vị trí + vận tốc) trên ảnh thu nhỏ ½. Khung được nhận ⟺ hai bộ bám
cách nhau ≤ `GAP_PX` VÀ cả hai có điểm ≥ `DIEM_TOI_THIEU`, liền ≥ `CHUOI_TOI_THIEU` khung, điểm trung bình chuỗi ≥ `DIEM_TB_CHUOI`.
Nhiễu không làm hai bộ bám độc lập trùng một quỹ đạo; logo tắt / nhảy chỗ giữa đoạn ⇒ hai bộ bám không gặp ⇒ không nhận ⇒ không dán.
Khung nhận được là `detected` có cờ `quy_dao` và vẫn qua mọi cổng nội dung phía sau như khung dò thường.
"""
from __future__ import annotations

import cv2
import numpy as np

from .dinh_vi import SIGMA, _hp
from .nguon_khung import NguonKhung

DOAN_TOI_THIEU, DOAN_TOI_DA = 8, 300
CHUOI_TOI_THIEU = 8
DIEM_TOI_THIEU, DIEM_TB_CHUOI = 0.08, 0.14
VAN_TOC_KHUNG = 8  # số khung detected cuối/đầu đoạn kề dùng ước vận tốc ban đầu
GIA_TOC_PX = 4.0  # quỹ đạo logo mượt: vận tốc đổi ≤ chừng này px/khung giữa hai khung liền (rác bám nét chữ giật ±20–40 px)
LECH_PX, LECH_TI_LE = 6.0, 0.08  # hai bộ bám coi là gặp nhau khi tâm lệch ≤ max(6 px, 8% bề rộng box)


def _tam(e: dict) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def _van_toc(det: dict[int, dict], moc: int, huong: int) -> tuple[float, float]:
    """Vận tốc tâm (px/khung, ảnh gốc) từ các khung detected liền kề `moc` về phía ngược `huong` (huong=+1: lấy khung trước moc)."""
    ks = [k for k in range(moc, moc - huong * VAN_TOC_KHUNG - huong, -huong) if k in det]
    if len(ks) < 2:
        return 0.0, 0.0
    (x0, y0), (x1, y1) = _tam(det[ks[-1]]), _tam(det[ks[0]])
    return (x1 - x0) / (ks[0] - ks[-1]), (y1 - y0) / (ks[0] - ks[-1])


def _bam(nho: dict[int, np.ndarray], thu_tu: list[int], e0: dict, vx: float, vy: float, mau_u8: np.ndarray) -> dict[int, tuple]:
    """Một bộ bám trên ảnh ½: trả {khung: (x, y, điểm)} toạ độ ẢNH GỐC (góc trên trái box cỡ e0)."""
    w, h = max(4, e0["w"] // 2), max(4, e0["h"] // 2)
    t = _hp(cv2.resize(mau_u8, (w, h), interpolation=cv2.INTER_AREA), SIGMA / 2)
    if float(t.std()) < 1e-3:
        return {}
    x, y = e0["x"] / 2.0, e0["y"] / 2.0
    vx, vy = vx / 2.0, vy / 2.0
    r = int(0.5 * max(w, h)) + 6
    out = {}
    for k in thu_tu:
        g = nho[k]
        H, W = g.shape
        px, py = x + vx, y + vy
        x0, y0 = max(0, int(px) - r), max(0, int(py) - r)
        x1, y1 = min(W, int(px) + w + r), min(H, int(py) + h + r)
        if x1 - x0 < w or y1 - y0 < h:
            break
        _, s, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(g[y0:y1, x0:x1], t, cv2.TM_CCOEFF_NORMED))
        nx, ny = float(x0 + lx), float(y0 + ly)
        vx, vy = 0.7 * vx + 0.3 * (nx - x), 0.7 * vy + 0.3 * (ny - y)
        x, y = nx, ny
        out[k] = (int(round(2 * x)), int(round(2 * y)), float(s))
    return out


def _muot(duong: dict, k: int) -> bool:
    """Bộ bám đi MƯỢT tại khung k: có k−1, k−2 (theo chiều đi của nó) và vận tốc đổi ≤ GIA_TOC_PX."""
    for d in (+1, -1):
        if k - d in duong and k - 2 * d in duong:
            (x0, y0), (x1, y1), (x2, y2) = duong[k - 2 * d][:2], duong[k - d][:2], duong[k][:2]
            return float(np.hypot((x2 - x1) - (x1 - x0), (y2 - y1) - (y1 - y0))) <= GIA_TOC_PX
    return True


def _nhan(xuoi: dict, nguoc: dict, khung: list[int], w: int) -> list[int]:
    """Khung nhận: hai bộ bám gặp nhau, cả hai điểm ≥ DIEM_TOI_THIEU, cả hai đi mượt; giữ chuỗi liền ≥ CHUOI_TOI_THIEU."""
    lech_toi_da = max(LECH_PX, LECH_TI_LE * w)
    hop = [k for k in khung if k in xuoi and k in nguoc and min(xuoi[k][2], nguoc[k][2]) >= DIEM_TOI_THIEU
           and np.hypot(xuoi[k][0] - nguoc[k][0], xuoi[k][1] - nguoc[k][1]) <= lech_toi_da
           and _muot(xuoi, k) and _muot(nguoc, k)]
    nhan, cur = [], []
    for k in hop:
        if cur and k != cur[-1] + 1:
            nhan += cur if len(cur) >= CHUOI_TOI_THIEU else []
            cur = []
        cur.append(k)
    nhan += cur if len(cur) >= CHUOI_TOI_THIEU else []
    return nhan


def bam_lai_doan_mat(nguon: NguonKhung, det: dict[int, dict], mau: np.ndarray) -> tuple[dict[int, dict], dict]:
    """`det` (từ theo_vet) ⇒ (det có thêm khung `quy_dao`, số đếm). Một lượt đọc tuần tự; chỉ giữ ảnh ½ của đoạn đang xét."""
    dem = {"doan_xet": 0, "khung_nhan": 0}
    ds = sorted(det)
    doan = [(a, b) for a, b in zip(ds, ds[1:]) if DOAN_TOI_THIEU <= b - a - 1 <= DOAN_TOI_DA]
    if not doan:
        return det, dem
    mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
    out = dict(det)
    j, nho = 0, {}
    for i, g in enumerate(nguon.doc_tuan_tu()):
        if j >= len(doan):
            break
        a, b = doan[j]
        if a < i < b:
            H, W = g.shape
            nho[i] = _hp(cv2.resize(g, (W // 2, H // 2), interpolation=cv2.INTER_AREA), SIGMA / 2)
        if i == b:
            khung = list(range(a + 1, b))
            if len(nho) == len(khung):
                xuoi = _bam(nho, khung, det[a], *_van_toc(det, a, +1), mau_u8)
                nguoc = _bam(nho, khung[::-1], det[b], *(-v for v in _van_toc(det, b, -1)), mau_u8)
                w = det[a]["w"]
                chuoi = _nhan(xuoi, nguoc, khung, w)
                if chuoi:
                    diem = {k: (xuoi[k][2] + nguoc[k][2]) / 2 for k in chuoi}
                    if float(np.mean(list(diem.values()))) >= DIEM_TB_CHUOI:
                        for k in chuoi:
                            e0 = det[a] if k - a <= b - k else det[b]
                            out[k] = {"frame": k, "x": (xuoi[k][0] + nguoc[k][0]) // 2, "y": (xuoi[k][1] + nguoc[k][1]) // 2,
                                      "w": e0["w"], "h": e0["h"], "score": round(diem[k], 3), "state": "detected", "nhay": False,
                                      "quy_dao": True}
                        dem["khung_nhan"] += len(chuoi)
            dem["doan_xet"] += 1
            nho = {}
            j += 1
            while j < len(doan) and doan[j][1] <= i:
                j += 1
    return out, dem
