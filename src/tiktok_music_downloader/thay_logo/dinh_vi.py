"""Ứng viên mỗi khung cho một mẫu sạch: dò mẫu TOÀN KHUNG (thô ½ + tinh tỉ lệ 0,01) lấy top-K đỉnh, thêm dò CỤC BỘ quanh các
vị trí neo (box mồi). Không còn Viterbi / trần vận tốc: việc nối ứng viên qua thời gian là của `theo_vet`.

Giữ hai cờ đã bật cố định từ lượt Test 02 v2: LỌC ứng viên nằm trên phụ đề (chữ trắng viền đen) và đo điểm trên ảnh THÔNG CAO.
Đầu ra: danh sách theo khung, mỗi phần tử `(ung_vien, loc_pd)`; ung_vien = [(x, y, điểm NCC, w, h)] điểm giảm dần (chỉ ứng viên thật,
không độn), loc_pd = số ứng viên bị bộ lọc phụ đề loại ở khung đó. Bộ nhớ: vài chục số mỗi khung, KHÔNG giữ ảnh.
"""
from __future__ import annotations

import cv2
import numpy as np

from .nguon_khung import NguonKhung

K = 6
SIGMA = 2.0
TI_LE_THO = (0.95, 1.05, 1.15)
TINH_KHOANG, TINH_BUOC, CUA_SO = 0.05, 0.01, 6
CUA_SO_NEO = 0.6  # dò cục bộ quanh neo: ±(0,6 × cạnh dài + 10) px
NGUONG_PHU_DE_UNG_VIEN = 0.03  # 137/137 ứng viên bị bỏ ở R9b đều là "Learna AI" trong phụ đề


def ti_le_phu_de(g: np.ndarray, x: int, y: int, w: int, h: int, pad: int) -> float:
    """Tỉ lệ điểm ảnh 'chữ phụ đề' (rất sáng >215 sát rất tối <45) trong box nới `pad` — kiểu chữ trắng viền đen."""
    H, W = g.shape
    r = g[max(0, y - pad):min(H, y + h + pad), max(0, x - pad):min(W, x + w + pad)]
    if r.size == 0:
        return 0.0
    toi = cv2.dilate((r < 45).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return float(((r > 215) & toi).mean())


def _hp(g: np.ndarray, s: float) -> np.ndarray:
    g = g.astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), s)


def _dinh_nms(m: np.ndarray, k: int, h: int, w: int) -> list[tuple[int, int, float]]:
    out, m = [], m.copy()
    for _ in range(k):
        _, s, _, (x, y) = cv2.minMaxLoc(m)
        out.append((x, y, s))
        cv2.rectangle(m, (x - w // 2, y - h // 2), (x + w // 2, y + h // 2), -1, -1)
    return out


def _ung_vien_khung(g, tho, tinh, ti_le_tinh, loc_phu_de=True):
    """K ứng viên (x, y, điểm, w, h) của một khung, điểm giảm dần; thiếu thì độn ứng viên điểm −1."""
    H, W = g.shape
    gh = _hp(cv2.resize(g, (W // 2, H // 2), interpolation=cv2.INTER_AREA), SIGMA / 2)
    raw = []
    for s, t in tho:
        if gh.shape[0] < t.shape[0] or gh.shape[1] < t.shape[1]:
            continue
        for x, y, sc in _dinh_nms(cv2.matchTemplate(gh, t, cv2.TM_CCOEFF_NORMED), K, *t.shape):
            raw.append((sc, x * 2, y * 2, s))
    raw.sort(key=lambda r: -r[0])
    chon = []
    for r in raw:  # NMS giữa các tỉ lệ ở mức thô
        if all(abs(r[1] - p[1]) > 40 or abs(r[2] - p[2]) > 20 for p in chon):
            chon.append(r)
        if len(chon) == K:
            break
    gf = _hp(g, SIGMA)
    uv = []
    for _, cx, cy, s0 in chon:
        best = None
        for s in ti_le_tinh[(ti_le_tinh >= s0 - TINH_KHOANG - 1e-6) & (ti_le_tinh <= s0 + TINH_KHOANG + 1e-6)]:
            t = tinh[float(s)]
            th, tw = t.shape
            x0, y0 = max(0, cx - CUA_SO), max(0, cy - CUA_SO)
            x1, y1 = min(W, cx + tw + CUA_SO), min(H, cy + th + CUA_SO)
            if x1 - x0 < tw or y1 - y0 < th:
                continue
            _, sc, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(gf[y0:y1, x0:x1], t, cv2.TM_CCOEFF_NORMED))
            if best is None or sc > best[2]:
                best = (x0 + lx, y0 + ly, sc, tw, th)
        if best:
            uv.append(best)
    truoc_loc = len(uv)
    if loc_phu_de:
        uv = [c for c in uv if ti_le_phu_de(g, c[0], c[1], c[3], c[4], 2) <= NGUONG_PHU_DE_UNG_VIEN]
    bi_loc = truoc_loc - len(uv)
    uv.sort(key=lambda c: -c[2])
    return uv[:K], bi_loc


def _ung_vien_neo(g, gf, tinh, neo, uv, loc_phu_de=True, khung=0):
    """Thêm ứng viên dò cục bộ quanh mỗi neo (x, y, w, h) bằng mẫu tỉ lệ 1,0 — bắt logo yếu mà top-K toàn khung bỏ lọt.
    Ứng viên trùng vị trí (≤ 0,3 cạnh) với ứng viên có sẵn thì giữ cái điểm cao hơn."""
    H, W = g.shape
    t = tinh[1.0]
    th, tw = t.shape
    for nx, ny, nw, nh, f0, f1 in neo:
        if not f0 <= khung <= f1:
            continue
        r = int(CUA_SO_NEO * max(nw, nh)) + 10
        x0, y0, x1, y1 = max(0, nx - r), max(0, ny - r), min(W, nx + tw + r), min(H, ny + th + r)
        if x1 - x0 < tw or y1 - y0 < th:
            continue
        _, sc, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(gf[y0:y1, x0:x1], t, cv2.TM_CCOEFF_NORMED))
        c = (x0 + lx, y0 + ly, float(sc), tw, th)
        if loc_phu_de and ti_le_phu_de(g, c[0], c[1], tw, th, 2) > NGUONG_PHU_DE_UNG_VIEN:
            continue
        gan = [k for k, u in enumerate(uv) if abs(u[0] - c[0]) <= 0.3 * tw and abs(u[1] - c[1]) <= 0.3 * th]
        if not gan:
            uv.append(c)
        elif uv[gan[0]][2] < c[2]:
            uv[gan[0]] = c
    uv.sort(key=lambda c: -c[2])


def dinh_vi(nguon: NguonKhung, mau: np.ndarray, neo: list[tuple[int, int, int, int, int, int]] = (),
            buoc: int = 1, loc_phu_de: bool = True) -> list[tuple[list[tuple], int]]:
    """Ứng viên mỗi khung cho một mẫu (ảnh xám). `neo` = (x, y, w, h, khung đầu, khung cuối): dò cục bộ thêm quanh vị trí đó khi khung nằm trong đoạn. Video rỗng ⇒ [].
    `loc_phu_de=False` ⇒ không loại ứng viên giống phụ đề (mẫu chính nó đã giống phụ đề: chữ trắng viền đen).
    `buoc` > 1 ⇒ chỉ dò khung 0, buoc, 2·buoc… (phần tử i ứng khung i·buoc): lượt tự học mẫu chỉ cần mẫu thưa, rẻ gấp `buoc` lần."""
    med = np.clip(mau, 0, 255).astype(np.uint8)
    half = cv2.resize(med, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    tho = [(s, _hp(cv2.resize(half, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR), SIGMA / 2)) for s in TI_LE_THO]
    ti_le_tinh = np.round(np.arange(0.90, 1.2001, TINH_BUOC), 2)
    tinh = {float(s): _hp(cv2.resize(med, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR), SIGMA) for s in ti_le_tinh}
    out = []
    for i, g in enumerate(nguon.doc_tuan_tu()):
        if i % buoc:
            continue
        uv, bi_loc = _ung_vien_khung(g, tho, tinh, ti_le_tinh, loc_phu_de)
        if neo:
            _ung_vien_neo(g, _hp(g, SIGMA), tinh, neo, uv, loc_phu_de, i)
        out.append((uv, bi_loc))
    return out
