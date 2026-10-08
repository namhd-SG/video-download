"""Đổi box agy (thang 0–1000) sang pixel: box sai khuôn bị BỎ, không đoán."""
import pytest

pytest.importorskip("cv2", reason="lõi thay logo cần opencv-python-headless (chưa có trong deps chính tới bước tích hợp)")

from tiktok_music_downloader.thay_logo.box_moi import BoxMoi, box_tu_box_2d  # noqa: E402


def test_box_2d_hop_le_doi_sang_pixel_theo_kho_that():
    b = box_tu_box_2d([342, 716, 361, 787], khung=12, rong=720, cao=1280)
    assert b == BoxMoi(12, 515, 437, 51, 24, "agy")


@pytest.mark.parametrize("box", [None, [], [1, 2, 3], [10, 10, 5, 50], [0, 0, 0, 0], [-1, 0, 10, 10], [0, 0, 10, 1001],
                                 ["a", 0, 10, 10]])
def test_box_2d_sai_khuon_bi_bo(box):
    assert box_tu_box_2d(box, khung=0, rong=720, cao=1280) is None


def test_box_qua_nho_duoc_nang_toi_4px():
    b = box_tu_box_2d([0, 0, 1, 1], khung=0, rong=360, cao=640)
    assert (b.w, b.h) == (4, 4)
