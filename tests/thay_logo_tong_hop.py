"""Video TỔNG HỢP có ground truth cho test lõi thay logo (ĐP-1489: không commit crop video bên thứ ba).

Mỗi khung: nền gradient trôi + nhiễu (đổi theo khung, để trung vị triệt nền như video thật) ⇒ dán watermark chữ trắng bán trong
suốt trôi chậm. Tuỳ chọn thêm phụ đề trắng viền đen, phụ đề trắng bóng mờ tràn ngang, hoặc icon đặc tương phản cao.
Không đọc file nào ngoài repo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from tiktok_music_downloader.thay_logo.box_moi import BoxMoi
from tiktok_music_downloader.thay_logo.nguon_khung import NguonKhungMang

RONG, CAO = 360, 640
FONT = cv2.FONT_HERSHEY_SIMPLEX


@dataclass
class ClipTongHop:
    nguon: NguonKhungMang
    hop_that: list[tuple[int, int, int, int]]  # box watermark thật mỗi khung (x, y, w, h)
    khung_phu_de: set[int] = field(default_factory=set)

    def box_moi(self, khung=(5, 15, 25, 35, 45, 55), nguon="agy") -> list[BoxMoi]:
        return [BoxMoi(i, *self.hop_that[i], nguon=nguon) for i in khung]


def _nen(rng: np.random.Generator, i: int) -> np.ndarray:
    yy, xx = np.mgrid[0:CAO, 0:RONG].astype(np.float32)
    g = 70 + 50 * np.sin((xx + 7 * i) / 41.0) * np.cos((yy - 5 * i) / 57.0) + 0.06 * yy
    g += rng.normal(0, 6, g.shape)
    return np.clip(g, 0, 255).astype(np.float32)


def _mat_na_chu(chu: str, scale: float, day: int) -> np.ndarray:
    (tw, th), base = cv2.getTextSize(chu, FONT, scale, day)
    m = np.zeros((th + base + 4, tw + 4), np.uint8)
    cv2.putText(m, chu, (2, th + 2), FONT, scale, 255, day, cv2.LINE_AA)
    return m.astype(np.float32) / 255.0


def _dan(g: np.ndarray, m: np.ndarray, x: int, y: int, mau: float, alpha: float) -> None:
    h, w = m.shape
    vung = g[y:y + h, x:x + w]
    a = m[:vung.shape[0], :vung.shape[1]] * alpha
    vung[:] = (1 - a) * vung + a * mau


def tao_clip(n: int = 60, *, phu_de_vien_den: range | None = None, phu_de_bong_mo: range | None = None,
             icon_dac: bool = False, icon_nen: float = 220.0, icon_tam: float = 120.0, seed: int = 7) -> ClipTongHop:
    rng = np.random.default_rng(seed)
    if icon_dac:  # logo đặc tương phản cao (kiểu icon app góc cố định): ô màu `icon_nen` + chấm tròn `icon_tam`
        wm = np.zeros((40, 40), np.float32)
        wm[4:36, 4:36] = 1.0
        wm_sang = np.zeros_like(wm)
        cv2.circle(wm_sang, (20, 20), 9, 1.0, -1)
    else:
        wm = _mat_na_chu("WMARK", 0.9, 2)
    h, w = wm.shape
    sub = _mat_na_chu("Hello subtitle", 0.8, 2)
    khung, hop = [], []
    for i in range(n):
        g = _nen(rng, i)
        x, y = (300 - w, 30) if icon_dac else (60 + i, 420 + (i // 3))
        if icon_dac:
            _dan(g, wm, x, y, icon_nen, 1.0)
            _dan(g, wm_sang, x, y, icon_tam, 1.0)
        else:
            _dan(g, wm, x, y, 255.0, 0.45)
        hop.append((x, y, w, h))
        if phu_de_vien_den and i in phu_de_vien_den:  # chữ trắng viền đen phủ ngang qua box
            vien = cv2.dilate(sub, np.ones((5, 5), np.uint8))
            sx, sy = max(0, x - 40), y + h // 2 - sub.shape[0] // 2
            _dan(g, vien, sx, sy, 0.0, 1.0)
            _dan(g, sub, sx, sy, 255.0, 1.0)
        if phu_de_bong_mo and i in phu_de_bong_mo:  # chữ trắng có bóng mờ, KHÔNG viền đen <45, tràn hai bên box
            bong = cv2.GaussianBlur(sub, (0, 0), 3)
            sx, sy = max(0, x - 70), y + h // 2 - sub.shape[0] // 2
            _dan(g, bong, sx + 2, sy + 2, 60.0, 0.6)
            _dan(g, sub, sx, sy, 250.0, 1.0)
        khung.append(np.clip(g, 0, 255).astype(np.uint8))
    tap_pd = set(phu_de_vien_den or ()) | set(phu_de_bong_mo or ())
    return ClipTongHop(NguonKhungMang(khung), hop, tap_pd)


def tam_lech(e: dict, hop: tuple[int, int, int, int]) -> float:
    x, y, w, h = hop
    return float(np.hypot(e["x"] + e["w"] / 2 - (x + w / 2), e["y"] + e["h"] / 2 - (y + h / 2)))
