"""Luật cổng đối chứng: hai bảng chân trị lấy NGUYÊN từ agy R2b (`~/agy-ws/exchange/tiktok-cong-ctrl-R2b-agy.md`, mục
Bằng chứng) — không suy lại — cộng các ca chọn khung đối chứng (agy R1b ĐK1b)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tiktok_music_downloader.tim_trend import cham
from tiktok_music_downloader.tim_trend.doi_chung import (ChuKyKhongOnDinh, VideoHuongDan, chon_khung_doi_chung,
                                                          dat_lan1, tin_ca_luot, tin_lan2)
from tiktok_music_downloader.tim_trend.truong import tu_json

NGUONG = frozenset({"3", "2A"})


def _h(bit: int) -> str:
    """1 = ctrl đạt (hạng 3), 0 = ctrl trượt (2B, như lô B ca 3)."""
    return "3" if bit else "2B"


# agy R2b: "Lan 1 (a,b) -> Lan 2 (c,d): dk2=..." — 12 dòng; dòng thứ 13 "(1,1) -> DAT ngay Lan 1".
BANG_LAN2 = [
    ((0, 0), (0, 0), False), ((0, 0), (0, 1), False), ((0, 0), (1, 0), False), ((0, 0), (1, 1), True),
    ((0, 1), (0, 0), False), ((0, 1), (0, 1), False), ((0, 1), (1, 0), False), ((0, 1), (1, 1), True),
    ((1, 0), (0, 0), False), ((1, 0), (0, 1), False), ((1, 0), (1, 0), True), ((1, 0), (1, 1), True),
]


@pytest.mark.parametrize("lan1, lan2, mong", BANG_LAN2)
def test_bang_tin_lan2_cua_agy(lan1, lan2, mong):
    h1, h2 = [_h(b) for b in lan1], [_h(b) for b in lan2]
    assert not dat_lan1(h1, NGUONG)            # chỉ chấm lại khi lần 1 chưa đạt
    assert tin_lan2(h1, h2, NGUONG) is mong


def test_bang_lan1_hai_ctrl_deu_dat_thi_dat_ngay():
    assert dat_lan1([_h(1), _h(1)], NGUONG)


# agy R2b: "Bang chan tri tin_duoc PASS 9/9" — ((so_lo, so_lo_bo, so_link_giu), mã thoát).
BANG_TIN_DUOC = [
    ((1, 1, 0), 7), ((2, 1, 11), 0), ((2, 1, 0), 7),
    ((3, 2, 5), 7), ((2, 0, 0), 0), ((3, 1, 4), 0),
    ((3, 1, 0), 7), ((4, 2, 8), 0), ((4, 3, 8), 7),
]


@pytest.mark.parametrize("ca, ma", BANG_TIN_DUOC)
def test_bang_tin_duoc_cua_agy(ca, ma):
    assert tin_ca_luot(*ca) is (ma == 0)


@pytest.mark.parametrize("hang_ctrl, mong", [
    (["3"], True), (["2B"], False), (["3", "3"], True), (["3", "2B"], False),
    (["3", "2B", "3"], True), (["3", "2B", "1"], False), (["2A"], True),
])
def test_dat_lan1_la_da_so_chat(hang_ctrl, mong):
    assert dat_lan1(hang_ctrl, NGUONG) is mong


def test_ctrl_2a_dat_hay_khong_theo_nguong():
    """agy R1b ĐK1a: ctrl ra 2A (ca 3 A' lô 0) ⇒ đạt với {3,2A}, trượt khi người chạy chỉ giữ {3}."""
    assert dat_lan1(["2A"], NGUONG) and not dat_lan1(["2A"], frozenset({"3"}))


CONCERT = {"so_ban_sao": 1, "chu_the": "nguoi thuong", "loai_nen": "san_dien", "hanh_dong": "khac"}
DIEN_THOAI = {"so_ban_sao": 1, "chu_the": "nguoi thuong", "loai_nen": "trong_nha", "hanh_dong": "khac",
              "la_tutorial": True}


def _chon(cac_khung: list[dict]):
    ds = [Path(f"dau-vao-{i}.jpg") for i in range(len(cac_khung))]
    truong = {k.stem: tu_json(dict(m, id=k.stem)) for k, m in zip(ds, cac_khung)}
    return chon_khung_doi_chung(ds, truong, cham.chu_ky(list(truong.values())), NGUONG)


def test_toan_khung_huong_dan_trong_nha_bao_video_huong_dan():
    """agy R1b ĐK1b test 1: chữ ký ra nền trong_nha, mọi khung tự ra 2A — nếu chọn trước khi kiểm thì không bao giờ raise."""
    with pytest.raises(VideoHuongDan):
        _chon([DIEN_THOAI] * 3)


def test_mot_khung_concert_hai_khung_dien_thoai_khong_lay_dien_thoai_lam_ctrl():
    """agy R1b ĐK1b test 2: đa số là cảnh điện thoại ⇒ chữ ký trong_nha; không có khung hạng 3 làm neo ⇒ dừng."""
    with pytest.raises(ChuKyKhongOnDinh) as loi:
        _chon([CONCERT, DIEN_THOAI, DIEN_THOAI])
    assert not isinstance(loi.value, VideoHuongDan)


def test_neo_hang_3_dung_dau_roi_den_khung_2a():
    """Khung concert có chữ hướng dẫn in đè (ca 3 A' lô 0: tutorial=True) ⇒ 2A ⇒ vẫn là ctrl, đứng sau neo hạng 3."""
    concert_co_chu = dict(CONCERT, la_tutorial=True)
    assert [k.name for k in _chon([CONCERT, concert_co_chu, CONCERT])] == [
        "dau-vao-0.jpg", "dau-vao-2.jpg", "dau-vao-1.jpg"]
