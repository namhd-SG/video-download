"""Kiểm hình TRƯỚC KHI DÁN: chỗ sắp được che mà lõi chỉ ĐOÁN (khung lấp lỗ di chuyển, đoạn vết vừa nhảy sang chỗ khác) phải khớp hình
watermark tại đúng box — không khớp thì để nguyên (lộ), không dán.

Vì sao: lấp lỗ (`lam_muot_vet`) đoán vị trí khung không dò được bằng nội suy / giữ chỗ cũ qua bước nhảy mà không nhìn ảnh. Watermark
nhảy hoặc tắt/bật ⇒ khung lấp nằm chỗ KHÔNG có logo ⇒ dán logo mới lên nền trống, logo cũ vẫn lộ chỗ khác (test_2: 24/30 khung lấp
sai chỗ, có khung hiện cả hai logo). Luật: dán sai tệ hơn sót (ĐP 14/10) ⇒ nghi thì không dán.

Thang điểm = đúng thang `dinh_vi` (NCC thông cao σ=`SIGMA` giữa khung và mẫu đổi cỡ về box, dò ±`CUA_SO` px) để sàn tính từ khung
`detected` dùng được cho khung lấp. Sàn THEO VẾT = max(`SAN_TUYET_DOI`, trung vị − max(`K_MAD` × MAD, `BIEN_TOI_THIEU`)): logo mờ có
trung vị thấp, logo rõ có trung vị cao — hằng chung sẽ giết logo mờ hoặc thả logo rõ (đo Test3 14/10: trung vị 0,36–1,0); biên tối
thiểu cho vết điểm gần như hằng (icon sạch, MAD ≈ 0) kẻo sàn sát trung vị bác cả khung tốt.

Phạm vi — đo 14/10 trên mốc 9124eeb: áp sàn cho MỌI khung detected sẽ hạ 1096 khung v13, 335 khung v17, 68 khung v05 (video user đã
chấm ĐẠT; đa số là logo mờ thật trên nền rối — điểm thấp nhưng đúng chỗ). Vì vậy:
- khung detected: chỉ hạ đoạn điểm dưới sàn DÀI hơn `GO_NGAN_TOI_DA` VÀ bắt đầu bằng BƯỚC NHẢY (vết nhảy sang chỗ khác rồi bám đó:
  v10 k372–402 điểm 0,51–0,62, sàn 0,64); đoạn điểm thấp liền mạch giữ nguyên;
- khung lấp: chỉ kiểm đoạn ĐI NHANH — hai đầu (khung có toạ độ gần nhất) lệch > `LAP_TINH_PX` VÀ tốc độ > `LAP_CHAM_PX` px/khung.
  Đo: đoạn lấp sai ở test_2 chạy 4,6–27 px/khung; logo Learna trôi chậm ở v13 (~1 px/khung, lệch 16–25 px) lấp ĐÚNG.
- vết YẾU (trung vị điểm detected < `VET_MANH`: logo trong suốt) ⇒ không kiểm khung lấp: điểm từng khung không phân định — đo test_1
  (trung vị 0,36): khung lấp đúng `hinh` trung vị 0,13 trong khi khung lấp SAI của test_2 (vết mạnh) là 0,32.
"""
from __future__ import annotations

import cv2
import numpy as np

from .dinh_vi import CUA_SO, SIGMA, _hp
from .nguon_khung import NguonKhung

SAN_TUYET_DOI = 0.20
K_MAD = 2.5
BIEN_TOI_THIEU = 0.15
GO_NGAN_TOI_DA = 3  # đoạn detected hụt sàn ≤ 3 khung = logo nhoè thoáng qua ⇒ vẫn che (chống nháy)
LAP_TINH_PX = 12  # đoạn lấp có hai đầu lệch ≤ chừng này = logo đứng yên, nội suy đáng tin ⇒ không kiểm
LAP_CHAM_PX = 2.0  # … hoặc đi chậm ≤ chừng này px/khung (logo trôi chậm) ⇒ không kiểm
VET_MANH = 0.5  # trung vị điểm detected dưới mức này ⇒ vết yếu, không kiểm khung lấp
NHAY_PX_MOI_KHUNG = 25.0  # cùng ngưỡng TOC_DO_NHAY của lam_muot_vet: vượt ⇒ coi là bước nhảy
CHAN_HINH = "hidden_hinh"


def san_hinh(track: list[dict]) -> float | None:
    """Sàn điểm hình của một vết; None nếu vết không có khung detected nào có điểm."""
    d = np.array([e["score"] for e in track if e.get("state") == "detected" and e.get("score") is not None], dtype=np.float64)
    if not d.size:
        return None
    med = float(np.median(d))
    return max(SAN_TUYET_DOI, med - max(K_MAD * float(np.median(np.abs(d - med))), BIEN_TOI_THIEU))


def diem_tai(gf: np.ndarray, mau_u8: np.ndarray, x: int, y: int, w: int, h: int) -> tuple[float, int, int]:
    """(điểm, x, y) tốt nhất khi dò mẫu đổi cỡ (w, h) quanh (x, y) ±CUA_SO trên ảnh thông cao `gf`. Không dò được ⇒ (−1, x, y)."""
    H, W = gf.shape
    if w < 4 or h < 4:
        return -1.0, x, y
    t = _hp(cv2.resize(mau_u8, (w, h), interpolation=cv2.INTER_LINEAR), SIGMA)
    x0, y0, x1, y1 = max(0, x - CUA_SO), max(0, y - CUA_SO), min(W, x + w + CUA_SO), min(H, y + h + CUA_SO)
    if x1 - x0 < w or y1 - y0 < h or float(t.std()) < 1e-3:
        return -1.0, x, y
    _, s, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(gf[y0:y1, x0:x1], t, cv2.TM_CCOEFF_NORMED))
    return float(s), x0 + lx, y0 + ly


def _tam(e: dict) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def _doan(track: list[dict], dk) -> list[tuple[int, int]]:
    """Các đoạn [đầu, cuối) liên tiếp thoả `dk(e)`."""
    out, i, n = [], 0, len(track)
    while i < n:
        if not dk(track[i]):
            i += 1
            continue
        j = i
        while j < n and dk(track[j]):
            j += 1
        out.append((i, j))
        i = j
    return out


def _bat_dau_bang_nhay(track: list[dict], i: int) -> bool:
    """Khung i là bước nhảy: theo_vet gắn cờ, hoặc tâm cách khung có box gần nhất phía trước > NHAY_PX_MOI_KHUNG × số khung."""
    if track[i].get("nhay"):
        return True
    for k in range(i - 1, -1, -1):
        if "x" in track[k]:
            (ax, ay), (bx, by) = _tam(track[k]), _tam(track[i])
            return float(np.hypot(ax - bx, ay - by)) > NHAY_PX_MOI_KHUNG * (i - k)
    return False


def _vi_tri_ke(track: list[dict], san: float) -> tuple[list, list]:
    """Mỗi khung: vị trí (x, y, w, h) của khung detected ĐẠT sàn gần nhất phía trước / phía sau (None nếu không có)."""
    n = len(track)
    truoc, sau = [None] * n, [None] * n
    cur = None
    for i, e in enumerate(track):
        truoc[i] = cur
        if e.get("state") == "detected" and (e.get("score") or 0) >= san:
            cur = (e["x"], e["y"], e["w"], e["h"])
    cur = None
    for i in range(n - 1, -1, -1):
        e = track[i]
        sau[i] = cur
        if e.get("state") == "detected" and (e.get("score") or 0) >= san:
            cur = (e["x"], e["y"], e["w"], e["h"])
    return truoc, sau


def kiem_hinh_truoc_dan(nguon: NguonKhung, track: list[dict], mau: np.ndarray) -> dict:
    """Sửa `track` tại chỗ (gọi TRƯỚC các cổng nội dung). Trả số đếm cho nhật ký.
    - Đoạn detected dưới sàn, dài > GO_NGAN_TOI_DA VÀ bắt đầu bằng bước nhảy ⇒ `hidden_hinh`.
    - Đoạn lấp có hai đầu lệch > LAP_TINH_PX ⇒ chấm điểm từng khung ở chỗ đang đoán VÀ ở chỗ của khung detected đạt sàn gần nhất
      trước/sau (lỗ qua bước nhảy: logo hoặc còn ở chỗ cũ, hoặc đã sang chỗ mới); đạt sàn thì dời box về chỗ đạt, không ⇒ `hidden_hinh`."""
    san = san_hinh(track)
    dem = {"san": None if san is None else round(san, 3), "detected_hut": 0, "filled_tinh": 0, "filled_giu": 0, "filled_doi_cho": 0,
           "filled_bo": 0}
    if san is None:
        return dem
    for i, j in _doan(track, lambda e: e.get("state") == "detected" and e.get("score") is not None and e["score"] < san):
        if j - i > GO_NGAN_TOI_DA and _bat_dau_bang_nhay(track, i):
            for e in track[i:j]:
                e["state"], e["hinh_hut"] = CHAN_HINH, round(float(e["score"]), 3)
            dem["detected_hut"] += j - i
    lap: dict[int, dict] = {}
    d = [e["score"] for e in track if e.get("state") == "detected" and e.get("score") is not None]
    vet_manh = bool(d) and float(np.median(d)) >= VET_MANH
    for i, j in _doan(track, lambda e: e.get("state") == "filled"):
        a = next((k for k in range(i - 1, -1, -1) if "x" in track[k]), None)
        b = next((k for k in range(j, len(track)) if "x" in track[k]), None)
        if a is not None and b is not None:
            lech = float(np.hypot(*np.subtract(_tam(track[a]), _tam(track[b]))))
            if lech <= LAP_TINH_PX or lech / (b - a) <= LAP_CHAM_PX:
                dem["filled_tinh"] += j - i
                continue
        if not vet_manh:
            dem["filled_vet_yeu"] = dem.get("filled_vet_yeu", 0) + j - i
            continue
        lap.update({k: track[k] for k in range(i, j)})
    if not lap:
        return dem
    truoc, sau = _vi_tri_ke(track, san)
    mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
    cuoi = max(lap)
    for i, g in enumerate(nguon.doc_tuan_tu()):
        e = lap.get(i)
        if e is not None:
            gf = _hp(g, SIGMA)
            cho = [(e["x"], e["y"], e["w"], e["h"])] + [p for p in (truoc[i], sau[i]) if p is not None]
            tot = max((diem_tai(gf, mau_u8, *p) + (p[2], p[3]) for p in cho), key=lambda r: r[0])
            e["hinh"] = round(tot[0], 3)
            if tot[0] < san:
                e["state"] = CHAN_HINH
                dem["filled_bo"] += 1
            elif (tot[1], tot[2], tot[3], tot[4]) != (e["x"], e["y"], e["w"], e["h"]):
                e.update(x=int(tot[1]), y=int(tot[2]), w=int(tot[3]), h=int(tot[4]))
                dem["filled_doi_cho"] += 1
            else:
                dem["filled_giu"] += 1
        if i >= cuoi:
            break
    return dem
