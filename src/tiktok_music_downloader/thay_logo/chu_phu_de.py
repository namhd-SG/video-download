"""Logo đi QUA CHỮ phụ đề: phân định logo thật nằm dưới chữ với chữ phụ đề giống logo (mồi chữ), và chấm hình không bị chữ làm nhiễu.

User chốt 15/10: được dán logo mới ĐÈ lên chữ (đè ít, khó thấy) — nhưng KHÔNG được dán vào chỗ không có logo. Đo v05 (Test 03_5):
phụ đề chứa đúng chữ "Learna AI" của logo ⇒ vết khoá nhầm vào chữ phụ đề đứng yên (k515 "know more", k834 "learn?", k944 "Learna AI,")
trong khi logo thật trôi ngay cạnh.

Phép phân định: XOÁ NÉT CHỮ (đặt thông cao = 0 ở điểm chữ trắng sát nền tối, giãn phủ viền + quầng lọc) rồi chấm lại mẫu tại box.
Chữ phụ đề bị xoá ⇒ điểm TỤT; logo mờ nằm dưới chữ mất nhiễu chữ ⇒ điểm GIỮ hoặc TĂNG. Đo 15/10 (`ti_le_xoa_chu` = sau / trước):
mồi chữ v05 ×3, v13 "Tyler.", v17 "revisaras" 0,33–0,67 (ứng viên chữ toàn khung v05: 0,38–0,78); logo thật dưới chữ v01 ×3 1,00,
test_2 k55 1,53, v05 k870/k1010/k1117 1,61–2,19. Ngưỡng `TI_LE_GIU` nằm giữa hai nhóm.
Chỉ dùng trong dò CỤC BỘ (tại box / quanh quỹ đạo): tìm toàn khung trên ảnh xoá chữ bám mép băng chữ trắng (đo thu2 15/10).
"""
from __future__ import annotations

import cv2
import numpy as np

from .dinh_vi import CUA_SO, SIGMA, _hp, ti_le_phu_de
from .nguon_khung import NguonKhung

CHU_SANG, CHU_TOI = 215, 45  # cùng định nghĩa "chữ trắng viền đen" của dinh_vi.ti_le_phu_de
GIAN_CHU = 7  # giãn mặt nạ: phủ viền đen + quầng thông cao σ=2 quanh nét chữ
TI_LE_GIU = 0.9  # điểm sau xoá chữ ≥ 0,9 × điểm trước ⇒ hình logo không dựa vào nét chữ ⇒ logo thật
PAD_GAN_CHU, NGUONG_GAN_CHU = 4, 0.03  # box ±4 px có > 3% điểm chữ ⇒ khung "gần chữ" (= tấm nền chồng phụ đề, cong.PAD_TAM_NEN)
VANH_RONG = 0.8  # dải hai bên box, cùng bề rộng dải của cổng vành ngang (cong.VANH_RONG — không import kẻo vòng)
MOI_DUNG_PX = 1.5  # box dịch ≤ chừng này px/khung ⇒ đứng yên
MOI_HO_TOI_DA = 3  # khung detected cách nhau ≤ 3 khung vẫn tính liền một đoạn đứng yên
MOI_TRUOT_TOI_DA = 6 * MOI_DUNG_PX  # cả đoạn lệch đầu đoạn ≤ chừng này: logo trôi chậm đều không gộp vào đoạn mồi đứng yên kế nó
MOI_DAI = (4, 90)  # độ dài (khung) đoạn đứng yên được xét là mồi chữ: mồi chữ = một câu phụ đề (≤ 3 s); logo tĩnh thật dài hơn nhiều


def mat_na_chu(g: np.ndarray) -> np.ndarray:
    """Điểm ảnh thuộc chữ phụ đề trắng viền đen (đã giãn) trên ảnh xám gốc."""
    toi = cv2.dilate((g < CHU_TOI).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return cv2.dilate(((g > CHU_SANG) & toi).astype(np.uint8), np.ones((GIAN_CHU, GIAN_CHU), np.uint8)) > 0


def thong_cao_xoa_chu(g: np.ndarray, sigma: float = SIGMA) -> np.ndarray:
    """Ảnh thông cao với điểm chữ phụ đề đặt 0 (trung tính với TM_CCOEFF_NORMED, không sinh mép giả như thay bằng median)."""
    gf = _hp(g, sigma)
    gf[mat_na_chu(g)] = 0.0
    return gf


def chu_trong_tam_nen(g: np.ndarray, e: dict) -> bool:
    """Chữ phụ đề chồng tấm nền (box ±4) — điều kiện HẸP cho các phép HẠ khung (bác mồi chữ, chấm lại khung hụt): vùng rộng hơn coi
    cả viền sáng của icon tĩnh trên nền tối là chữ ⇒ gỡ nhầm logo thật (đo kq11: v04 lộ 14,9→17,2%, test icon đặc mất vết)."""
    return ti_le_phu_de(g, e["x"], e["y"], e["w"], e["h"], PAD_GAN_CHU) > NGUONG_GAN_CHU


def gan_chu(g: np.ndarray, e: dict) -> bool:
    """`chu_trong_tam_nen` HOẶC chữ ở dải hai bên box (vùng cổng vành ngang soi: ±0,8 bề rộng, cao box ± h/4) — chỉ dùng để quyết CHO
    ĐÈ CHỮ (vẫn phải qua chấm hình). test_2 k84–k128: logo rõ nằm CẠNH dòng chữ, trong box không có chữ, cổng vành vẫn chặn."""
    if chu_trong_tam_nen(g, e):
        return True
    H, W = g.shape
    rw = int(VANH_RONG * e["w"])
    y0, y1 = max(0, e["y"] - e["h"] // 4), min(H, e["y"] + e["h"] + e["h"] // 4)
    x0, x1 = max(0, e["x"] - rw), min(W, e["x"] + e["w"] + rw)
    return y1 > y0 and x1 > x0 and float(mat_na_chu(g[y0:y1, x0:x1]).mean()) > NGUONG_GAN_CHU


def diem_box(gf: np.ndarray, mau_u8: np.ndarray, e: dict) -> float:
    """Điểm khớp lớn nhất của mẫu (đổi cỡ về box) trong box ±CUA_SO trên ảnh thông cao `gf`; không dò được ⇒ −1."""
    H, W = gf.shape
    x, y, w, h = e["x"], e["y"], e["w"], e["h"]
    if w < 4 or h < 4:
        return -1.0
    t = _hp(cv2.resize(mau_u8, (w, h), interpolation=cv2.INTER_LINEAR), SIGMA)
    x0, y0, x1, y1 = max(0, x - CUA_SO), max(0, y - CUA_SO), min(W, x + w + CUA_SO), min(H, y + h + CUA_SO)
    if x1 - x0 < w or y1 - y0 < h or float(t.std()) < 1e-3:
        return -1.0
    return float(cv2.matchTemplate(gf[y0:y1, x0:x1], t, cv2.TM_CCOEFF_NORMED).max())


def cham_qua_chu(g: np.ndarray, mau_u8: np.ndarray, e: dict) -> tuple[float, float]:
    """(điểm trước, điểm sau xoá chữ) tại box."""
    return diem_box(_hp(g, SIGMA), mau_u8, e), diem_box(thong_cao_xoa_chu(g), mau_u8, e)


def la_logo_qua_chu(truoc: float, sau: float) -> bool:
    return sau > 0 and sau >= TI_LE_GIU * max(truoc, 0.0)


def _doan_dung_yen(det: dict[int, dict]) -> list[list[int]]:
    ks = sorted(det)
    out, cur = [], []
    for a, b in zip(ks, ks[1:]):
        (ax, ay), (bx, by) = (det[a]["x"], det[a]["y"]), (det[b]["x"], det[b]["y"])
        d0 = det[cur[0]] if cur else det[a]
        if (b - a <= MOI_HO_TOI_DA and np.hypot(bx - ax, by - ay) <= MOI_DUNG_PX * (b - a)
                and np.hypot(bx - d0["x"], by - d0["y"]) <= MOI_TRUOT_TOI_DA):
            cur = cur or [a]
            cur.append(b)
        else:
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [d for d in out if MOI_DAI[0] <= d[-1] - d[0] + 1 <= MOI_DAI[1]]


def bo_moi_chu(nguon: NguonKhung, det: dict[int, dict], mau: np.ndarray) -> tuple[dict[int, dict], int]:
    """Gỡ khỏi `det` các đoạn box ĐỨNG YÊN nằm GẦN CHỮ mà điểm tụt khi xoá chữ (trung vị `la_logo_qua_chu` sai) = vết đang khoá vào chữ
    phụ đề. Đoạn bị gỡ thành lỗ mất dấu ⇒ bám hai chiều / lấp lỗ phía sau xử lý như mọi lỗ. Logo tĩnh thật dưới chữ (v01) giữ điểm ⇒
    không bị gỡ. Trả (det mới, số khung gỡ)."""
    doan = _doan_dung_yen(det)
    if not doan:
        return det, 0
    can = {k for d in doan for k in d}
    mau_u8 = np.clip(mau, 0, 255).astype(np.uint8)
    cham: dict[int, tuple[float, float]] = {}
    cuoi = max(can)
    for i, g in enumerate(nguon.doc_tuan_tu()):
        if i in can and chu_trong_tam_nen(g, det[i]):
            cham[i] = cham_qua_chu(g, mau_u8, det[i])
        if i >= cuoi:
            break
    out, bo = dict(det), 0
    for d in doan:
        k_chu = [k for k in d if k in cham]  # chỉ khung có chữ trong tấm nền bị xét/gỡ — khung sạch cùng đoạn là logo thật, giữ
        if len(k_chu) < MOI_DAI[0]:
            continue
        if not la_logo_qua_chu(float(np.median([cham[k][0] for k in k_chu])), float(np.median([cham[k][1] for k in k_chu]))):
            for k in k_chu:
                out.pop(k, None)
            bo += len(k_chu)
    return out, bo
