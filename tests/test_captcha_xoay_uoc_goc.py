"""Bộ ước góc captcha xoay (`src/tiktok_music_downloader/captcha_xoay_uoc_goc.py`) trên ảnh TỔNG HỢP: cắt hình tròn giữa một ảnh có
vân, xoay theo góc biết trước như trang làm (CSS clockwise), kiểm bộ ước tìm lại đúng lệch. Không mạng."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from tiktok_music_downloader.captcha_xoay_uoc_goc import khoang_keo_px, uoc_goc

N_NGOAI, N_TRONG = 347, 211


def _anh_goc(hat: int) -> np.ndarray:
    """Ảnh có vân đủ phân biệt góc: nhiễu mịn + vài khối màu lớn."""
    rng = np.random.default_rng(hat)
    nho = rng.integers(0, 255, (12, 12, 3), dtype=np.uint8)
    im = cv2.resize(nho, (N_NGOAI, N_NGOAI), interpolation=cv2.INTER_CUBIC)
    for _ in range(6):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        p = tuple(int(v) for v in rng.integers(0, N_NGOAI, 2))
        cv2.circle(im, p, int(rng.integers(15, 60)), c, -1)
    return im


def _xoay_css(im: np.ndarray, do_css: float) -> np.ndarray:
    """CSS `rotate(+a)` = theo chiều kim đồng hồ; cv2 góc dương = ngược chiều ⇒ đổi dấu."""
    h, w = im.shape[:2]
    m = cv2.getRotationMatrix2D(((w - 1) / 2, (h - 1) / 2), -do_css, 1.0)
    return cv2.warpAffine(im, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _de_bai(hat: int, lech_css: float) -> tuple[bytes, bytes]:
    """Tạo cặp ảnh như captcha: ảnh đầy đủ đã khớp, hình trong bị xoay lệch `lech_css` so với vị trí đúng
    (trang hiển thị lệch này khi θ=0). Người giải cần lệch s = 2θ sao cho I(ψ − s) khớp O(ψ)."""
    full = _anh_goc(hat)
    o = (N_NGOAI - N_TRONG) // 2
    trong = full[o:o + N_TRONG, o:o + N_TRONG].copy()
    trong = _xoay_css(trong, -lech_css)
    ngoai = full.copy()
    m = np.zeros(full.shape[:2], np.uint8)
    cv2.circle(m, (N_NGOAI // 2, N_NGOAI // 2), N_TRONG // 2, 255, -1)
    ngoai[m > 0] = 255  # lỗ trắng giữa vòng ngoài như ảnh thật
    return cv2.imencode(".png", ngoai)[1].tobytes(), cv2.imencode(".webp", trong)[1].tobytes()


def _sai_goc(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


@pytest.mark.parametrize("hat,lech", [(1, 37.0), (2, 111.5), (3, 200.0), (4, 299.0), (5, 5.0), (6, 355.0)])
def test_tim_lai_lech_biet_truoc_sai_khong_qua_3_do(hat, lech):
    """3° lệch ≈ 2,4 px nút. Dung sai thật của TikTok CHƯA đo (cần thử giải sống) — siết lại khi có số."""
    ngoai, trong = _de_bai(hat, lech)
    kq = uoc_goc(ngoai, trong)
    assert _sai_goc(kq.lech_do, lech) <= 3.0, (kq, lech)
    assert kq.theta_do == pytest.approx(kq.lech_do / 2)
    assert isinstance(kq.lech_do, float) and not isinstance(kq.lech_do, np.floating), \
        "Playwright không JSON hoá được float32 numpy"


def test_xoay_them_hinh_trong_thi_lech_doi_dung_bang_ay():
    ngoai, trong = _de_bai(7, 150.0)
    goc = uoc_goc(ngoai, trong).lech_do
    im = cv2.imdecode(np.frombuffer(trong, np.uint8), cv2.IMREAD_COLOR)
    trong2 = cv2.imencode(".png", _xoay_css(im, 60.0))[1].tobytes()
    assert _sai_goc(uoc_goc(ngoai, trong2).lech_do, goc - 60.0) <= 1.5


def test_anh_hong_bao_loi_ro():
    with pytest.raises(ValueError, match="không giải mã được"):
        uoc_goc(b"khong-phai-anh", b"x")


def test_khoang_keo_khop_so_do_tren_trang_that():
    """Đo 17/11: rãnh 348, nút 64; nút đi 150 px ⇒ θ = 95,0704°."""
    assert khoang_keo_px(95.0704, 348, 64) == pytest.approx(150.0, abs=0.01)
    assert khoang_keo_px(180.0, 348, 64) == pytest.approx(284.0)
