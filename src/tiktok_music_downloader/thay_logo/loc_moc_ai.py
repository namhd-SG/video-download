"""LỌC MỐC AI THÔ trước lộ trình: box AI (AI nhìn ảnh chỉ chỗ logo) chỉ vào lộ trình khi không có bằng chứng ngược.

Vì sao: lộ trình nhận MỌI box AI làm mốc trọng số cao, kể cả box mà lưới AI vòng hai (`ai_vong_hai`) đã bác ⇒ đo 15/10 (kq20): v13
k9670–k9681 box lên dòng chữ (AI vẽ cùng một box 17 lần trên vùng cắt tĩnh), v01 k4340–k4349 box lên áo trống (AI lặp tâm vùng cắt đang
trôi theo vết cũ). Không thể chỉ nhận box đã qua lưới: v05 k826–k842 (logo sau hộp phụ đề) AI chỉ đúng mà không có ứng viên lõi — lộ
trình sinh ra để cứu đúng ca đó. Đặc tả qua 5 vòng phản biện (agy thaylogo-ai2 R3–R5).

Box CÓ ứng viên lõi gần (`ai_vong_hai._ung_vien_ai`) luôn giữ. Box KHÔNG ứng viên ("thô") bị bác theo 4 bước:
1. L5 — xung đột vết dò: có det không-AI tại khung, lệch > `LECH_PX`, điểm xoá chữ det ≥ max(`SAN_TUYET_DOI`, `HE_SO_SAN`·sàn) VÀ
   ≥ `TI_SO_L5` × điểm xoá chữ tại AI — miễn khi box nằm trên đường nối hai box có ứng viên hai phía (±`CUA_NOI` khung, lệch ≤ `LECH_PX`).
2. D1 — cụm tĩnh lan từ L5: box trùng tâm (≤ `CUM_PX`) với ≥ `CUM_TOI_THIEU` box đã bị L5 bác trong ±`CUM_KHUNG` khung (AI lặp cùng
   một box sai). Chỉ lan từ L5: logo thật cũng đứng yên (v01 k2609–k2624 AI đúng, tĩnh).
3. D2 — box không có box có-ứng-viên nào khớp quỹ đạo trong ±`HAI_PHIA` VÀ điểm xoá chữ tại AI < `SAN_TUYET_DOI`.
4. 2B — box không khớp quỹ đạo (lệch ≤ `LECH_PX` + `GIA_TOC_PX`·Δ) với BẤT KỲ mốc AI còn lại nào trong ±`HAI_PHIA` khung.
Khung bị L5 bác: det tại đúng khung đó cũng KHÔNG làm mốc (v05 k908: det bám chữ điểm 0,69). Chỉ đúng khung — chặn cả lân cận làm mất
det đúng (v05 k1001, đo kq21d).
Đo 12 video Test3 (kq21e): v05 0,5→0,2 % lộ; v01 1,3→1,5, v13 1,4→1,7 (chỗ dán sai chuyển thành sót); 0 mốc user đổi.
"""
from __future__ import annotations

import math

import numpy as np

from .ai_vong_hai import GIA_TOC_PX, HE_SO_SAN, SAN_TUYET_DOI, _ung_vien_ai
from .box_moi import BoxMoi
from .chu_phu_de import cham_qua_chu
from .kiem_hinh import san_hinh
from .nguon_khung import NguonKhung

LECH_PX = 8.0
HAI_PHIA = 10
TI_SO_L5 = 2.5
CUA_NOI = 15
CUM_PX, CUM_KHUNG, CUM_TOI_THIEU = 2.0, 60, 2


def _tam(b: BoxMoi) -> tuple[float, float]:
    return b.x + b.w / 2, b.y + b.h / 2


def _khop_quy_dao(b: BoxMoi, ds) -> bool:
    return any(0 < abs(o.khung - b.khung) <= HAI_PHIA and math.dist(_tam(b), _tam(o)) <= LECH_PX + GIA_TOC_PX * abs(o.khung - b.khung)
               for o in ds)


def tren_duong_noi(b: BoxMoi, co: dict[int, BoxMoi]) -> bool:
    """Box nằm trên đường nối box có-ứng-viên gần nhất hai phía (±CUA_NOI khung), lệch ≤ LECH_PX."""
    tr = [k for k in co if b.khung - CUA_NOI <= k < b.khung]
    sa = [k for k in co if b.khung < k <= b.khung + CUA_NOI]
    if not tr or not sa:
        return False
    a, z = max(tr), min(sa)
    (ax, ay), (zx, zy) = _tam(co[a]), _tam(co[z])
    r = (b.khung - a) / (z - a)
    return math.dist(_tam(b), (ax + r * (zx - ax), ay + r * (zy - ay))) <= LECH_PX


def chon_moc_ai(co: dict[int, BoxMoi], tho: list[BoxMoi], diem_ai: dict[int, float],
                xung_dot: dict[int, tuple[float, float]], san: float) -> tuple[list[BoxMoi], set[int], dict[int, str]]:
    """Phần QUYẾT ĐỊNH (thuần, không đọc khung). `diem_ai[k]` = điểm xoá chữ tại box thô k; `xung_dot[k]` = (khoảng cách, điểm xoá
    chữ det) cho box thô có det không-AI tại khung. ⇒ (box giữ, khung bị L5 bác, lý do bác theo khung)."""
    bac: set[int] = set()
    bo_l5: set[int] = set()
    ly: dict[int, str] = {}
    for b in tho:
        x = xung_dot.get(b.khung)
        if x is None or tren_duong_noi(b, co):
            continue
        kc, s_d = x
        s_ai = diem_ai.get(b.khung, 0.0)
        if kc > LECH_PX and s_d >= max(SAN_TUYET_DOI, HE_SO_SAN * san) and s_d >= TI_SO_L5 * s_ai:
            bac.add(b.khung)
            bo_l5.add(b.khung)
            ly[b.khung] = f"l5 kc={kc:.0f} det={s_d:.3f} ai={s_ai:.3f}"
    for b in tho:
        if b.khung in bac:
            continue
        n = sum(1 for o in tho if o.khung in bo_l5 and abs(o.khung - b.khung) <= CUM_KHUNG and math.dist(_tam(b), _tam(o)) <= CUM_PX)
        if n >= CUM_TOI_THIEU:
            bac.add(b.khung)
            ly[b.khung] = f"d1 n={n}"
    for b in tho:
        if b.khung in bac:
            continue
        if not _khop_quy_dao(b, co.values()) and diem_ai.get(b.khung, 0.0) < SAN_TUYET_DOI:
            bac.add(b.khung)
            ly[b.khung] = f"d2 s_ai={diem_ai.get(b.khung, 0.0):.3f}"
    con = list(co.values()) + [b for b in tho if b.khung not in bac]
    for b in tho:
        if b.khung not in bac and not _khop_quy_dao(b, con):
            bac.add(b.khung)
            ly[b.khung] = "2b"
    return list(co.values()) + [b for b in tho if b.khung not in bac], bo_l5, ly


def loc_moc_ai(nguon: NguonKhung, det: dict[int, dict], mau: np.ndarray, neo_ai: list[BoxMoi], uv) -> tuple[list[BoxMoi], set[int], dict]:
    """Chấm điểm box thô (một lượt đọc tuần tự) rồi `chon_moc_ai`. ⇒ (box giữ, khung bị L5 bác, số đếm)."""
    san = san_hinh(list(det.values())) or 0.0
    w = int(np.median([e["w"] for e in det.values()]))
    h = int(np.median([e["h"] for e in det.values()]))
    co = {b.khung: b for b in neo_ai if 0 <= b.khung < len(uv) and _ung_vien_ai(uv[b.khung][0], b) is not None}
    tho = [b for b in neo_ai if b.khung not in co and 0 <= b.khung < len(uv)]
    diem_ai: dict[int, float] = {}
    xung_dot: dict[int, tuple[float, float]] = {}
    can = {b.khung: b for b in tho}
    if can:
        mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
        cuoi = max(can)
        for i, g in enumerate(nguon.doc_tuan_tu()):
            b = can.get(i)
            if b is not None:
                ax, ay = _tam(b)
                _, diem_ai[i] = cham_qua_chu(g, mau_u8, {"x": int(round(ax - w / 2)), "y": int(round(ay - h / 2)), "w": w, "h": h})
                d = det.get(i)
                if d is not None and not d.get("ai"):
                    _, s_d = cham_qua_chu(g, mau_u8, d)
                    xung_dot[i] = (math.dist((ax, ay), (d["x"] + d["w"] / 2, d["y"] + d["h"] / 2)), s_d)
            if i >= cuoi:
                break
    giu, bo_l5, ly = chon_moc_ai(co, tho, diem_ai, xung_dot, san)
    dem = {"co_ung_vien": len(co), "tho": len(tho), "tho_bi_bac": len(ly), "l5": len(bo_l5)}
    return giu, bo_l5, dem
