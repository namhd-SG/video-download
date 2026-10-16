"""LỘ TRÌNH: logo trôi theo một đường mượt trong từng đoạn ⇒ dựng đường đó từ các mốc tin được rồi dùng nó để (a) gỡ khung vết đang
bám chỗ giống logo nằm LỆCH đường, (b) đặt logo ở khung mất dấu / bị chữ-tay che mà vẫn nằm giữa hai phía có mốc.

Ý tưởng user 15/10 15:55 ("trong 1 đoạn logo sẽ đi theo 1 lộ trình nhất định … dự đoán hướng đi của logo để tracking"). Đo kq19:
- v05 k816–k846: AI chỉ chỗ logo ở k820/826/832/838 gần như thẳng hàng ((245,784)→(230,763), logo sau hộp phụ đề) nhưng điểm hình thấp
  nên lưới AI bỏ; lõi nội suy về chữ "learn?" (303,811) ⇒ lộ.
- test_2 k371–k403: logo thật trôi đều +5 px/khung (k355–k369), vết nhảy sang một chỗ ĐỨNG YÊN giống logo (266,276) 33 khung trong khi
  logo đi tiếp (k383 (258,329) đúng chỗ AI chỉ) rồi quay về ⇒ dán sai.

Cách làm: điểm mốc = khung dò đạt sàn hình (trọng số 1) + tâm box AI (trọng số `TRONG_SO_AI`, AI đã đo 55/55 đúng chỗ). Mỗi khung k: lấy
mốc trong ±`CUA_SO` khung, khớp bậc hai theo thời gian có trọng số, loại điểm lệch > `LECH_PX` rồi khớp lại (chống mồi đứng yên chen
giữa). Chỉ dùng dự đoán khi còn ≥ `MOC_TOI_THIEU` mốc VÀ có mốc ở CẢ HAI PHÍA trong ±`HAI_PHIA` khung (gần bước nhảy logo thật — đổi
cảnh — một phía là điểm lệch ⇒ không dự đoán, để nguyên).
Khung vết nằm lệch dự đoán > `LECH_PX` (bám chỗ khác) hoặc thiếu ⇒ dò cục bộ ±`DO_PX` quanh dự đoán trên thông cao đã xoá chữ: đủ điểm
⇒ đặt ở đỉnh dò; không đủ (bị che) ⇒ đặt đúng dự đoán. Khung đặt gắn `ai` + `quy_dao` + `lo_trinh` (miễn cổng như khung AI — user cho
đè chữ/vật).
Box AI thô qua `loc_moc_ai` trước khi làm mốc (box lưới AI đã bác vẫn vào lộ trình ⇒ dán sai v13/v01, đo 15/10); khung mà bộ lọc bác vì
det mạnh hơn (L5) thì det tại đúng khung đó cũng không làm mốc.
"""
from __future__ import annotations

import cv2
import numpy as np

from .box_moi import BoxMoi
from .chu_phu_de import thong_cao_xoa_chu
from .dinh_vi import SIGMA, _hp
from .kiem_hinh import san_hinh
from .loc_moc_ai import HAI_PHIA, LECH_PX, loc_moc_ai
from .nguon_khung import NguonKhung

TRONG_SO_AI = 3.0
CUA_SO = 15
MOC_TOI_THIEU = 4
DO_PX = 6
DIEM_DO = 0.20


def _khop(ts: np.ndarray, xs: np.ndarray, ws: np.ndarray, t: float) -> float:
    bac = 2 if len(set(ts.tolist())) >= 4 else 1
    p = np.polyfit(ts, xs, bac, w=np.sqrt(ws))
    return float(np.polyval(p, t))


def _du_doan(moc: dict[int, tuple[float, float, float]], k: int) -> tuple[float, float] | None:
    """Tâm dự đoán tại k từ mốc ±CUA_SO (khớp bậc hai có trọng số, bỏ điểm lệch rồi khớp lại); None nếu không đủ / không hai phía."""
    ks = [j for j in moc if abs(j - k) <= CUA_SO and j != k]
    for _ in range(3):
        if len(ks) < MOC_TOI_THIEU or not any(k - HAI_PHIA <= j < k for j in ks) or not any(k < j <= k + HAI_PHIA for j in ks):
            return None
        ts = np.array(ks, float)
        ws = np.array([moc[j][2] for j in ks])
        xs, ys = np.array([moc[j][0] for j in ks]), np.array([moc[j][1] for j in ks])
        px = [_khop(ts, xs, ws, j) for j in ks]
        py = [_khop(ts, ys, ws, j) for j in ks]
        lech = np.hypot(xs - np.array(px), ys - np.array(py))
        giu = [j for j, d in zip(ks, lech) if d <= LECH_PX]
        if len(giu) == len(ks):
            return _khop(ts, xs, ws, k), _khop(ts, ys, ws, k)
        ks = giu
    return None


def theo_lo_trinh(nguon: NguonKhung, det: dict[int, dict], mau: np.ndarray, neo_ai: list[BoxMoi], n: int, uv=None
                  ) -> tuple[dict[int, dict], dict]:
    """`det` ⇒ (det đã sửa theo lộ trình, số đếm). Không có mốc AI vẫn chạy (chỉ mốc dò đạt sàn). `uv` (ứng viên lõi theo khung) bật
    bộ lọc mốc AI thô; thiếu `uv` thì mọi box AI làm mốc như cũ."""
    dem = {"thay_lech": 0, "dat_moi": 0, "do_thay": 0}
    if len(det) < MOC_TOI_THIEU:
        return det, dem
    giu, bo_l5 = list(neo_ai), set()
    if neo_ai and uv is not None:
        giu, bo_l5, dem["loc"] = loc_moc_ai(nguon, det, mau, list(neo_ai), uv)
    san = san_hinh(list(det.values())) or 1.0
    w = int(np.median([e["w"] for e in det.values()]))
    h = int(np.median([e["h"] for e in det.values()]))
    moc: dict[int, tuple[float, float, float]] = {}
    for k, e in det.items():
        if (e.get("score") or 0) >= san and k not in bo_l5:
            moc[k] = (e["x"] + e["w"] / 2, e["y"] + e["h"] / 2, 1.0)
    for b in giu:
        moc[b.khung] = (b.x + b.w / 2, b.y + b.h / 2, TRONG_SO_AI)  # AI đè mốc dò cùng khung (dò có thể đang bám chỗ giống logo)
    if not moc:
        return det, dem
    can: dict[int, tuple[float, float]] = {}
    lo, hi = min(moc), max(moc)
    for k in range(lo, hi + 1):
        p = _du_doan(moc, k)
        if p is None:
            continue
        e = det.get(k)
        if e is None or np.hypot(e["x"] + e["w"] / 2 - p[0], e["y"] + e["h"] / 2 - p[1]) > LECH_PX:
            can[k] = p
    if not can:
        return det, dem
    out = dict(det)
    mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
    t = _hp(cv2.resize(mau_u8, (w, h), interpolation=cv2.INTER_LINEAR), SIGMA)
    cuoi = max(can)
    for i, g in enumerate(nguon.doc_tuan_tu()):
        p = can.get(i)
        if p is not None:
            H, W = g.shape
            x, y = int(round(p[0] - w / 2)), int(round(p[1] - h / 2))
            x0, y0, x1, y1 = max(0, x - DO_PX), max(0, y - DO_PX), min(W, x + w + DO_PX), min(H, y + h + DO_PX)
            diem = None
            if x1 - x0 >= w and y1 - y0 >= h and float(t.std()) > 1e-3:
                _, s, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(thong_cao_xoa_chu(g[y0:y1, x0:x1]), t, cv2.TM_CCOEFF_NORMED))
                if s >= DIEM_DO:
                    x, y, diem = x0 + lx, y0 + ly, round(float(s), 3)
                    dem["do_thay"] += 1
            dem["thay_lech" if i in det else "dat_moi"] += 1
            out[i] = {"frame": i, "x": x, "y": y, "w": w, "h": h, "score": diem, "state": "detected", "nhay": False,
                      "ai": True, "quy_dao": True, "lo_trinh": True}
        if i >= cuoi:
            break
    return out, dem
