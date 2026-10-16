"""CHE QUA CHỮ: lấp các đoạn khung bị cổng chặn ngắn kẹp giữa hai khung đang dán — được đè chữ (user 16/10: "logo đi vô chữ vẫn ko che
dc … che nhầm xíu ko sao", "đè lên chữ dc mà đừng sợ"; 14:2x chọn "che qua chữ + dò hai đầu" cho đường có AI).

Vì sao: cổng phụ đề chặn cả khung mà vết dò ĐÚNG chỗ logo nhưng điểm thấp vì chữ đè (miễn đè chữ đòi điểm ≥ sàn hình vết); logo lộ giữa
hai khung đã che. Đo 12 video Test3 (đường không AI): Test 03_10 lộ 22% → 3,5%, 03_1 4,0% → 0,8%; 6 mốc user lên "che tại khung".

Chạy SAU mọi cổng, TRƯỚC `cong.go_chan_le`. Mỗi đoạn khung bị chặn liền (`hidden_*`) dài ≤ `GAP_MAX`, kẹp giữa hai khung đang dán a, b:
1. NỘI SUY (cả hai đường): tâm a–b lệch ≤ `LECH_PX` + `GIA_TOC_PX`·(b−a) ⇒ dán theo đường thẳng; vết dò thật của khung (có điểm, không
   phải khung kiểm hình bác) nằm ≤ `GAN_DET` quanh đường ⇒ giữ vị trí vết dò.
2. DÒ HAI ĐẦU (CHỈ đường có AI): hai đầu xa hơn ngưỡng ⇒ mỗi khung lấy ≤ `K` đỉnh khớp mẫu trên ảnh đã xoá chữ trong vùng bao box a, b
   (+`PAD`), cộng vết dò sẵn có; quy hoạch động chọn đường nối tâm a → tâm b (bước ≤ `BUOC_DP`) tối đa Σ điểm − `PHAT`·Σ bước/`BUOC_DP`;
   dán khung trên đường có điểm ≥ `SAN_DAN`. Đường không AI KHÔNG dò hai đầu: đo được dán lên má em bé (03_10) / tháp (03_4).
Không lấp khung có box mồi ±1 (đổi chỗ ở đó làm `_box_duoc_phu` coi box mồi "không được phủ" ⇒ cả video thành chờ người — 03_38), và
không nội suy chéo qua box mồi khi đường lệch tâm box. Khung còn sót trong một đoạn đã lấp một phần ⇒ `giu_chan` (không để `go_chan_le`
gỡ ăn theo mẩu ≤ 3 khung). Khung lấp: `filled`, `de_chu`, tấm nền hẹp, cờ `qua_chu` (kiểu "noi" | "dp").

HẰNG SỐ CHƯA HIỆU CHỈNH ngoài 12 video Test3: GAP_MAX, LECH_PX/GIA_TOC_PX, GAN_DET, PAD, K, BUOC_DP, PHAT, SAN_DAN. SAN_DAN 0,165 đặt giữa
điểm cao nhất của khung dán sai (0,159) và thấp nhất của khung đúng (0,171) trên 66 khung đã soi mắt — phân tách hẹp.
Phản biện: agy thaylogo-quachu R1b (lỗ K1–K6 đã khoá ở đây và ở `cong.chuan_pad_vet`, `duong_ong.ap_moi_cong`).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import cong
from .box_moi import BoxMoi
from .chu_phu_de import thong_cao_xoa_chu
from .dinh_vi import SIGMA, _hp
from .kiem_hinh import CHAN_HINH
from .nguon_khung import NguonKhung

GAP_MAX = 45
LECH_PX, GIA_TOC_PX = 8.0, 4.0
GAN_DET = 12.0
PAD, K, BUOC_DP, PHAT, SAN_DAN = 16, 5, 60.0, 0.15, 0.165


def _tam(e: dict) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def _vet_that(e: dict) -> bool:
    """Khung có vị trí do VẾT DÒ thật (có điểm), không phải vị trí lõi tự kẻ mà kiểm hình đã bác."""
    return e.get("x") is not None and e.get("score") is not None and e.get("state") != CHAN_HINH


def _dat(e: dict, x: float, y: float, w: int, h: int, rong: int, cao: int, kieu: str) -> None:
    x = int(round(min(max(x, 0), max(0, rong - w))))
    y = int(round(min(max(y, 0), max(0, cao - h))))
    e.update({"chan_cu": e.get("state"), "state": "filled", "x": x, "y": y, "w": w, "h": h, "de_chu": True,
              "plate_pad": cong.PAD_CHAT, "qua_chu": kieu})


def _ung_vien(g: np.ndarray, vung, t: np.ndarray, w: int, h: int, them) -> list[tuple[tuple[float, float], float]]:
    """≤ K đỉnh (tâm, điểm) trong vùng (nén cực đại bán kính w/2 × h/2) + vị trí `them` chấm cùng thước."""
    x0, y0, x1, y1 = vung
    r = cv2.matchTemplate(thong_cao_xoa_chu(g[y0:y1, x0:x1]), t, cv2.TM_CCOEFF_NORMED)
    out, rr = [], r.copy()
    for _ in range(K):
        _, s, _, (lx, ly) = cv2.minMaxLoc(rr)
        if s < 0:
            break
        out.append(((x0 + lx + w / 2, y0 + ly + h / 2), float(s)))
        rr[max(0, ly - h // 2):ly + h // 2 + 1, max(0, lx - w // 2):lx + w // 2 + 1] = -1
    if them is not None:
        lx, ly = int(round(them[0] - w / 2)) - x0, int(round(them[1] - h / 2)) - y0
        if 0 <= ly < r.shape[0] and 0 <= lx < r.shape[1]:
            out.append((them, float(r[ly, lx])))
    return out


def _duong_tot_nhat(pa, pb, tang: list[list]) -> list | None:
    """Quy hoạch động: đường nối pa → pb qua mỗi tầng một ứng viên, bước ≤ BUOC_DP. Trả [(tâm, điểm)] mỗi tầng hoặc None."""
    lop = [[(pa, 0.0)]] + tang + [[(pb, 0.0)]]
    tot = [[-math.inf] * len(c) for c in lop]
    truoc = [[-1] * len(c) for c in lop]
    tot[0][0] = 0.0
    for q in range(1, len(lop)):
        for u, (pu, su) in enumerate(lop[q]):
            for v, (pv, _) in enumerate(lop[q - 1]):
                if tot[q - 1][v] == -math.inf:
                    continue
                d = math.dist(pu, pv)
                if d > BUOC_DP:
                    continue
                val = tot[q - 1][v] + su - PHAT * d / BUOC_DP
                if val > tot[q][u]:
                    tot[q][u], truoc[q][u] = val, v
    if tot[-1][0] == -math.inf:
        return None
    duong, u = [], 0
    for q in range(len(lop) - 1, 1, -1):
        u = truoc[q][u]
        duong.append(lop[q - 1][u])
    return duong[::-1]


def lap_qua_chu(nguon: NguonKhung, track: list[dict], mau: np.ndarray, cum: list[BoxMoi], co_ai: bool = False) -> dict:
    """Lấp tại chỗ trên `track` (sau cổng, trước go_chan_le). Trả số khung lấp theo kiểu."""
    dem = {"noi": 0, "dp": 0}
    box = {b.khung + d: b for b in cum for d in (-1, 0, 1)}
    rong, cao = nguon.rong, nguon.cao
    mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
    n, i = len(track), 0
    while i < n:
        if not str(track[i].get("state", "")).startswith("hidden_"):
            i += 1
            continue
        j = i
        while j < n and str(track[j].get("state", "")).startswith("hidden_"):
            j += 1
        a, b = i - 1, j
        if a < 0 or b >= n or track[a].get("state") not in cong.DA_CHAC or track[b].get("state") not in cong.DA_CHAC or j - i > GAP_MAX:
            i = j
            continue
        w, h = max(track[a]["w"], track[b]["w"]), max(track[a]["h"], track[b]["h"])
        pa, pb, L = _tam(track[a]), _tam(track[b]), b - a
        if math.dist(pa, pb) <= LECH_PX + GIA_TOC_PX * L:
            duong = {k: (pa[0] + (k - a) / L * (pb[0] - pa[0]), pa[1] + (k - a) / L * (pb[1] - pa[1])) for k in range(i, j)}
            cat_box = any(math.dist(duong[k], (box[k].x + box[k].w / 2, box[k].y + box[k].h / 2)) > max(GAN_DET, 0.5 * max(box[k].w, box[k].h))
                          for k in range(i, j) if track[k]["frame"] in box)
            if not cat_box:
                for k in range(i, j):
                    e = track[k]
                    if e["frame"] in box:
                        continue
                    p = duong[k]
                    if _vet_that(e) and math.dist(_tam(e), p) <= GAN_DET:
                        p = _tam(e)
                    _dat(e, p[0] - w / 2, p[1] - h / 2, w, h, rong, cao, "noi")
                    dem["noi"] += 1
        elif co_ai:
            t = _hp(cv2.resize(mau_u8, (w, h), interpolation=cv2.INTER_LINEAR), SIGMA)
            vung = (max(0, int(min(pa[0], pb[0]) - w / 2 - PAD)), max(0, int(min(pa[1], pb[1]) - h / 2 - PAD)),
                    min(rong, int(max(pa[0], pb[0]) + w / 2 + PAD)), min(cao, int(max(pa[1], pb[1]) + h / 2 + PAD)))
            if vung[2] - vung[0] >= w and vung[3] - vung[1] >= h and float(t.std()) > 1e-3:
                tang = []
                for k in range(i, j):
                    g = nguon.doc(track[k]["frame"])
                    e = track[k]
                    tang.append(_ung_vien(g, vung, t, w, h, _tam(e) if _vet_that(e) else None) if g is not None else [])
                duong_dp = _duong_tot_nhat(pa, pb, tang)
                if duong_dp is not None:
                    for k, (p, s) in zip(range(i, j), duong_dp):
                        if track[k]["frame"] in box or s < SAN_DAN:
                            continue
                        _dat(track[k], p[0] - w / 2, p[1] - h / 2, w, h, rong, cao, "dp")
                        dem["dp"] += 1
        if any(track[k].get("qua_chu") for k in range(i, j)):
            for k in range(i, j):
                if not track[k].get("qua_chu"):
                    track[k]["giu_chan"] = True
        i = j
    return dem
