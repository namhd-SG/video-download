"""Tải MỘT bài ảnh: đủ K tệp, kiểm từng tệp, URL dự phòng, lỗi phân loại, hụt thì xoá sạch thư mục bài.

Không gọi mạng: `lay` giả thay `requests.get`; ảnh mẫu sinh bằng Pillow.

Đột biến (áp tạm trong `tai_anh.py` ⇒ test đỏ, hoàn nguyên ⇒ xanh):
  * Bỏ kiểm đủ K tệp: trong `tai_mot_bai` xoá điều kiện `len(tep) != k` và để vòng lặp dừng sau tệp thứ K-1
    (vd `zip(urls_moi_tep[:-1], kieu)`) ⇒ `test_bai_thieu_tep_bi_bo_ca_bai` đỏ.
  * Bỏ kiểm byte ảnh bằng Pillow: cho `_kiem_anh_bang_pillow` trả luôn "jpg" không mở tệp ⇒
    `test_tep_html_dat_ten_anh_bi_bo_ca_bai` đỏ.
  * Bỏ kiểm luồng hình của con-video: thay `if not kiem_video(part)` bằng `if False` ⇒
    `test_con_video_khong_co_luong_hinh_lam_hut_bai` đỏ.
"""
from __future__ import annotations

import io

import pytest
import requests
from PIL import Image

from tiktok_music_downloader import tai_anh
from tiktok_music_downloader.tai_anh_cau_hinh import TRAN_ANH_MOI_BAI
from tiktok_music_downloader.utils import VideoRef

BAI = "anh-tt-7000000000000000001"


def anh_bytes(mau=(200, 30, 30), kich_thuoc=(64, 48), dinh_dang="JPEG") -> bytes:
    buf = io.BytesIO()
    Image.effect_noise(kich_thuoc, 80).convert("RGB").save(buf, dinh_dang)   # nhiễu: đủ >1KB, không nén mất
    return buf.getvalue()


class PhanHoi:
    def __init__(self, status=200, body=b"", ctype="image/jpeg"):
        self.status_code, self._body, self.headers = status, body, {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._body), 4096):
            yield self._body[i:i + 4096]


class LayGia:
    """Kịch bản theo URL: giá trị là PhanHoi hoặc Exception (ném)."""

    def __init__(self, kich_ban):
        self.kich_ban, self.da_goi = kich_ban, []

    def __call__(self, url, **kw):
        self.da_goi.append(url)
        v = self.kich_ban[url]
        if isinstance(v, Exception):
            raise v
        return v


def ref_anh(urls, kieu=None):
    return VideoRef(video_id=BAI, url="https://nguon.invalid/bai", loai="anh", anh_urls=tuple(urls),
                    anh_kieu=tuple(kieu or ("anh",) * len(urls)))


def test_tai_du_k_tep_dat_ten_theo_thu_tu_va_dinh_dang_that(tmp_path):
    jpg, png = anh_bytes(), anh_bytes(dinh_dang="PNG")
    lay = LayGia({"a": PhanHoi(body=jpg), "b": PhanHoi(body=png, ctype="image/png")})
    kq = tai_anh.tai_mot_bai(ref_anh([("a",), ("b",)]), tmp_path, lay=lay)
    assert kq.ok and kq.loai_loi is None
    assert [p.name for p in kq.tep] == ["01.jpg", "02.png"]
    assert kq.thu_muc_bai == tmp_path / BAI
    assert not list((tmp_path / BAI).glob("*.part"))


def test_url_dau_connect_timeout_thi_thu_url_du_phong(tmp_path):
    lay = LayGia({"x": requests.ConnectTimeout("het gio"), "y": PhanHoi(body=anh_bytes())})
    kq = tai_anh.tai_mot_bai(ref_anh([("x", "y")]), tmp_path, lay=lay)
    assert kq.ok and lay.da_goi == ["x", "y"]


def test_bai_thieu_tep_bi_bo_ca_bai(tmp_path):
    """Tệp #3 hết URL dự phòng đều mất kết nối ⇒ cả bài bỏ, thư mục xoá sạch, lỗi hệ thống (mạng)."""
    lay = LayGia({"1": PhanHoi(body=anh_bytes()), "2": PhanHoi(body=anh_bytes()), "3": requests.ConnectionError()})
    kq = tai_anh.tai_mot_bai(ref_anh([("1",), ("2",), ("3",), ("4",)]), tmp_path, lay=lay)
    assert not kq.ok and kq.loai_loi == "he_thong" and not kq.can_tham_lai
    assert not (tmp_path / BAI).exists()
    assert "4" not in lay.da_goi          # hụt là dừng, không tải nốt


def test_tep_html_dat_ten_anh_bi_bo_ca_bai(tmp_path):
    """Tệp #5 là trang HTML (đủ lớn, khai Content-Type ảnh) ⇒ Pillow từ chối ⇒ 0 tệp còn lại."""
    html = b"<html><body>" + b"x" * 4000 + b"</body></html>"
    kich_ban = {str(i): PhanHoi(body=anh_bytes()) for i in range(1, 9)}
    kich_ban["5"] = PhanHoi(body=html)
    kq = tai_anh.tai_mot_bai(ref_anh([(str(i),) for i in range(1, 9)]), tmp_path, lay=LayGia(kich_ban))
    assert not kq.ok and kq.loai_loi == "he_thong" and "hỏng" in kq.ly_do
    assert not (tmp_path / BAI).exists()


def test_tep_anh_cut_hoac_qua_nho_bi_loai(tmp_path):
    cut = anh_bytes(kich_thuoc=(200, 200))
    kq = tai_anh.tai_mot_bai(ref_anh([("c",)]), tmp_path, lay=LayGia({"c": PhanHoi(body=cut[: len(cut) // 2])}))
    assert not kq.ok and kq.loai_loi == "he_thong"
    kq = tai_anh.tai_mot_bai(ref_anh([("n",)]), tmp_path, lay=LayGia({"n": PhanHoi(body=b"GIF89a")}))
    assert not kq.ok and "nhỏ" in kq.ly_do


def test_content_type_khong_phai_anh_bi_loai(tmp_path):
    kq = tai_anh.tai_mot_bai(ref_anh([("h",)]), tmp_path,
                             lay=LayGia({"h": PhanHoi(body=anh_bytes(), ctype="text/html; charset=utf-8")}))
    assert not kq.ok and kq.loai_loi == "he_thong"


@pytest.mark.parametrize("ma", [403, 410])
def test_url_ky_het_han_la_loi_nguon_va_xin_tham_lai(tmp_path, ma):
    kq = tai_anh.tai_mot_bai(ref_anh([("a", "b")]), tmp_path,
                             lay=LayGia({"a": PhanHoi(status=ma), "b": PhanHoi(status=ma)}))
    assert not kq.ok and kq.loai_loi == "nguon" and kq.can_tham_lai
    assert not (tmp_path / BAI).exists()


def test_bai_go_404_la_loi_nguon_khong_tham_lai(tmp_path):
    kq = tai_anh.tai_mot_bai(ref_anh([("a",)]), tmp_path, lay=LayGia({"a": PhanHoi(status=404)}))
    assert not kq.ok and kq.loai_loi == "nguon" and not kq.can_tham_lai


def test_vuot_tran_so_anh_la_qua_nang_phia_nguon_va_khong_goi_mang(tmp_path):
    lay = LayGia({})
    kq = tai_anh.tai_mot_bai(ref_anh([(f"u{i}",) for i in range(TRAN_ANH_MOI_BAI + 1)]), tmp_path, lay=lay)
    assert not kq.ok and kq.loai_loi == "nguon" and "nặng" in kq.ly_do and lay.da_goi == []


def test_bai_khong_co_anh_la_loi_nguon(tmp_path):
    kq = tai_anh.tai_mot_bai(ref_anh([]), tmp_path, lay=LayGia({}))
    assert not kq.ok and kq.loai_loi == "nguon"


def test_con_video_qua_kiem_luong_hinh_luu_thanh_mp4(tmp_path):
    video = b"\x00\x00\x00\x18ftypmp42" + b"v" * 3000
    lay = LayGia({"a": PhanHoi(body=anh_bytes()), "v": PhanHoi(body=video, ctype="video/mp4")})
    kq = tai_anh.tai_mot_bai(ref_anh([("a",), ("v",)], ("anh", "video")), tmp_path, lay=lay,
                             kiem_video=lambda p: True)
    assert kq.ok and [p.name for p in kq.tep] == ["01.jpg", "02.mp4"]


def test_con_video_khong_co_luong_hinh_lam_hut_bai(tmp_path):
    video = b"\x00\x00\x00\x18ftypmp42" + b"v" * 3000
    lay = LayGia({"a": PhanHoi(body=anh_bytes()), "v": PhanHoi(body=video, ctype="video/mp4")})
    kq = tai_anh.tai_mot_bai(ref_anh([("a",), ("v",)], ("anh", "video")), tmp_path, lay=lay,
                             kiem_video=lambda p: False)
    assert not kq.ok and kq.loai_loi == "he_thong"
    assert not (tmp_path / BAI).exists()


def test_con_video_ma_khong_co_ham_kiem_thi_hut_chu_khong_cho_qua(tmp_path):
    video = b"\x00\x00\x00\x18ftypmp42" + b"v" * 3000
    kq = tai_anh.tai_mot_bai(ref_anh([("v",)], ("video",)), tmp_path,
                             lay=LayGia({"v": PhanHoi(body=video, ctype="video/mp4")}))
    assert not kq.ok
