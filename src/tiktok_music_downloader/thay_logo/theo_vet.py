"""Nối ứng viên qua thời gian thành một vết: lượt XUÔI + lượt NGƯỢC trên CÙNG bộ ứng viên đã cache (không giữ khung ảnh).

Thay Viterbi trần vận tốc 8 px. Mỗi lượt có một trạng thái (vị trí + vận tốc ước lượng):
- ứng viên GẦN vị trí dự đoán (bán kính theo cỡ logo + số khung đã mất) và điểm ≥ `lo` ⇒ nhận, ưu tiên điểm cao + gần;
- không có thì ứng viên BẤT KỲ chỗ nào điểm ≥ `hi` ⇒ nhận như một BƯỚC NHẢY (logo nhảy góc), vận tốc về 0 — bước nhảy lớn chỉ
  được nhận khi ứng viên đủ mạnh;
- không có cả hai ⇒ trượt khung (lấp lỗ lo sau), mất quá `TRUOT_TOI_DA` khung liền ⇒ trạng thái "lạc", chỉ nhận lại khi ≥ `hi`.
Ngưỡng `hi`/`lo` TƯƠNG ĐỐI theo video: dựng từ phân bố điểm các ứng viên hạng ≥ 2 (nền nhiễu của chính video), không phải 0,75 cố định.
Hai lượt hợp lại theo từng khung (điểm cao thắng khi bất đồng); đoạn ngắn không có mồi chống lưng bị bỏ (ứng viên lẻ).
"""
from __future__ import annotations

import numpy as np

HI_SAN, HI_TRAN, LO_SAN = 0.30, 0.65, 0.20
HI_BU, LO_BU = 0.05, 0.02   # cộng thêm vào phân vị 95 / 90 của điểm nền nhiễu
TRUOT_TOI_DA = 30
DOAN_TOI_THIEU = 4          # đoạn detected liên tục (cho phép hở ≤ 2 khung) ngắn hơn thì bỏ, trừ khi có khung mồi
HO_TOI_DA = 2
BAN_KINH_CO = 0.35          # bán kính dự đoán = 0,35 × cạnh dài + 8 + 5 × số khung đã mất, trần 2 × cạnh dài
PHAT_KHOANG_CACH = 0.15     # trừ điểm theo khoảng cách tới dự đoán khi chọn giữa các ứng viên gần
TI_LE_DIEM_TOI_THIEU = 0.5  # vết đang chắc (điểm trung bình động E) chỉ nhận ứng viên ≥ 0,5 × E: ứng viên rác điểm thấp không cướp vết
HE_SO_DIEM = 0.3            # hệ số trung bình động của điểm vết


def nguong_tuong_doi(uv: list[list[tuple]]) -> tuple[float, float, float]:
    """(hi, lo, phân vị 95 của nền nhiễu) theo video. Nền nhiễu = điểm các ứng viên hạng ≥ 2 mỗi khung (hạng 1 có thể là chính logo)."""
    nen = [c[2] for cs in uv for c in cs[1:]]
    if len(nen) < 20:
        return HI_SAN, LO_SAN, 0.0
    q95, q90 = np.percentile(nen, 95), np.percentile(nen, 90)
    hi = float(min(HI_TRAN, max(HI_SAN, q95 + HI_BU)))
    lo = float(min(hi - 0.08, max(LO_SAN, q90 + LO_BU)))
    return hi, lo, float(q95)


def _mot_luot(uv: list[list[tuple]], thu_tu, hi: float, lo: float, kich: tuple[int, int]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    cur = None
    vx = vy = 0.0
    mat = 1
    diem_tb = 0.0
    w, h = kich
    for t in thu_tu:
        cs = uv[t]
        chon, nhay = None, False
        lo_t, hi_t = max(lo, TI_LE_DIEM_TOI_THIEU * diem_tb), max(hi, 0.6 * diem_tb)
        if cur is not None:
            px, py = cur[0] + vx * mat, cur[1] + vy * mat
            r = min(2.0 * max(w, h), BAN_KINH_CO * max(w, h) + 8 + 5 * mat)
            gan = [(c[2] - PHAT_KHOANG_CACH * np.hypot(c[0] - px, c[1] - py) / r, c) for c in cs
                   if c[2] >= lo_t and np.hypot(c[0] - px, c[1] - py) <= r]
            if gan:
                chon = max(gan, key=lambda z: z[0])[1]
        if chon is None:
            xa = [c for c in cs if c[2] >= hi_t]
            if xa:
                chon, nhay = max(xa, key=lambda c: c[2]), cur is not None
        if chon is None:
            mat += 1
            if mat > TRUOT_TOI_DA:
                cur, vx, vy, diem_tb = None, 0.0, 0.0, 0.0
            continue
        if cur is not None and not nhay:
            vx, vy = 0.7 * vx + 0.3 * (chon[0] - cur[0]) / mat, 0.7 * vy + 0.3 * (chon[1] - cur[1]) / mat
        else:
            vx = vy = 0.0
        diem_tb = chon[2] if cur is None else (1 - HE_SO_DIEM) * diem_tb + HE_SO_DIEM * chon[2]
        cur, mat, w, h = (chon[0], chon[1]), 1, chon[3], chon[4]
        out[t] = {"frame": t, "x": int(chon[0]), "y": int(chon[1]), "w": int(chon[3]), "h": int(chon[4]),
                  "score": round(float(chon[2]), 3), "state": "detected", "nhay": bool(nhay)}
    return out


def _tam(e: dict) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def hop_hai_luot(xuoi: dict[int, dict], nguoc: dict[int, dict]) -> dict[int, dict]:
    """Mỗi khung: có một lượt thì lấy, có cả hai thì lấy điểm cao hơn (chồng vị trí hay không đều vậy — bất đồng ⇒ điểm quyết)."""
    out = {}
    for t in sorted(set(xuoi) | set(nguoc)):
        a, b = xuoi.get(t), nguoc.get(t)
        out[t] = a if b is None or (a is not None and a["score"] >= b["score"]) else b
    return out


def bo_doan_ngan(det: dict[int, dict], khung_moi: set[int]) -> dict[int, dict]:
    """Bỏ đoạn detected ngắn hơn DOAN_TOI_THIEU khung trừ khi nó chứa (±1) một khung mồi: ứng viên lẻ trúng ngưỡng không phải vết."""
    ds = sorted(det)
    doan, cur = [], []
    for t in ds:
        if cur and t - cur[-1] > HO_TOI_DA + 1:
            doan.append(cur)
            cur = []
        cur.append(t)
    if cur:
        doan.append(cur)
    giu = {}
    for d in doan:
        co_moi = any(t + k in khung_moi for t in d for k in (-1, 0, 1))
        if len(d) >= DOAN_TOI_THIEU or co_moi:
            giu.update({t: det[t] for t in d})
    return giu


def theo_vet(uv: list[list[tuple]], kich: tuple[int, int], khung_moi: set[int],
             hop_moi: dict[int, list[tuple]] | None = None) -> tuple[dict[int, dict], dict]:
    """Ứng viên (đã cache) ⇒ {khung: entry detected} + thông tin ngưỡng. `kich` = (w, h) mẫu, dùng làm cỡ ban đầu.
    `hop_moi` ({khung: [(x, y, w, h)]} của box mồi) bật khoá có danh tính vết (khoa_danh_tinh); None = chỉ mã cũ (lượt tự học)."""
    n = len(uv)
    hi, lo, nen95 = nguong_tuong_doi(uv)
    xuoi = _mot_luot(uv, range(n), hi, lo, kich)
    nguoc = _mot_luot(uv, range(n - 1, -1, -1), hi, lo, kich)
    det = bo_doan_ngan(hop_hai_luot(xuoi, nguoc), khung_moi)
    tt = {"hi": round(hi, 3), "lo": round(lo, 3), "nen95": round(nen95, 3), "xuoi": len(xuoi), "nguoc": len(nguoc), "hop": len(det)}
    if hop_moi is None:
        return det, tt
    from .khoa_danh_tinh import theo_vet_danh_tinh  # nhập muộn: module đó dùng hằng của module này
    return theo_vet_danh_tinh(uv, kich, khung_moi, hop_moi, det, hi, lo, tt)
