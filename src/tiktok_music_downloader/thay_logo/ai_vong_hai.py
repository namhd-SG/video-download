"""AI vòng hai: box AI (AI nhìn ảnh chỉ chỗ logo ở đoạn lõi còn để lộ) thành MỐC VỊ TRÍ cho vết — có kiểm, không tin mù.

User chốt 15/10 (pane tkkien 11:52, 12:46): "gọi AI vào … đè chữ đè vật vẫn dc". Đo kq15 (khung AI miễn MỌI cổng, lan ±3 khung, xoá ứng
viên xa AI): % lộ giảm mạnh nhưng DÁN SAI (v05 k842 lên chữ "learn?", v05 k893 lệch cao, v13 k9682 lên dòng chữ) và làm TỤT mốc đã
đúng (v17 k476, v38 k241 — ứng viên đúng của lượt một bị xoá). agy thaylogo-ai2 R2b ⇒ lưới:
- KHÔNG xoá ứng viên lượt một; chỉ THAY vị trí vết tại khung AI khi mốc AI qua kiểm.
- L2 (hình): tại vị trí gán, điểm sau xoá chữ ≥ max(`SAN_TUYET_DOI`, `HE_SO_SAN` × sàn hình vết); có chữ trong tấm nền thì điểm không được
  tụt khi xoá chữ (`la_logo_qua_chu` — chữ phụ đề giống logo thì tụt).
- L1 (quỹ đạo): mốc AI chỉ nhận khi có MỐC KHÁC (mốc AI qua L2 hoặc khung dò đạt sàn) trong ±`CAP_TOI_DA` khung, dịch giữa hai mốc
  ≤ max(`LECH_PX`, `LECH_TI_LE`·w) + `GIA_TOC_PX`·Δkhung (không có bước nhảy). Mốc lẻ loi bị bỏ.
- Khung kẹp giữa hai mốc liền nhau (≤ `CAP_TOI_DA`): vị trí = NỘI SUY hai mốc (không dùng tâm box AI thô — logo che nửa thì tâm AI lệch).
- L3: cỡ box = trung vị cỡ vết. L4: tấm nền ép sát (gắn ở cổng).
Khung nhận gắn `ai` + `quy_dao` ⇒ miễn kiểm hình và cổng nội dung (được đè chữ/vật); cổng khớp mồi và mẫu vẫn chỉ từ box mồi gốc.
"""
from __future__ import annotations

import numpy as np

from .box_moi import BoxMoi
from .chu_phu_de import cham_qua_chu, chu_trong_tam_nen, la_logo_qua_chu
from .kiem_hinh import san_hinh
from .nguon_khung import NguonKhung

SAN_TUYET_DOI, HE_SO_SAN = 0.15, 0.35
CAP_TOI_DA = 6
LECH_PX, LECH_TI_LE, GIA_TOC_PX = 6.0, 0.08, 4.0
KHOP_AI_PX, KHOP_AI_TI_LE = 12, 0.25  # ứng viên coi là "của AI" khi tâm lệch tâm box AI ≤ max(12 px, 25% bề rộng box AI)


def _tam(e: dict) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def _ung_vien_ai(uv_khung: list[tuple], b: BoxMoi) -> tuple | None:
    cx, cy = b.x + b.w / 2, b.y + b.h / 2
    gan = [c for c in uv_khung if np.hypot(c[0] + c[3] / 2 - cx, c[1] + c[4] / 2 - cy) <= max(KHOP_AI_PX, KHOP_AI_TI_LE * b.w)]
    return max(gan, key=lambda c: c[2]) if gan else None


def gan_moc_ai(nguon: NguonKhung, det: dict[int, dict], uv, mau: np.ndarray, neo_ai: list[BoxMoi]) -> tuple[dict[int, dict], dict]:
    """`det` (sau theo_vet/bỏ mồi chữ) ⇒ (det có mốc AI đã kiểm + khung nội suy giữa các mốc, số đếm). Một lượt đọc tuần tự."""
    dem = {"ai_box": len(neo_ai), "ai_khong_ung_vien": 0, "ai_truot_hinh": 0, "ai_le_loi": 0, "ai_nhan": 0, "noi_suy": 0}
    if not neo_ai or not det:
        return det, dem
    san = san_hinh(list(det.values())) or 0.0
    w = int(np.median([e["w"] for e in det.values()]))
    h = int(np.median([e["h"] for e in det.values()]))
    cho: dict[int, dict] = {}
    for b in neo_ai:
        if not 0 <= b.khung < len(uv):
            continue
        c = _ung_vien_ai(uv[b.khung][0], b)
        if c is None:
            dem["ai_khong_ung_vien"] += 1
            continue
        cx, cy = c[0] + c[3] / 2, c[1] + c[4] / 2
        cho[b.khung] = {"frame": b.khung, "x": int(round(cx - w / 2)), "y": int(round(cy - h / 2)), "w": w, "h": h, "score": None,
                        "state": "detected", "nhay": False}
    mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
    hinh_ok: dict[int, dict] = {}
    if cho:
        cuoi = max(cho)
        for i, g in enumerate(nguon.doc_tuan_tu()):
            e = cho.get(i)
            if e is not None:
                t, s = cham_qua_chu(g, mau_u8, e)
                if s >= max(SAN_TUYET_DOI, HE_SO_SAN * san) and (not chu_trong_tam_nen(g, e) or la_logo_qua_chu(t, s)):
                    e["score"], e["diem_xoa_chu"] = round(max(t, s), 3), round(s, 3)
                    hinh_ok[i] = e
                else:
                    dem["ai_truot_hinh"] += 1
            if i >= cuoi:
                break
    moc = {k: e for k, e in det.items() if (e.get("score") or 0) >= san}
    moc.update(hinh_ok)
    ks = sorted(moc)

    def lien(a: int, b: int) -> bool:
        (ax, ay), (bx, by) = _tam(moc[a]), _tam(moc[b])
        return 0 < b - a <= CAP_TOI_DA and np.hypot(bx - ax, by - ay) <= max(LECH_PX, LECH_TI_LE * w) + GIA_TOC_PX * (b - a)

    ke = {k: [j for j in ks if 0 < abs(j - k) <= CAP_TOI_DA] for k in hinh_ok}
    nhan = {k for k in hinh_ok if any(lien(min(k, j), max(k, j)) for j in ke[k])}
    dem["ai_le_loi"] = len(hinh_ok) - len(nhan)
    out = dict(det)
    for k in nhan:
        out[k] = dict(hinh_ok[k], ai=True, quy_dao=True)
    dem["ai_nhan"] = len(nhan)
    giu = sorted(set(k for k in ks if k not in hinh_ok) | nhan)
    for a, b in zip(giu, giu[1:]):
        if not (a in nhan or b in nhan) or not lien(a, b) or b - a < 2:
            continue
        (ax, ay), (bx, by) = _tam(moc[a]), _tam(moc[b])
        for k in range(a + 1, b):
            r = (k - a) / (b - a)
            cx, cy = ax + r * (bx - ax), ay + r * (by - ay)
            cu = out.get(k)
            if cu is not None and np.hypot(_tam(cu)[0] - cx, _tam(cu)[1] - cy) <= max(LECH_PX, LECH_TI_LE * w):
                out[k] = dict(cu, ai=True, quy_dao=True)
            else:
                out[k] = {"frame": k, "x": int(round(cx - w / 2)), "y": int(round(cy - h / 2)), "w": w, "h": h, "score": None,
                          "state": "detected", "nhay": False, "ai": True, "quy_dao": True, "noi_suy_ai": True}
                dem["noi_suy"] += 1
    return out, dem
