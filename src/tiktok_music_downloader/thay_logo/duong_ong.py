"""Đường ống một video: box mồi → gom vết → mỗi vết: mồi đồng thuận → mẫu sạch → C + tự học 2 vòng → C cuối → các cổng.

Chép trình tự `p1a_t2_pipeline_v2.py` (lượt Test 02 v2), thay cổng khớp bằng v2 (N=3, lệch=0) và thêm cổng vành ngang
(ĐP-1488 (b)). Kết quả mỗi vết mang trạng thái `render` hoặc `cho_nguoi` + số đếm để người tạo job duyệt.
Không render, không gọi agy — box mồi do người gọi đưa vào (agy học mẫu hoặc kéo tay).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import cong
from .box_moi import MIN_BOX, BoxMoi, chon_moi_dong_thuan, gom_vet
from .dinh_vi import dinh_vi
from .mau import dung_mau_sach, mat_na_va_tuong_phan, tu_hoc_mau
from .nguon_khung import NguonKhung

SO_VONG_TU_HOC = 2


@dataclass
class KetQuaVet:
    trang_thai: str  # "render" | "cho_nguoi" | "loi_mau"
    box_cum: int
    ncc_moi: float = 0.0
    track: list[dict] = field(default_factory=list)
    khung_render: list[dict] = field(default_factory=list)
    khop: dict = field(default_factory=dict)
    tu_hoc_bi_tu_choi: int = 0  # số vòng tự học mà mẫu mới lệch mẫu cũ ⇒ giữ mẫu cũ (cờ cho người duyệt)
    tuong_phan_mau: float = 0.0
    dem_chan: dict = field(default_factory=dict)

    @property
    def pct_chac(self) -> float:
        return round(100 * len(self.khung_render) / max(1, len(self.track)), 1)


@dataclass
class KetQuaVideo:
    vet: list[KetQuaVet]
    so_box: int
    so_cum: int

    @property
    def trang_thai(self) -> str:
        """Video có ≥1 vết render ⇒ render; không thì chờ người (kéo khung tay)."""
        return "render" if any(v.trang_thai == "render" for v in self.vet) else "cho_nguoi"


def _ap_cong_khung(nguon: NguonKhung, track: list[dict], mask: np.ndarray, nguong: float,
                   ti_le_vanh: dict[int, float] | None) -> None:
    """Một lượt đọc tuần tự: cổng phụ đề + tương phản trên mỗi khung chắc; đo vành ngang nếu được yêu cầu."""
    by = {e["frame"]: e for e in track if e.get("state") == "detected"}
    for i, g in enumerate(nguon.doc_tuan_tu()):
        e = by.get(i)
        if e is None:
            continue
        cong.cong_phu_de(g, e)
        if e["state"] == "detected":
            cong.cong_tuong_phan(g, e, mask, nguong)
        if ti_le_vanh is not None and e["state"] == "detected":
            ti_le_vanh[i] = cong.ti_le_vanh(g, e)


def xu_ly_vet(nguon: NguonKhung, cum: list[BoxMoi]) -> KetQuaVet:
    moi, ncc = chon_moi_dong_thuan(nguon, cum)
    mau = dung_mau_sach(nguon, moi, cum)
    if mau is None:
        return KetQuaVet("loi_mau", len(cum), ncc)
    tu_choi = 0
    for _ in range(SO_VONG_TU_HOC):
        track = dinh_vi(nguon, mau)
        mask, tcon = mat_na_va_tuong_phan(mau)
        # Plan §5c.1: crop tự học chỉ lấy khung đã qua cổng, kẻo mẫu trôi sang chữ nội dung.
        _ap_cong_khung(nguon, track, mask, cong.nguong_tuong_phan(tcon), None)
        mau, nhan = tu_hoc_mau(nguon, track, mau)
        tu_choi += 0 if nhan else 1
    kq = ap_moi_cong(nguon, dinh_vi(nguon, mau), mau, cum)
    kq.ncc_moi, kq.tu_hoc_bi_tu_choi = round(ncc, 3), tu_choi
    return kq


def ap_moi_cong(nguon: NguonKhung, track: list[dict], mau: np.ndarray, cum: list[BoxMoi]) -> KetQuaVet:
    """Mọi cổng trên track cuối của một vết, theo đúng thứ tự; trả kết quả vết (sửa `track` tại chỗ)."""
    mask, tcon = mat_na_va_tuong_phan(mau)
    vanh: dict[int, float] = {}
    _ap_cong_khung(nguon, track, mask, cong.nguong_tuong_phan(tcon), vanh)
    cong.cong_vanh_ngang(track, vanh)
    khop = cong.cong_khop(track, cum)
    render = cong.khung_duoc_render(track, khop["qua_cong"])
    dem = {s: sum(1 for e in track if e.get("state") == s)
           for s in (cong.CHAN_PHU_DE, cong.CHAN_TUONG_PHAN, cong.CHAN_VANH)}
    return KetQuaVet("render" if render else "cho_nguoi", len(cum), track=track, khung_render=render, khop=khop,
                     tuong_phan_mau=round(tcon, 1), dem_chan=dem)


def xu_ly_video(nguon: NguonKhung, boxes: list[BoxMoi]) -> KetQuaVideo:
    """Mỗi cụm đủ MIN_BOX box là một watermark riêng (video có thể mang 2 thương hiệu). Không cụm nào đủ ⇒ chờ người."""
    cum = gom_vet(boxes)
    vet = [xu_ly_vet(nguon, cl) for cl in cum if len(cl) >= MIN_BOX]
    return KetQuaVideo(vet, len(boxes), len(cum))
