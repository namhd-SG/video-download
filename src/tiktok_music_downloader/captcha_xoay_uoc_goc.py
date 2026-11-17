"""Ước góc cho captcha XOAY của TikTok ("Drag the slider to fit the puzzle", lớp `captcha-verify-container`).

Cấu trúc đo 17/11 (M5): hai `<img alt="Captcha">` dạng data URI webp — vòng NGOÀI (347×347 gốc) và hình tròn
TRONG (211×211 gốc), cùng tỉ lệ điểm ảnh (hiển thị 210 / 128 px). Kéo nút `#captcha_slide_button` đi `d` px
⇒ vòng ngoài `rotate(-θ)`, hình trong `rotate(+θ)`, θ = 180·d / (rãnh − nút) (đo: rãnh 348, nút 64 ⇒
0,6338°/px). Lệch tương đối giữa hai ảnh = 2θ ∈ [0°, 360°].

Cách ước (thuần tính toán, không mạng): lấy vành màu NGAY TRONG mép hình tròn trong và vành NGAY NGOÀI mép đó
trên vòng ngoài, mẫu theo góc (chiều kim đồng hồ trên màn). Hiển thị: ngoài tại góc φ là O(φ+θ), trong là
I(φ−θ) ⇒ khớp khi O(ψ) ≈ I(ψ − 2θ). Tìm s = 2θ cực tiểu sai khác vòng (tương quan vòng bằng FFT trên cả
màu lẫn gradient theo góc). Ý tưởng so mép vành là cách phổ biến của các bộ giải mã nguồn mở cho captcha xoay;
mã này viết lại từ đầu, không chép mã ai.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

SO_MAU_GOC = 720  # 0,5° mỗi mẫu


@dataclass(frozen=True)
class KetQuaUocGoc:
    lech_do: float      # s = 2θ, độ, [0, 360)
    theta_do: float     # góc mỗi ảnh xoay = s / 2
    do_tin: float       # (sai khác trung bình − sai khác nhỏ nhất) / độ lệch chuẩn — càng lớn càng chắc


def _doc(anh: bytes) -> np.ndarray:
    im = cv2.imdecode(np.frombuffer(anh, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        raise ValueError("không giải mã được ảnh captcha")
    return im.astype(np.float32)


def _vanh(im: np.ndarray, tam: tuple[float, float], ban_kinh: float) -> np.ndarray:
    """Màu (SO_MAU_GOC × 3) dọc vòng tròn bán kính `ban_kinh`, góc tăng theo chiều kim đồng hồ trên màn
    (trục y ảnh hướng xuống)."""
    goc = np.linspace(0, 2 * np.pi, SO_MAU_GOC, endpoint=False)
    mx = (tam[0] + ban_kinh * np.cos(goc)).astype(np.float32).reshape(1, -1)
    my = (tam[1] + ban_kinh * np.sin(goc)).astype(np.float32).reshape(1, -1)
    return cv2.remap(im, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[0]


def _vanh_day(im, tam, r_tu, r_den, buoc=1.0) -> np.ndarray:
    """Trung bình vài vành liền nhau để bớt nhiễu nén."""
    rs = np.arange(r_tu, r_den + 1e-6, buoc)
    return np.mean([_vanh(im, tam, r) for r in rs], axis=0)


def _dac_trung(v: np.ndarray) -> np.ndarray:
    """Màu đã chuẩn hoá + gradient theo góc (mép cắt ngang vành là thứ khớp rõ nhất)."""
    mau = (v - v.mean(axis=0)) / (v.std(axis=0) + 1e-6)
    grad = np.roll(v, -1, axis=0) - np.roll(v, 1, axis=0)
    grad = grad / (grad.std(axis=0) + 1e-6)
    return np.concatenate([mau, grad], axis=1)


def uoc_goc(anh_ngoai: bytes, anh_trong: bytes, le: float = 3.0, day: float = 4.0) -> KetQuaUocGoc:
    """Ước lệch góc s = 2θ để hình trong khớp vòng ngoài. `le`: khoảng px tránh đường viền/anti-alias ở mép;
    `day`: độ dày vành lấy mẫu."""
    ngoai, trong = _doc(anh_ngoai), _doc(anh_trong)
    hn, wn = ngoai.shape[:2]
    ht, wt = trong.shape[:2]
    r = min(ht, wt) / 2.0
    tam_n = ((wn - 1) / 2.0, (hn - 1) / 2.0)
    tam_t = ((wt - 1) / 2.0, (ht - 1) / 2.0)
    I = _dac_trung(_vanh_day(trong, tam_t, r - le - day, r - le))
    O = _dac_trung(_vanh_day(ngoai, tam_n, r + le, r + le + day))
    # sai khác(s) = Σ|O(ψ) − I(ψ − s)|² = hằng − 2·Σ O(ψ)·I(ψ − s) ⇒ cực đại tương quan vòng.
    tq = np.real(np.fft.ifft(np.fft.fft(O, axis=0) * np.conj(np.fft.fft(I, axis=0)), axis=0)).sum(axis=1)
    k = int(np.argmax(tq))
    # Nội suy parabol quanh đỉnh cho phần lẻ của mẫu.
    a, b, c = tq[(k - 1) % SO_MAU_GOC], tq[k], tq[(k + 1) % SO_MAU_GOC]
    mau = a - 2 * b + c
    dk = 0.5 * (a - c) / mau if mau != 0 else 0.0
    s = float(((k + dk) * 360.0 / SO_MAU_GOC) % 360.0)  # float thường: float32 numpy không JSON hoá được
    do_tin = float((tq.max() - tq.mean()) / (tq.std() + 1e-9))
    return KetQuaUocGoc(lech_do=s, theta_do=s / 2.0, do_tin=do_tin)


def khoang_keo_px(theta_do: float, rong_ray: float, rong_nut: float) -> float:
    """θ (độ mỗi ảnh xoay) → px nút phải đi: d = θ·(rãnh − nút)/180."""
    return theta_do * (rong_ray - rong_nut) / 180.0
