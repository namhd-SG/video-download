"""Định vị C nhanh: dò mẫu sạch mỗi khung (thô ½ + tinh tỉ lệ 0,01) rồi Viterbi nối vết qua thời gian.

Chép từ `p0b_c_locate_fast.py` với hai cờ đã bật cố định như lượt Test 02 v2: LỌC ứng viên nằm trên phụ đề và BIÊN CỤC BỘ
(chỉ so với ứng viên gần ≤2 cạnh box — hai bản watermark giống hệt ở xa không bị coi là mơ hồ).
Đầu ra: mỗi khung một dict `{"frame", "state", [x, y, w, h, score]}`; state ∈ detected | predicted | hidden.
CHỈ `detected` (biên ≥0,2) mới có thể được render — `predicted` là khung Viterbi nối qua, không đủ chắc.
"""
from __future__ import annotations

import cv2
import numpy as np

from .nguon_khung import NguonKhung

K, TAU, VMAX, JUMP, SWITCH = 6, 0.33, 8.0, 0.5, 0.6
SIGMA = 2.0
TI_LE_THO = (0.95, 1.05, 1.15)
TINH_KHOANG, TINH_BUOC, CUA_SO = 0.05, 0.01, 6
BIEN_CHAC = 0.2
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


def _ung_vien_khung(g, tho, tinh, ti_le_tinh):
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
    uv = [c for c in uv if ti_le_phu_de(g, c[0], c[1], c[3], c[4], 2) <= NGUONG_PHU_DE_UNG_VIEN]
    uv.sort(key=lambda c: -c[2])
    while len(uv) < K:
        uv.append(uv[-1][:2] + (-1.0,) + uv[-1][3:] if uv else (0, 0, -1.0, 1, 1))
    return uv[:K]


def _viterbi(cands: list[list[tuple]]) -> list[int]:
    """Đường trạng thái tốt nhất; trạng thái K = 'ẩn'. Chép nguyên từ bench."""
    score = np.array([[c[2] for c in cands[0]] + [TAU]])
    back = []
    for i in range(1, len(cands)):
        prev, cur = cands[i - 1], cands[i]
        trans = np.zeros((K + 1, K + 1))
        for a in range(K):
            for b in range(K):
                d = np.hypot(cur[b][0] - prev[a][0], cur[b][1] - prev[a][1])
                trans[a, b] = 0.0 if d <= VMAX else -JUMP
        trans[:K, K] = trans[K, :K] = -SWITCH
        tot = score[-1][:, None] + trans
        back.append(tot.argmax(0))
        emit = np.array([c[2] for c in cur] + [TAU])
        score = np.vstack([score, tot.max(0) + emit])
    st = int(score[-1].argmax())
    path = [st]
    for b in reversed(back):
        st = int(b[st])
        path.append(st)
    path.reverse()
    return path


def dinh_vi(nguon: NguonKhung, mau: np.ndarray) -> list[dict]:
    """Track mỗi khung cho một mẫu (ảnh xám). Video rỗng ⇒ []."""
    med = np.clip(mau, 0, 255).astype(np.uint8)
    half = cv2.resize(med, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    tho = [(s, _hp(cv2.resize(half, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR), SIGMA / 2)) for s in TI_LE_THO]
    ti_le_tinh = np.round(np.arange(0.90, 1.2001, TINH_BUOC), 2)
    tinh = {float(s): _hp(cv2.resize(med, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR), SIGMA) for s in ti_le_tinh}
    cands = [_ung_vien_khung(g, tho, tinh, ti_le_tinh) for g in nguon.doc_tuan_tu()]
    if not cands:
        return []
    track = []
    for i, s in enumerate(_viterbi(cands)):
        e: dict = {"frame": i}
        if s < K:
            x, y, sc, cw, ch = cands[i][s]
            gan = [c[2] for j, c in enumerate(cands[i]) if j != s and abs(c[0] - x) <= 2 * cw and abs(c[1] - y) <= 2 * ch]
            bien = sc - (max(gan) if gan else -1.0)
            e.update(x=int(x), y=int(y), w=int(cw), h=int(ch), score=round(float(sc), 3),
                     state="detected" if bien >= BIEN_CHAC else "predicted")
        else:
            e["state"] = "hidden"
        track.append(e)
    return track
