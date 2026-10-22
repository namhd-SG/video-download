"""Hạng khớp dạng tất định, trên trường agy đo thật ở GĐ1 (22/10). Không mạng, không agy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tiktok_music_downloader.tim_trend import cham
from tiktok_music_downloader.tim_trend.truong import tu_json

_FIX = Path(__file__).parent / "fixtures" / "tim_trend" / "truong-gd1.json"
TRUONG = {m["id"]: tu_json(m) for m in json.loads(_FIX.read_text())["items"]}


@pytest.fixture
def ck_collage():
    """Video mẫu 1 (`video test.mp4`): 7 bản sao cùng người mẫu, nền trắng."""
    return cham.chu_ky([TRUONG["ctrl-0"], TRUONG["ctrl-1"], TRUONG["ctrl-2"]])


@pytest.fixture
def ck_catwalk():
    """Video mẫu 2 (khác trend): 1 người mẫu catwalk trên sàn diễn."""
    return cham.chu_ky([TRUONG["s3-0"], TRUONG["s3-1"]])


def test_chu_ky_collage(ck_collage):
    assert (ck_collage.so_ban_sao, ck_collage.bac, ck_collage.chu_the, ck_collage.nen, ck_collage.la_luoi) == \
        (7, ">=3", "nguoi", "tron", False)


@pytest.mark.parametrize("id_, mong", [
    ("ctrl-1", "3"),   # đối chứng dương: khung của chính video mẫu
    ("s6-7", "3"),     # đồ đen, 7 dáng, nền trắng — user chấm đúng
    ("s7-0", "3"),
    ("s6-1", "3"),     # Ronaldo 6 dáng — user chấm đúng
    ("s7-1", "2A"),    # cùng dạng + chữ "Tutorial Pembuatan Gratis" — user chấm đúng
    ("s5-5", "1"),     # lưới 4 ô: xét lưới TRƯỚC bản sao (lỗi GĐ1)
    ("s1-7", "1"),     # 1 người
    ("s2-7", "1"),     # poster tutorial + nền khác: lệch 1 KÈM tutorial ⇒ 1, không lên 2B (ĐK2)
    ("s2-3", "2B"),    # 60 em bé nhân bản trong nhà: người thường gom nhóm người, chỉ lệch nền
    ("s3-4", "0"),     # chó: khác chủ thể ⇒ 0 trước mọi luật khác (ĐK2)
])
def test_hang_voi_chu_ky_collage(ck_collage, id_, mong):
    assert cham.hang(TRUONG[id_], ck_collage) == mong


@pytest.mark.parametrize("id_, mong", [
    ("s3-1", "3"),
    ("s3-2", "3"),     # catwalk ngoài công viên: nền chỉ phụ khi chữ ký 1 người + hành động đặc trưng (ĐK3)
    ("s3-3", "3"),
    ("s3-7", "3"),
    ("s5-2", "1"),     # 1 người ngồi tạo dáng, cùng nền trơn: hành động là cổng cứng
    ("s6-7", "1"),     # collage 7 dáng: KHÔNG được lọt vào kết quả video 2 (tiêu chí nghiệm thu)
    ("s3-4", "0"),
])
def test_hang_voi_chu_ky_catwalk_khong_hang_cung(ck_catwalk, id_, mong):
    assert cham.hang(TRUONG[id_], ck_catwalk) == mong


def test_ty_le_dung_tren_thuoc_nguoi(ck_collage):
    """Các ảnh user đã chấm tay (cham-tay-ket-qua.json 22/10) có trong fixture: ngưỡng mặc định giữ đúng ảnh user nói đúng."""
    user_dung = {"s6-7", "s7-0", "s6-1", "s7-1"}
    user_sai = {"s1-7", "s2-7", "s2-3", "s3-4", "s5-2"}
    giu = {k for k in user_dung | user_sai if cham.hang(TRUONG[k], ck_collage) in cham.NGUONG_MAC_DINH}
    assert giu == user_dung


def test_khong_doc_duoc_so_ban_sao_thi_khong_xep_hang(ck_collage):
    t = tu_json({"id": "x", "so_ban_sao": "bay", "chu_the": "nguoi mau thoi trang", "loai_nen": "trang_tron"})
    assert t.so_ban_sao is None and cham.hang(t, ck_collage) is None


def test_gia_tri_la_thanh_khac():
    t = tu_json({"id": "x", "so_ban_sao": 3, "chu_the": "robot", "loai_nen": "vu tru", "hanh_dong": "bay"})
    assert (t.chu_the, t.loai_nen, t.hanh_dong) == ("khac", "khac", "khac")


def test_chu_ky_khong_khung_nao_doc_duoc():
    with pytest.raises(ValueError):
        cham.chu_ky([tu_json({"id": "x", "so_ban_sao": None})])
