"""Logo qua chữ phụ đề: phân định logo thật dưới chữ với chữ phụ đề giống logo (mồi chữ) bằng điểm trước/sau xoá nét chữ."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from thay_logo_tong_hop import _dan, _mat_na_chu, _nen
from tiktok_music_downloader.thay_logo import chu_phu_de
from tiktok_music_downloader.thay_logo.nguon_khung import NguonKhungMang

W_LOGO = _mat_na_chu("WMARK", 0.9, 2)
H, W = W_LOGO.shape
X, Y = 120, 400


def _mau() -> np.ndarray:
    """Mẫu sạch: chính watermark (trắng bán trong suốt) trên nền xám phẳng."""
    g = np.full((H, W), 90.0, np.float32)
    _dan(g, W_LOGO, 0, 0, 255.0, 0.45)
    return g


def _khung(i: int, *, logo: bool, moi_chu: bool = False, chu_de: bool = False) -> np.ndarray:
    """`logo` = watermark thật bán trong suốt tại (X, Y). `moi_chu` = phụ đề TRẮNG VIỀN ĐEN có đúng chữ của logo tại (X, Y) (chữ phụ đề
    giống logo — v05 "Learna AI,"). `chu_de` = một dòng phụ đề trắng viền đen cắt NGANG nửa dưới logo (logo thật bị chữ đè một phần)."""
    g = _nen(np.random.default_rng(i), i)
    if logo:
        _dan(g, W_LOGO, X, Y, 255.0, 0.45)
    if moi_chu:
        _dan(g, cv2.dilate(W_LOGO, np.ones((5, 5), np.uint8)), X, Y, 0.0, 1.0)
        _dan(g, W_LOGO, X, Y, 255.0, 1.0)
    if chu_de:
        dong = _mat_na_chu("ab", 0.6, 2)
        for sx in range(X - 30, X + W + 30, dong.shape[1]):
            _dan(g, cv2.dilate(dong, np.ones((5, 5), np.uint8)), sx, Y + H // 2, 0.0, 1.0)
            _dan(g, dong, sx, Y + H // 2, 255.0, 1.0)
    return np.clip(g, 0, 255).astype(np.uint8)


def _e(i: int) -> dict:
    return {"frame": i, "x": X, "y": Y, "w": W, "h": H, "score": 0.5, "state": "detected"}


def test_mat_na_chu_bat_chu_vien_den_khong_bat_watermark_mo():
    assert chu_phu_de.mat_na_chu(_khung(0, logo=False, moi_chu=True))[Y:Y + H, X:X + W].mean() > 0.2
    assert chu_phu_de.mat_na_chu(_khung(0, logo=True))[Y:Y + H, X:X + W].mean() == 0.0


def test_moi_chu_tut_diem_khi_xoa_chu_logo_that_duoi_chu_khong_tut():
    mau = np.clip(_mau(), 0, 255).astype(np.uint8)
    truoc, sau = chu_phu_de.cham_qua_chu(_khung(1, logo=False, moi_chu=True), mau, _e(1))
    assert truoc > 0.3 and not chu_phu_de.la_logo_qua_chu(truoc, sau)
    g = _khung(1, logo=True, chu_de=True)
    assert chu_phu_de.gan_chu(g, _e(1))
    truoc, sau = chu_phu_de.cham_qua_chu(g, mau, _e(1))
    assert chu_phu_de.la_logo_qua_chu(truoc, sau)


def _det(ks) -> dict[int, dict]:
    return {k: _e(k) for k in ks}


def test_bo_moi_chu_go_doan_khoa_chu_giu_logo_that_dung_yen_duoi_chu():
    khung = [_khung(i, logo=False, moi_chu=10 <= i < 30) if i < 40 else _khung(i, logo=True, chu_de=True) for i in range(70)]
    det = _det(list(range(10, 30)) + list(range(40, 70)))
    out, bo = chu_phu_de.bo_moi_chu(NguonKhungMang(khung), det, _mau())
    assert bo == 20 and not set(range(10, 30)) & set(out)
    assert set(range(40, 70)) <= set(out)  # logo thật tĩnh dưới chữ (kiểu v01) không bị gỡ


def test_bo_moi_chu_khong_dung_toi_doan_xa_chu_hoac_qua_dai():
    khung = [_khung(i, logo=True) for i in range(130)]
    det = _det(range(130))  # logo tĩnh 130 khung (> MOI_DAI), không gần chữ
    out, bo = chu_phu_de.bo_moi_chu(NguonKhungMang(khung), det, _mau())
    assert bo == 0 and out == det


@pytest.mark.parametrize("dot_bien", ["nguong_0", "khong_xoa_chu"])
def test_dot_bien_thi_moi_chu_lot(monkeypatch, dot_bien):
    """Phép thử có sức phân định: bỏ ngưỡng tỉ lệ hoặc bỏ bước xoá chữ ⇒ mồi chữ không bị gỡ."""
    if dot_bien == "nguong_0":
        monkeypatch.setattr(chu_phu_de, "TI_LE_GIU", 0.0)
    else:
        monkeypatch.setattr(chu_phu_de, "thong_cao_xoa_chu", lambda g, sigma=chu_phu_de.SIGMA: chu_phu_de._hp(g, sigma))
    khung = [_khung(i, logo=False, moi_chu=True) for i in range(20)]
    _, bo = chu_phu_de.bo_moi_chu(NguonKhungMang(khung), _det(range(20)), _mau())
    assert bo == 0


def test_bo_moi_chu_chi_go_khung_co_chu_giu_khung_logo_sach_cung_doan():
    """Đoạn đứng yên: 25 khung logo thật sạch rồi 5 khung chữ giống logo cùng chỗ ⇒ chỉ gỡ 5 khung chữ (agy R3b PB1)."""
    khung = [_khung(i, logo=i < 25, moi_chu=i >= 25) for i in range(30)]
    out, bo = chu_phu_de.bo_moi_chu(NguonKhungMang(khung), _det(range(30)), _mau())
    assert bo == 5 and set(range(25)) <= set(out) and not set(range(25, 30)) & set(out)
