"""Khử trùng ứng viên theo video_id rồi dHash ảnh bìa. Ảnh tổng hợp bằng Pillow, không mạng."""
from __future__ import annotations

from PIL import Image, ImageDraw

from tiktok_music_downloader.tim_trend.khu_trung import MucKhuTrung, dhash, hamming, khu_trung


def _anh(tmp_path, ten, ve, co=(360, 640), chat_luong=95):
    img = Image.new("RGB", (240, 320), "white")
    ve(ImageDraw.Draw(img))
    p = tmp_path / ten
    img.resize(co).save(p, quality=chat_luong)
    return p


def _hinh_a(d):
    d.rectangle([20, 20, 120, 300], fill="black")
    d.ellipse([150, 40, 220, 110], fill="gray")


def _hinh_b(d):
    d.rectangle([140, 200, 230, 310], fill="black")
    d.rectangle([10, 10, 60, 60], fill="gray")


def test_cung_anh_nen_lai_khac_co_van_trung(tmp_path):
    a = _anh(tmp_path, "a.jpg", _hinh_a)
    a2 = _anh(tmp_path, "a2.jpg", _hinh_a, co=(270, 480), chat_luong=60)
    assert hamming(dhash(a), dhash(a2)) <= 4


def test_khac_anh_khong_trung(tmp_path):
    assert hamming(dhash(_anh(tmp_path, "a.jpg", _hinh_a)), dhash(_anh(tmp_path, "b.jpg", _hinh_b))) > 4


def test_khu_trung_id_roi_anh(tmp_path):
    a = _anh(tmp_path, "a.jpg", _hinh_a)
    a_reup = _anh(tmp_path, "a_reup.jpg", _hinh_a, co=(300, 533), chat_luong=70)
    b = _anh(tmp_path, "b.jpg", _hinh_b)
    giu, bo = khu_trung([MucKhuTrung("1", a), MucKhuTrung("1", a), MucKhuTrung("2", a_reup),
                         MucKhuTrung("3", b), MucKhuTrung("4", None)])
    assert [m.video_id for m in giu] == ["1", "3", "4"]
    assert bo == {"1": "trung video_id", "2": "trung anh bia voi 1"}
