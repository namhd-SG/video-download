"""Các cổng chặn khung trước khi render. Mỗi cổng chỉ được HẠ khung `detected` xuống trạng thái bị chặn, không bao giờ nâng.

Thứ tự trong đường ống: phụ đề cũ → tương phản học → vành ngang + nét lạ (theo video) → khớp box mồi (theo vết) → cổng cứng.
Nguồn: `p0b_subtitle_rule.py`, phép tương phản trong `p1a_t2_pipeline_v2.py`, `p1a_subtitle_ring_probe.py`,
`p1a_agreement_gate_v2.py`. Hằng số giữ nguyên số đã đo (plan p1 §2g–§2i).
"""
from __future__ import annotations

import cv2
import numpy as np

from .box_moi import BoxMoi
from .dinh_vi import ti_le_phu_de

# Cổng phụ đề cũ (ĐP-1437): tấm nền A2 nới 4px chồng chữ trắng viền đen >3% ⇒ thử co về box chữ cũ +2px; vẫn chồng ⇒ bỏ.
PHU_DE_TI_LE, PAD_TAM_NEN, PAD_CHAT = 0.03, 4, 2
# Cổng tương phản HỌC theo video: nét chênh nền > max(65, 1,5 × tương phản của chính mẫu) ⇒ không phải watermark mờ.
TUONG_PHAN_SAN, TUONG_PHAN_HE_SO = 65.0, 1.5
# Cổng vành ngang (ĐP-1488 chọn (b) cho pilot): phụ đề tràn ngang ra ngoài box, watermark thì không.
VANH_RONG, VANH_SANG, VANH_THONG_CAO, VANH_SAN, VANH_K_MAD = 0.8, 180, 35, 0.01, 4.0
# Cổng khớp v2: chỉ xét box mồi mà track đang chắc (±1 khung); qua ⟺ khớp ≥ CAN_KHOP VÀ lệch = 0.
CAN_KHOP = 3
# Cổng NÉT LẠ (plan p1 §5c.2): nội dung lạ (khối chữ, phụ đề màu) nằm GỌN trong tấm nền (box ±PAD_TAM_NEN) mà C vẫn "chắc".
# Đo = PHẦN DƯ sau khi trừ mẫu: thông cao σ3 của khung − a × thông cao của mẫu (a khớp bình phương tối thiểu); điểm "nét lạ" =
# |dư| > NET_LA_THONG_CAO VÀ lệch trung vị vùng > NET_LA_LECH. Không dùng "loại trừ mặt nạ mẫu" (đề xuất kongming): đo trên clip
# tổng hợp, mặt nạ chữ watermark phủ 74% box, giãn 3px phủ 99,7% ⇒ r ≡ 0, cổng mù.
# Ngưỡng khung theo VIDEO = max(NET_LA_SAN, trung vị + K × MAD). Hằng ĐỀ XUẤT, CHƯA hiệu chỉnh trên video thật.
NET_LA_LECH, NET_LA_THONG_CAO, NET_LA_SAN, NET_LA_K_MAD = 65, 35, 0.03, 4.0
# Trung vị r > ngưỡng này ⇒ gắn cờ vết cho member soi. KHÔNG chặn cả vết: icon đặc sạch đã có r trung vị ~0,10 (clip tổng hợp)
# ⇒ chặn sẽ giết mọi icon. Hệ quả đã biết: nội dung lạ nằm trong box ở PHẦN LỚN video thì ngưỡng theo video bị kéo lên và mù.
NET_LA_PHO_BIEN = 0.10

CHAN_PHU_DE, CHAN_TUONG_PHAN, CHAN_VANH, CHAN_NET = "hidden_sub", "hidden_contrast", "hidden_ring", "hidden_net"


def cong_phu_de(g: np.ndarray, e: dict) -> None:
    """Phụ đề kiểu trắng viền đen chồng tấm nền. Mù với chữ trắng BÓNG MỜ (Test 02 _3) — cổng vành ngang bù chỗ đó."""
    if ti_le_phu_de(g, e["x"], e["y"], e["w"], e["h"], PAD_TAM_NEN) <= PHU_DE_TI_LE:
        return
    if ti_le_phu_de(g, e["x"], e["y"], e["w"], e["h"], PAD_CHAT) > PHU_DE_TI_LE:
        e["state"] = CHAN_PHU_DE
    else:
        e["plate_pad"] = PAD_CHAT


def nguong_tuong_phan(tuong_phan_mau: float) -> float:
    return max(TUONG_PHAN_SAN, TUONG_PHAN_HE_SO * tuong_phan_mau)


def cong_tuong_phan(g: np.ndarray, e: dict, mask: np.ndarray, nguong: float) -> None:
    """Nét trong box chênh nền quá mạnh so với chính watermark ⇒ đó là chữ/UI nội dung, không phải watermark mờ."""
    c = g[e["y"]:e["y"] + e["h"], e["x"]:e["x"] + e["w"]].astype(np.float32)
    if not c.size:
        return
    mk = cv2.resize(mask, (c.shape[1], c.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    if mk.sum() > 5 and (~mk).sum() > 5 and abs(c[mk].mean() - c[~mk].mean()) > nguong:
        e["state"] = CHAN_TUONG_PHAN


def ti_le_vanh(g: np.ndarray, e: dict) -> float:
    """Tỉ lệ điểm 'nét chữ sáng' (xám >180 VÀ thông cao σ3 >35) trong 2 dải trái/phải box, cao = box ± h/4."""
    H, W = g.shape
    gf = g.astype(np.float32)
    hp = gf - cv2.GaussianBlur(gf, (0, 0), 3)
    y0, y1 = max(0, e["y"] - e["h"] // 4), min(H, e["y"] + e["h"] + e["h"] // 4)
    rw = int(VANH_RONG * e["w"])
    parts = []
    for x0, x1 in ((max(0, e["x"] - rw), e["x"]), (e["x"] + e["w"], min(W, e["x"] + e["w"] + rw))):
        if x1 - x0 > 4:
            parts.append(((g[y0:y1, x0:x1] > VANH_SANG) & (hp[y0:y1, x0:x1] > VANH_THONG_CAO)).ravel())
    return float(np.concatenate(parts).mean()) if parts else 0.0


def _chan_theo_video(track: list[dict], ti_le: dict[int, float], san: float, k_mad: float, trang_thai: str) -> float | None:
    """Ngưỡng theo VIDEO = max(sàn, trung vị + K × MAD) trên các khung chắc; vượt ⇒ chặn. Trả trung vị (None nếu không có)."""
    v = np.array([ti_le[e["frame"]] for e in track if e.get("state") == "detected" and e["frame"] in ti_le])
    if not v.size:
        return None
    med = float(np.median(v))
    nguong = max(san, med + k_mad * (float(np.median(np.abs(v - med))) + 1e-4))
    for e in track:
        if e.get("state") == "detected" and ti_le.get(e["frame"], 0.0) > nguong:
            e["state"] = trang_thai
    return med


def cong_vanh_ngang(track: list[dict], ti_le: dict[int, float]) -> None:
    """Đo Test 02: bắt 50/58 khung phụ đề bóng mờ của _3, nhưng precision cờ ~40% (cờ oan trên giày/tóc/vạch sáng)."""
    _chan_theo_video(track, ti_le, VANH_SAN, VANH_K_MAD, CHAN_VANH)


def ti_le_net_la(g: np.ndarray, e: dict, mau: np.ndarray) -> float:
    """Tỉ lệ điểm 'nét lạ' trong tấm nền: phần dư sau khi trừ mẫu watermark (đã co về cỡ box) khỏi thông cao của khung."""
    H, W = g.shape
    p = PAD_TAM_NEN
    x0, y0, x1, y1 = max(0, e["x"] - p), max(0, e["y"] - p), min(W, e["x"] + e["w"] + p), min(H, e["y"] + e["h"] + p)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return 0.0
    vung = g[y0:y1, x0:x1].astype(np.float32)
    tt = np.zeros_like(vung)
    bx, by = e["x"] - x0, e["y"] - y0
    tr = cv2.resize(mau.astype(np.float32), (e["w"], e["h"]))
    tt[by:by + e["h"], bx:bx + e["w"]] = tr[:tt.shape[0] - by, :tt.shape[1] - bx]
    hc = vung - cv2.GaussianBlur(vung, (0, 0), 3)
    ht = tt - cv2.GaussianBlur(tt, (0, 0), 3)
    a = float((hc * ht).sum() / max(float((ht * ht).sum()), 1e-6))
    du = np.abs(hc - a * ht)
    return float(((du > NET_LA_THONG_CAO) & (np.abs(vung - np.median(vung)) > NET_LA_LECH)).mean())


def cong_net_la(track: list[dict], ti_le: dict[int, float]) -> bool:
    """Chặn khung có nét lạ vượt ngưỡng theo video. Trả True nếu nét lạ PHỔ BIẾN (trung vị > NET_LA_PHO_BIEN) ⇒ cờ cho member."""
    med = _chan_theo_video(track, ti_le, NET_LA_SAN, NET_LA_K_MAD, CHAN_NET)
    return med is not None and med > NET_LA_PHO_BIEN


def cong_khop(track: list[dict], boxes: list[BoxMoi], can: int = CAN_KHOP) -> dict:
    """Track cuối phải trùng box mồi ĐỘC LẬP: khớp = tâm lệch ≤ 0,5 × cạnh dài box mồi, xét ở khung box (±1).

    Bắt mẫu học từ mồi sai: mẫu sai tự nhất quán nên C vẫn "chắc", chỉ đối chiếu ngoài mới lộ (Test 02: 5/5 vết sai lệch ≥2,
    mọi vết đúng lệch 0). Box mà track không chắc tại đó tính `track_vang`, không tính lệch."""
    by = {e["frame"]: e for e in track}
    khop = lech = vang = 0
    for b in boxes:
        e = next((by[f] for f in (b.khung, b.khung - 1, b.khung + 1) if by.get(f, {}).get("state") == "detected"), None)
        if e is None:
            vang += 1
            continue
        cx, cy, canh = b.x + b.w / 2, b.y + b.h / 2, max(b.w, b.h)
        if abs(e["x"] + e["w"] / 2 - cx) <= 0.5 * canh and abs(e["y"] + e["h"] / 2 - cy) <= 0.5 * canh:
            khop += 1
        else:
            lech += 1
    return {"khop": khop, "lech": lech, "track_vang": vang, "qua_cong": khop >= can and lech == 0}


def khung_duoc_render(track: list[dict], qua_cong_khop: bool) -> list[dict]:
    """CỔNG CỨNG: chỉ khung `detected` của vết đã qua cổng khớp. Mọi thứ khác giữ nguyên watermark."""
    if not qua_cong_khop:
        return []
    return [e for e in track if e.get("state") == "detected"]
