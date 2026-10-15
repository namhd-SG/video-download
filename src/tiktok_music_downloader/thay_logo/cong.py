"""Các cổng chặn khung trước khi render. Mỗi cổng chỉ được HẠ khung `detected` xuống trạng thái bị chặn, không bao giờ nâng.

Thứ tự trong đường ống: phụ đề cũ → tương phản học → vành ngang + nét lạ (theo video) → khớp box mồi (theo vết) → cổng cứng.
Nguồn: `p0b_subtitle_rule.py`, phép tương phản trong `p1a_t2_pipeline_v2.py`, `p1a_subtitle_ring_probe.py`,
`p1a_agreement_gate_v2.py`. Hằng số giữ nguyên số đã đo (plan p1 §2g–§2i).
"""
from __future__ import annotations

import cv2
import numpy as np

from .box_moi import BoxMoi
from .chu_phu_de import mat_na_chu
from .dinh_vi import ti_le_phu_de

# Cổng phụ đề cũ (ĐP-1437): tấm nền A2 nới 4px chồng chữ trắng viền đen >3% ⇒ thử co về box chữ cũ +2px; vẫn chồng ⇒ bỏ.
PHU_DE_TI_LE, PAD_TAM_NEN, PAD_CHAT = 0.03, 4, 2
# Cổng tương phản HỌC theo video: nét chênh nền > max(65, 1,5 × tương phản của chính mẫu) ⇒ không phải watermark mờ.
TUONG_PHAN_SAN, TUONG_PHAN_HE_SO = 65.0, 1.5
# Cổng vành ngang (ĐP-1488 chọn (b) cho pilot): phụ đề tràn ngang ra ngoài box, watermark thì không. Sàn 0,04 (trước 0,01): đo ở
# PhotoRevive (Test 03_40) video gần như không có nét sáng ⇒ MAD ≈ 0 ⇒ ngưỡng rơi về sàn, dải sáng tĩnh 0,031 chặn oan 307/710 khung;
# phụ đề bóng mờ tổng hợp đo 0,054.
VANH_RONG, VANH_SANG, VANH_THONG_CAO, VANH_SAN, VANH_K_MAD = 0.8, 180, 35, 0.04, 4.0
# Cổng khớp: chỉ xét box mồi mà vết đang phủ (±1 khung); qua ⟺ khớp ≥ CAN_KHOP VÀ khớp > lệch. Không còn đòi "lệch = 0": một box mồi
# sai (agy gọi nhầm UI) từng giết cả vết đúng; mẫu học từ mồi sai thì lệch ĐA SỐ box ⇒ vẫn bị chặn.
CAN_KHOP = 1
# Khung của vết còn watermark thật (detected) hoặc đã lấp lỗ (filled) — cả hai đều được che; khung bị cổng chặn thì KHÔNG.
DA_CHAC = ("detected", "filled")
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


def _chan_theo_video(track: list[dict], ti_le: dict[int, float], san: float, k_mad: float, trang_thai: str,
                     mien=lambda e: False) -> float | None:
    """Ngưỡng theo VIDEO = max(sàn, trung vị + K × MAD) trên các khung chắc; vượt ⇒ chặn. Trả trung vị (None nếu không có)."""
    v = np.array([ti_le[e["frame"]] for e in track if e.get("state") in DA_CHAC and e["frame"] in ti_le])
    if not v.size:
        return None
    med = float(np.median(v))
    nguong = max(san, med + k_mad * (float(np.median(np.abs(v - med))) + 1e-4))
    for e in track:  # khung `mien` vẫn VÀO thống kê ngưỡng nhưng không bị chặn — bỏ khỏi thống kê làm trung vị video tụt và chặn oan
        # khung khác (đo kq16: v17 k470 detected → hidden_ring)
        if e.get("state") in DA_CHAC and ti_le.get(e["frame"], 0.0) > nguong and not mien(e):
            e["state"] = trang_thai
    return med


def cong_vanh_ngang(track: list[dict], ti_le: dict[int, float]) -> None:
    """Đo Test 02: bắt 50/58 khung phụ đề bóng mờ của _3, nhưng precision cờ ~40% (cờ oan trên giày/tóc/vạch sáng)."""
    _chan_theo_video(track, ti_le, VANH_SAN, VANH_K_MAD, CHAN_VANH, lambda e: e.get("de_chu") or e.get("ai"))  # chữ tràn cạnh logo đè


def ti_le_net_la(g: np.ndarray, e: dict, mau: np.ndarray, bo_chu: bool = False) -> float:
    """Tỉ lệ điểm 'nét lạ' trong tấm nền: phần dư sau khi trừ mẫu watermark (đã co về cỡ box) khỏi thông cao của khung. `bo_chu` ⇒ nét
    chữ phụ đề trắng viền đen KHÔNG tính — CHỈ cho khung đã xác nhận là logo đè chữ (user cho đè chữ 15/10; chữ đè logo từng chặn cả khung
    logo thật — v05 k886, test_2 k124–k128). Khung chưa xác nhận vẫn tính chữ: đó là lớp chặn phụ đề dự phòng."""
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
    la = (du > NET_LA_THONG_CAO) & (np.abs(vung - np.median(vung)) > NET_LA_LECH)
    if bo_chu:
        la &= ~mat_na_chu(g[y0:y1, x0:x1])
    return float(la.mean())


def cong_net_la(track: list[dict], ti_le: dict[int, float]) -> bool:
    """Chặn khung có nét lạ vượt ngưỡng theo video. Trả True nếu nét lạ PHỔ BIẾN (trung vị > NET_LA_PHO_BIEN) ⇒ cờ cho member."""
    med = _chan_theo_video(track, ti_le, NET_LA_SAN, NET_LA_K_MAD, CHAN_NET, lambda e: e.get("ai"))  # khung AI: user cho đè vật
    return med is not None and med > NET_LA_PHO_BIEN


def cong_khop(track: list[dict], boxes: list[BoxMoi], can: int = CAN_KHOP) -> dict:
    """Vết cuối phải trùng box mồi ĐỘC LẬP: khớp = tâm lệch ≤ 0,5 × cạnh dài box mồi, xét ở khung box (±1).

    Bắt mẫu học từ mồi sai: mẫu sai tự nhất quán nên dò vẫn "chắc", chỉ đối chiếu ngoài mới lộ (Test 02: 5/5 vết sai lệch ≥2).
    Box mà vết không phủ tại đó tính `track_vang`, không tính lệch. Qua ⟺ khớp ≥ `can` và khớp > lệch."""
    by = {e["frame"]: e for e in track}
    khop = lech = vang = 0
    for b in boxes:
        e = next((by[f] for f in (b.khung, b.khung - 1, b.khung + 1) if by.get(f, {}).get("state") in DA_CHAC), None)
        if e is None:
            vang += 1
            continue
        cx, cy, canh = b.x + b.w / 2, b.y + b.h / 2, max(b.w, b.h)
        if abs(e["x"] + e["w"] / 2 - cx) <= 0.5 * canh and abs(e["y"] + e["h"] / 2 - cy) <= 0.5 * canh:
            khop += 1
        else:
            lech += 1
    return {"khop": khop, "lech": lech, "track_vang": vang, "qua_cong": khop >= can and khop > lech}


CHAN_RUN_LE = 3  # khung bị chặn lẻ loi (≤ 3 khung liền) = báo động giả: phụ đề thật nằm lại ≥ nửa giây
# Khung bị KIỂM HÌNH bác (`kiem_hinh.CHAN_HINH`) không thuộc diện gỡ: đó là chỗ không có logo (khung lấp sai chỗ, vết trượt), gỡ là
# dán logo lên nền trống (kiểm hình đã chừa đoạn ngắn ≤ 3 khung).
KHONG_GO = ("hidden_hinh",)
# Gỡ chặn THEO HÌNH (đo 14/10, agy KHÉP R4b): khung bị cổng TƯƠNG PHẢN hoặc VÀNH chặn mà hình khớp watermark (điểm ≥ sàn hình của
# vết) VÀ trong tấm nền không có nét lạ (phần dư sau trừ mẫu ≤ NET_LA_SAN, sàn TUYỆT ĐỐI — ngưỡng theo video bị kéo lên khi chữ nằm
# lâu trong box) ⇒ đó là watermark, không phải nội dung ⇒ che lại với tấm nền ép hẹp (box +PAD_CHAT, chỗ logo cũ đã che sẵn).
# Đo: khung bị tương phản chặn ở v01/v04/v05 có điểm trung vị 0,66–0,83, 91–100% ≥ sàn (logo trắng mờ trên nền TỐI, chênh 66–98);
# đối chứng α bị bác (chữ phụ đề thật đo theo mặt nạ logo có α THẤP hơn logo). Cổng PHỤ ĐỀ và NÉT LẠ không gỡ.
CO_THE_GO_THEO_HINH = (CHAN_TUONG_PHAN, CHAN_VANH)


def go_chan_theo_hinh(track: list[dict], net: dict[int, float], san: float | None) -> int:
    """Gỡ khung bị cổng tương phản / vành chặn khi hình khớp + không nét lạ (xem trên); khung gỡ gắn `go_hinh`. Trong một đoạn chặn
    bị gỡ MỘT PHẦN, khung còn lại gắn `giu_chan` để `go_chan_le` không gỡ ăn theo các mẩu ≤ 3 khung vừa bị cắt ra (chúng đã bị xét và
    trượt). Đoạn chặn không có khung nào được gỡ thì giữ nguyên hành vi cũ của `go_chan_le`. Trả số khung gỡ."""
    if san is None:
        return 0
    go, i, n = 0, 0, len(track)
    while i < n:
        if track[i].get("state") not in CO_THE_GO_THEO_HINH:
            i += 1
            continue
        j = i
        while j < n and track[j].get("state") in CO_THE_GO_THEO_HINH:
            j += 1
        dat = [e for e in track[i:j] if (e.get("quy_dao") or max(e.get("score") or -1.0, e.get("diem_xoa_chu") or -1.0) >= san)
               and net.get(e["frame"], 1.0) <= NET_LA_SAN]  # điểm sau xoá chữ: khung đè chữ bị cổng tương phản chặn vẫn gỡ được
        for e in dat:
            e["chan_cu"], e["state"], e["plate_pad"], e["go_hinh"] = e["state"], "detected", PAD_CHAT, True
        if dat:
            # Giữ chặn cả khung bị cổng KHÁC (phụ đề / nét lạ) liền kề trong cùng đoạn chặn: gỡ phần tương phản/vành không được cắt
            # chúng thành mẩu ≤ 3 khung cho go_chan_le gỡ ăn theo (đoạn chặn dài trước đó vẫn là chặn thật).
            a, b = i, j
            while a > 0 and str(track[a - 1].get("state", "")).startswith("hidden_"):
                a -= 1
            while b < n and str(track[b].get("state", "")).startswith("hidden_"):
                b += 1
            for e in track[a:b]:
                if not e.get("go_hinh"):
                    e["giu_chan"] = True
        go += len(dat)
        i = j
    return go


def go_chan_le(track: list[dict], toi_da: int | None = None) -> int:
    """Gỡ chặn cho đoạn khung bị cổng chặn NGẮN (≤ `toi_da` khung liền): trả về trạng thái trước khi chặn (detected nếu có điểm, filled
    nếu là khung lấp). Cổng theo khung có tỉ lệ báo giả đáng kể (nét lạ trên logo sạch, vành ngang trên dải sáng tĩnh); mỗi khung
    chặn oan là một khung LỘ watermark giữa hai khung đã che = nháy. Phụ đề/nội dung thật kéo dài ⇒ vẫn bị chặn. Trả số khung gỡ."""
    toi_da = CHAN_RUN_LE if toi_da is None else toi_da
    go, i, n = 0, 0, len(track)
    def chan(e: dict) -> bool:
        st = str(e.get("state", ""))
        return st.startswith("hidden_") and st not in KHONG_GO and not e.get("giu_chan") and "x" in e

    while i < n:
        if not chan(track[i]):
            i += 1
            continue
        j = i
        while j < n and chan(track[j]):
            j += 1
        # Cạnh là khung bị kiểm hình bác ⇒ đoạn ngắn này KHÔNG kẹp giữa hai khung đang che, không phải nháy: giữ chặn. (v05 k921:
        # khung lấp dời lên CHỮ "Learna AI" trong phụ đề, cổng phụ đề chặn đúng, hai bên là hidden_hinh ⇒ thành đoạn 1 khung ⇒ bị gỡ.)
        canh = [track[k].get("state") for k in (i - 1, j) if 0 <= k < n]
        if j - i <= toi_da and not any(st in KHONG_GO for st in canh):
            for e in track[i:j]:
                e["chan_cu"] = e["state"]
                e["state"] = "detected" if e.get("score") is not None else "filled"
                go += 1
        i = j
    return go


def khung_duoc_render(track: list[dict], qua_cong_khop: bool) -> list[dict]:
    """CỔNG CỨNG: khung detected + filled (đã lấp lỗ) của vết đã qua cổng khớp. Khung bị cổng khác chặn giữ nguyên watermark."""
    if not qua_cong_khop:
        return []
    return [e for e in track if e.get("state") in DA_CHAC]


def khung_con_watermark_khong_thay(track: list[dict]) -> list[dict]:
    """Khung vết còn watermark thật nhưng bị cổng chặn (không thay): nguồn tô lấp của khung KHÁC không được lấy từ đây."""
    return [e for e in track if str(e.get("state", "")).startswith("hidden_") and "x" in e]


def chuan_pad_vet(track: list[dict]) -> None:
    """Pad tấm nền CỐ ĐỊNH theo vết: ≥20% khung phủ cần pad hẹp (phụ đề sát) ⇒ cả vết dùng pad hẹp; ít hơn ⇒ pad rộng, chỉ các khung
    thật sự bị phụ đề sát mới hẹp (nội dung được bảo vệ trước, cố định pad sau)."""
    phu = [e for e in track if e.get("state") in DA_CHAC]
    hep = [e for e in phu if e.get("plate_pad") == PAD_CHAT]
    if phu and len(hep) >= 0.2 * len(phu):
        for e in phu:
            e["plate_pad"] = PAD_CHAT
