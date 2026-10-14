"""Từ các khung detected rời rạc ⇒ vết liền mạch: lấp lỗ, nới hai đầu, làm mượt vị trí + cỡ.

- Hai khung detected cách ≤ `LO_TOI_DA` khung thuộc cùng MỘT ĐOẠN SỐNG; xa hơn ⇒ đoạn sống mới (không lấp: logo thật sự vắng).
- Lỗ giữa hai khung detected: tốc độ ngầm ≤ `TOC_DO_NHAY` px/khung ⇒ nội suy tuyến tính; vượt ⇒ BƯỚC NHẢY: giữ vị trí cũ nửa đầu lỗ,
  vị trí mới nửa sau, và làm mượt KHÔNG đi xuyên bước nhảy (tách đoạn mượt).
- Nới `NOI_HAI_DAU` khung giữ nguyên vị trí ở hai đầu mỗi đoạn sống (logo hiện/ẩn mờ dần mà ứng viên chưa đạt ngưỡng).
- Làm mượt = hồi quy tuyến tính cục bộ trọng số Gauss (σ = `SIGMA_MUOT` khung) trên từng đoạn mượt: tương đương Kalman+RTS mô hình
  vận tốc đều nhưng vector hoá, không lệch ở hai đầu đoạn, không kéo logo đứng yên đi lệch.
"""
from __future__ import annotations

import numpy as np

LO_TOI_DA = 60
NOI_HAI_DAU = 3
TOC_DO_NHAY = 25.0
SIGMA_MUOT = 3.0


def _hoi_quy_cuc_bo(z: np.ndarray, sigma: float = SIGMA_MUOT) -> np.ndarray:
    """Làm mượt chuỗi `z` (không còn nan) bằng hồi quy tuyến tính cục bộ Gauss; hai đầu chuỗi cắt nhân (không đệm)."""
    n = len(z)
    if n < 3:
        return z.copy()
    r = int(np.ceil(3 * sigma))
    u = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-0.5 * (u / sigma) ** 2)
    m = np.ones(n)
    cv = lambda x, h: np.convolve(x, h)[r:r + n]  # noqa: E731  — "full" rồi cắt: "same" trả độ dài kernel khi chuỗi ngắn hơn kernel
    h1, h2 = k * (-u), k * u * u  # d = j − t = −(t − j)
    s0, s1, s2, t0, t1 = cv(m, k), cv(m, h1), cv(m, h2), cv(z, k), cv(z, h1)
    den = s0 * s2 - s1 * s1
    ok = den > 1e-9 * np.maximum(s0 * s2, 1e-12)
    return np.where(ok, (t0 * s2 - t1 * s1) / np.where(ok, den, 1.0), t0 / np.maximum(s0, 1e-12))


def _doan_song(khung: list[int]) -> list[list[int]]:
    chuoi = [[khung[0]]]
    for t in khung[1:]:
        if t - chuoi[-1][-1] > LO_TOI_DA:
            chuoi.append([t])
        else:
            chuoi[-1].append(t)
    return chuoi


def _dung_doan(det: dict[int, dict], ch: list[int], n: int):
    """Một đoạn sống ⇒ (khung đầu, mảng cx, cy, w, h đã điền, id đoạn mượt theo khung)."""
    a, b = max(0, ch[0] - NOI_HAI_DAU), min(n - 1, ch[-1] + NOI_HAI_DAU)
    L = b - a + 1
    v = np.full((4, L), np.nan)
    seg = np.zeros(L, int)

    def dat(t, e):
        v[:, t - a] = (e["x"] + e["w"] / 2, e["y"] + e["h"] / 2, e["w"], e["h"])

    for t in ch:
        dat(t, det[t])
    for t in range(a, ch[0]):
        v[:, t - a] = v[:, ch[0] - a]
    for t in range(ch[-1] + 1, b + 1):
        v[:, t - a] = v[:, ch[-1] - a]
    sid = 0
    for p, t in zip(ch, ch[1:]):
        dt = t - p
        toc = float(np.hypot(*(v[:2, t - a] - v[:2, p - a]))) / dt
        if toc > TOC_DO_NHAY:
            giua = p + (dt + 1) // 2  # nửa đầu giữ vị trí cũ, từ `giua` giữ vị trí mới
            for k in range(p + 1, t):
                v[:, k - a] = v[:, p - a] if k < giua else v[:, t - a]
            sid += 1
            seg[giua - a:] = sid
    # lỗ còn lại (tốc độ êm) ⇒ nội suy tuyến tính theo từng hàng
    for r in range(4):
        co = ~np.isnan(v[r])
        v[r] = np.interp(np.arange(L), np.flatnonzero(co), v[r][co])
    return a, v, seg


def lap_va_lam_muot(det: dict[int, dict], n: int) -> tuple[dict[int, dict], list[tuple[int, int]]]:
    """`det` {khung: entry detected thô} ⇒ ({khung: entry detected|filled đã mượt}, [(khung đầu, khung cuối) mỗi đoạn sống]).
    Entry giữ nguyên trường của khung detected gốc (score…), thêm `x0`,`y0` = vị trí thô; khung lấp có `state='filled'`."""
    if not det:
        return {}, []
    out: dict[int, dict] = {}
    doan = []
    for ch in _doan_song(sorted(det)):
        a, v, seg = _dung_doan(det, ch, n)
        for s in np.unique(seg):
            idx = np.flatnonzero(seg == s)
            cx, cy, w, h = (_hoi_quy_cuc_bo(v[r, idx]) for r in range(4))
            for j, i in enumerate(idx):
                t = a + int(i)
                ww, hh = max(4, int(round(w[j]))), max(4, int(round(h[j])))
                goc = det.get(t)
                e = dict(goc) if goc is not None else {"frame": t, "score": None, "nhay": False}
                e.update(frame=t, x=int(round(cx[j] - ww / 2)), y=int(round(cy[j] - hh / 2)), w=ww, h=hh,
                         state="detected" if goc is not None else "filled")
                if goc is not None:
                    e["x0"], e["y0"] = goc["x"], goc["y"]
                out[t] = e
        doan.append((a, a + len(v[0]) - 1))
    return out, doan
