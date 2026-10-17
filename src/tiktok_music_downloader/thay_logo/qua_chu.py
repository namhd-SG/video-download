"""CHE QUA CHỮ: lấp các đoạn khung bị cổng chặn ngắn kẹp giữa hai khung đang dán — được đè chữ (user 16/10: "logo đi vô chữ vẫn ko che
dc … che nhầm xíu ko sao", "đè lên chữ dc mà đừng sợ").

Vì sao: cổng phụ đề chặn cả khung mà vết dò ĐÚNG chỗ logo nhưng điểm thấp vì chữ đè (miễn đè chữ đòi điểm ≥ sàn hình vết); logo lộ giữa
hai khung đã che. Đo 12 video Test3 (đường không AI): Test 03_10 lộ 22% → 3,5%, 03_1 4,0% → 0,8%; 6 mốc user lên "che tại khung".

Chạy SAU mọi cổng, TRƯỚC `cong.go_chan_le`. Mỗi đoạn khung bị chặn liền (`hidden_*`) dài ≤ `GAP_MAX`, kẹp giữa hai khung đang dán a, b,
tâm a–b lệch ≤ `LECH_PX` + `GIA_TOC_PX`·(b−a) ⇒ dán theo đường thẳng a → b; vết dò thật của khung (có điểm, không phải khung kiểm hình
bác) nằm ≤ `GAN_DET` quanh đường ⇒ giữ vị trí vết dò. Hai đầu xa hơn ngưỡng (logo nhảy chỗ) ⇒ không lấp: đường không AI không có gì
để biết logo đi đâu (dò ảnh ở đó đo được dán lên má em bé — Test 03_10 — và tháp — Test 03_4).
Khung box mồi ±1 (box của MỌI cụm trong video) KHÔNG bị dời: đổi chỗ ở đó làm `_box_duoc_phu` coi box mồi "không được phủ" ⇒ cả video
thành chờ người (03_38). Ô vết dò ở đó trùng box ⇒ gỡ TẠI CHỖ với tấm nền hẹp (không nháy, không phình nền giữa vùng đã che) — trừ khi
kiểm hình đã bác khung đó VÀ nó lệch đường nối > `GAN_DET`: box mồi có thể sai (Test 03_5 k896 cao hơn logo thật ~40 px), lúc đó để nguyên.
Đường thẳng được nội suy kể cả khi lệch tâm box mồi trong đoạn: chặn trường hợp đó để lộ hẳn logo ở Test 03_38 k287–299, trong khi dán
theo đường che được phần lớn.
Khung lấp: `filled`, `de_chu`, tấm nền hẹp, cờ `qua_chu` = "noi".

HẰNG SỐ CHƯA HIỆU CHỈNH ngoài 12 video Test3: GAP_MAX, LECH_PX/GIA_TOC_PX, GAN_DET.
Phản biện: agy thaylogo-quachu R1b (K1–K6) + R2b (tách đường không AI, bỏ chặn nội suy qua box mồi lệch) + R3b/R4b (gỡ tại chỗ).
"""
from __future__ import annotations

import math

from . import cong
from .box_moi import BoxMoi
from .kiem_hinh import CHAN_HINH
from .nguon_khung import NguonKhung

GAP_MAX = 45
LECH_PX, GIA_TOC_PX = 8.0, 4.0
GAN_DET = 12.0


def _tam(e: dict) -> tuple[float, float]:
    return e["x"] + e["w"] / 2, e["y"] + e["h"] / 2


def _vet_that(e: dict) -> bool:
    """Khung có vị trí do VẾT DÒ thật (có điểm), không phải vị trí lõi tự kẻ mà kiểm hình đã bác."""
    return e.get("x") is not None and e.get("score") is not None and e.get("state") != CHAN_HINH


def _dat(e: dict, x: float, y: float, w: int, h: int, rong: int, cao: int) -> None:
    x = int(round(min(max(x, 0), max(0, rong - w))))
    y = int(round(min(max(y, 0), max(0, cao - h))))
    e.update({"chan_cu": e.get("state"), "state": "filled", "x": x, "y": y, "w": w, "h": h, "de_chu": True,
              "plate_pad": cong.PAD_CHAT, "qua_chu": "noi"})


def _phu_box(e: dict, b: BoxMoi) -> bool:
    """Ô của khung trùng box mồi — đúng công thức `duong_ong._box_duoc_phu` / `cong.cong_khop` (tâm lệch ≤ 0,5 cạnh dài box)."""
    if e.get("x") is None:
        return False
    canh = 0.5 * max(b.w, b.h)
    return abs(e["x"] + e["w"] / 2 - (b.x + b.w / 2)) <= canh and abs(e["y"] + e["h"] / 2 - (b.y + b.h / 2)) <= canh


def lap_qua_chu(nguon: NguonKhung, track: list[dict], cum: list[BoxMoi], moi_box: list[BoxMoi] | None = None) -> dict:
    """Lấp tại chỗ trên `track` (sau cổng, trước go_chan_le). `moi_box`: box mồi của MỌI cụm trong video (mặc định `cum`). Trả số khung
    lấp."""
    dem = {"noi": 0}
    box = {b.khung + d for b in cum for d in (-1, 0, 1)}
    quanh: dict[int, list[BoxMoi]] = {}
    for bm in (moi_box if moi_box is not None else cum):
        for d in (-1, 0, 1):
            quanh.setdefault(bm.khung + d, []).append(bm)
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
            for k in range(i, j):
                e = track[k]
                p = (pa[0] + (k - a) / L * (pb[0] - pa[0]), pa[1] + (k - a) / L * (pb[1] - pa[1]))
                if any(_phu_box(e, bm) for bm in quanh.get(e["frame"], ())):
                    if e.get("state") != CHAN_HINH or math.dist(_tam(e), p) <= GAN_DET:
                        e.update({"chan_cu": e.get("state"), "state": "detected" if e.get("score") is not None else "filled",
                                  "de_chu": True, "plate_pad": cong.PAD_CHAT, "qua_chu": "noi"})
                        dem["noi"] += 1
                    continue
                if e["frame"] in box:
                    continue
                if _vet_that(e) and math.dist(_tam(e), p) <= GAN_DET:
                    p = _tam(e)
                _dat(e, p[0] - w / 2, p[1] - h / 2, w, h, nguon.rong, nguon.cao)
                dem["noi"] += 1
        i = j
    return dem
