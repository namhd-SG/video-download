"""Thay logo — lối ra cho ca "Máy không chắc" và trạng thái lượt nói thật, trên trình duyệt THẬT (Chromium, chặn mạng ngoài).

Ca máy không thay gì từng là ngõ cụt: thẻ không có link, không có lý do đọc được, lượt 0 video ra vẫn ghi "Xong" + "Chờ duyệt", và
"Thư mục Drive riêng" trông như link mà không mở được. Các test dưới dựng /bo và /videos bằng JSON cố định (dữ liệu thử, không chạm prod).

Ảnh chụp ghi vào `$VIDEODL_ANH_THAY_LOGO` nếu có đặt (để người duyệt tự mở).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_thay_logo_trang_browser import (  # noqa: F401 — fixture may_chu/trinh_duyet dùng lại
    _anh, _danh_sach, _dong_mo, _luot, _tra_json, _trang_gia, may_chu, trinh_duyet,
)

from tiktok_music_downloader.thay_logo import duong_ong

GOC = Path(duong_ong.__file__).read_text(encoding="utf-8")
MAC_DINH = "Máy chưa tự thay được, cần người xem."
CHU_KY_SU = re.compile(r"box|agy|khung|vết|cụm|NCC|mồi", re.I)

# Mỗi lý do lõi có thể ghi cho ca "không chắc" (duong_ong.py). Chuỗi mẫu PHẢI còn trong mã lõi — lõi đổi chữ thì test đỏ ở đây,
# nhắc sửa bảng LY_DO_MAY ở thay-logo-chung.js thay vì để lý do mới lặng lẽ rơi về câu mặc định.
LY_DO_LOI = [
    "không có box mồi nào dùng được",
    "chỉ dò lại được 1 khung ngoài khung mồi",
    "vết nhảy loạn (",
    "không tách khỏi nền nhiễu của video",
    "không dựng được mẫu từ box mồi",
    "vết không khớp box mồi (mẫu có thể học nhầm nội dung)",
    "mọi khung đều bị cổng nội dung chặn",
    duong_ong.LY_DO_HAT_GIONG_NHO.format(n=2),
    duong_ong.LY_DO_VONG_HAI,
    "cụm chỉ có 1 box, dưới ngưỡng",
]


def _anh_jpg(r):
    from io import BytesIO

    from PIL import Image
    b = BytesIO()
    Image.new("RGB", (36, 64), (230, 230, 230)).save(b, "JPEG")
    r.fulfill(status=200, content_type="image/jpeg", body=b.getvalue())


def test_bang_ly_do_khop_ma_loi_va_moi_ly_do_co_loi_thuong(may_chu, trinh_duyet, monkeypatch):
    """Mọi lý do lõi ⇒ một câu thường riêng (không rơi về mặc định, không có chữ kỹ thuật); chuỗi lạ ⇒ câu mặc định; rỗng ⇒ không hiện.
    ĐỘT BIẾN: xoá một dòng trong LY_DO_MAY ⇒ ĐỎ."""
    for mau in LY_DO_LOI[:7] + ["cụm chỉ có"]:
        assert mau.split(" (")[0].split(" 1 ")[0] in GOC, f"lõi không còn chuỗi {mau!r}: sửa LY_DO_MAY"
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach([])))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("window.TL && typeof window.TL.lyDoDeHieu === 'function'")
    for mau in LY_DO_LOI:
        cau = p.evaluate("(c) => window.TL.lyDoDeHieu(c)", f"1/1 watermark không tự thay được: [cụm 0, 2 box] {mau}")
        assert cau and cau != MAC_DINH and not CHU_KY_SU.search(cau), (mau, cau)
    assert p.evaluate("() => window.TL.lyDoDeHieu('lý do mới chưa ai thấy')") == MAC_DINH
    assert p.evaluate("() => window.TL.lyDoDeHieu(null)") == ""


def test_the_khong_chac_co_ly_do_thuong_link_goc_va_anh_lon(may_chu, trinh_duyet, monkeypatch):
    """Ca máy không chắc: lý do lời thường (2 lý do ⇒ 2 câu), link "▶ Xem video gốc" tới đúng file Drive nguồn, ảnh máy đã nhìn bấm được
    (mở ảnh lớn ở tab mới). Không còn chữ kỹ thuật nào trong khối. ĐỘT BIẾN: bỏ link gốc / bỏ thẻ <a> quanh ảnh ⇒ ĐỎ."""
    ly = "2/2 watermark không tự thay được: [cụm 0, 3 box] vết nhảy loạn (4 bước); [cụm 1, 2 box] mọi khung đều bị cổng nội dung chặn"
    v = _dong_mo(41, trang_thai="cho_nguoi", so_box=5, co_truoc=1, ly_do_may=ly, ten_video="Test 03_12.mp4")
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach([v])), bo=[_luot(1, "Bộ thử", tong=1, cho_nguoi=1)])
    p.route("**/api/thay-logo/videos/41/khung/*", _anh_jpg)
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('#tl-khong-chac .tl-muc').length === 1 && document.querySelector('#tl-khong-chac img.tl-truoc-nho')")
    k = p.locator("#tl-khong-chac")
    chu = k.inner_text()
    assert "đổi chỗ liên tục" in chu and "đè lên mặt người hoặc chữ" in chu
    assert not CHU_KY_SU.search(chu), chu
    goc = k.get_by_role("link", name="▶ Xem video gốc")
    assert goc.get_attribute("href") == "https://drive.google.com/file/d/" + "F" * 20 + "/view" and goc.get_attribute("target") == "_blank"
    a = k.locator("a.tl-truoc-nho-link")
    assert a.get_attribute("href") == "/api/thay-logo/videos/41/khung/truoc.jpg" and a.get_attribute("target") == "_blank"
    # Cùng màn hình, các con số phải khớp nhau: đầu trang, dòng lượt, khối bên phải.
    assert "1 video máy không chắc" in p.locator("#tl-tom-tat").inner_text()
    luot = p.locator("#tl-bo-list .tl-bo-the").nth(0).inner_text()
    assert "Máy xong 1/1" in luot and "Máy đang làm" not in luot
    _anh(p, "ux-f1-khong-chac-1280.png")


def test_khong_chac_video_da_don_khong_co_link_goc(may_chu, trinh_duyet, monkeypatch):
    """File nguồn đã dọn (`da_don`) ⇒ không dựng link gốc chết; lý do vẫn hiện."""
    v = _dong_mo(42, trang_thai="cho_nguoi", so_box=0, da_don=1, ly_do_may="không có box mồi nào dùng được")
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach([v])))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('#tl-khong-chac .tl-muc').length === 1")
    k = p.locator("#tl-khong-chac")
    assert "không tìm thấy logo cũ đủ rõ" in k.inner_text() and k.get_by_role("link", name="▶ Xem video gốc").count() == 0


def _mo_luot(br, goc, monkeypatch, bo, videos=()):
    p = _trang_gia(br, goc, monkeypatch, lambda r: _tra_json(r, _danh_sach(list(videos))), bo=bo)
    p.goto(f"{goc}/thay-logo.html")
    p.wait_for_function(f"document.querySelectorAll('#tl-bo-list .tl-bo-the').length === {min(len(bo), 2)}")
    return p, p.locator("#tl-bo-list .tl-bo-the")


def test_luot_khong_ra_video_noi_that_va_thu_muc_khong_gia_link(may_chu, trinh_duyet, monkeypatch):
    """Lượt máy làm hết mà 0 video thay được: KHÔNG ghi "Xong"/"Chờ duyệt"; ca không chắc ⇒ nút dẫn tới khối "Máy không chắc"; ca toàn lỗi
    ⇒ "Không làm được" + "Không có video để duyệt". "Thư mục Drive riêng" chưa có thư mục ⇒ nói rõ "tạo khi máy thay xong video đầu tiên" và KHÔNG mang
    màu link. ĐỘT BIẾN: trả lại nhánh "Xong"/"Chờ duyệt" cũ ⇒ ĐỎ."""
    bo = [_luot(1, "Test2", dich_khac="drive", tong=1, cho_nguoi=1), _luot(2, "Toàn lỗi", dich_khac="drive", tong=2, loi=2)]
    v = _dong_mo(51, job_id=1, ten_bo="Test2", trang_thai="cho_nguoi", so_box=3, ly_do_may="vết nhảy loạn (3 bước)")
    loi = [_dong_mo(60 + k, job_id=2, ten_bo="Toàn lỗi", trang_thai="loi", loi_text="Hết chỗ đĩa khi ghi video ra.") for k in range(2)]
    p, the = _mo_luot(trinh_duyet, may_chu, monkeypatch, bo, [v, *loi])
    p.wait_for_function("document.querySelectorAll('#tl-khong-lam .tl-muc').length === 2")
    tom = p.locator("#tl-tom-tat").inner_text()
    assert "1 video máy không chắc" in tom and "2 video không làm được" in tom
    assert "0/1 đã thay" in the.nth(0).inner_text() and "0/2 đã thay" in the.nth(1).inner_text()  # không còn "0/1 xong" cạnh "Máy xong 1/1"
    assert re.search(r"Lỗi\s*2", p.locator("#tl-loc").inner_text())
    t1, t2 = the.nth(0).inner_text(), the.nth(1).inner_text()
    assert the.nth(0).locator(".tl-bo-tt").inner_text() == "Máy không chắc" and "Chờ duyệt" not in t1
    assert "Xem 1 video máy không chắc" in t1 and "tạo khi máy thay xong video đầu tiên" in t1
    assert the.nth(1).locator(".tl-bo-tt").inner_text() == "Không làm được" and "Không có video để duyệt" in t2 and "Chờ duyệt" not in t2
    mau = p.evaluate("""() => { const s = document.querySelector('.tl-bo-dich'), l = document.querySelector('#tl-bo-list a, a');
        return [getComputedStyle(s).color, s.closest('a'), getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()]; }""")
    assert mau[1] is None  # chữ nơi nhận không nằm trong <a>
    p.evaluate("(c) => { const d = document.createElement('i'); d.style.color = c; document.body.append(d); window.__ac = getComputedStyle(d).color; }", mau[2])
    assert mau[0] != p.evaluate("() => window.__ac")  # không mang màu nhấn của link
    _anh(p, "ux-f2-luot-1280.png")
    the.nth(0).get_by_role("button", name=re.compile("^Xem 1 video máy không chắc")).click()
    p.wait_for_function("(() => { const r = document.getElementById('tl-khong-chac').getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; })()")


def test_luot_co_thu_muc_ra_link_that_khong_kem_cau_cho(may_chu, trinh_duyet, monkeypatch):
    """Có video Đạt (đã có thư mục) ⇒ "Xong", link thật "Mở thư mục đầu ra", không còn câu "tạo khi máy thay xong video đầu tiên"."""
    p, the = _mo_luot(trinh_duyet, may_chu, monkeypatch, [_luot(3, "Có Đạt", dich_khac="drive", tong=2, xong=2, dat=2, thu_muc_ra_id="THUMUC" + "z" * 14)])
    t = the.nth(0).inner_text()
    assert the.nth(0).locator(".tl-bo-tt").inner_text() == "Xong" and "tạo khi máy thay xong video đầu tiên" not in t and "Thư mục Drive riêng" in t
    assert the.nth(0).locator("a.tl-bo-thumuc").get_attribute("href").endswith("/THUMUC" + "z" * 14)


def test_luot_khong_lam_duoc_khong_bi_ghim_khi_qua_2_luot_gan_nhat(may_chu, trinh_duyet, monkeypatch):
    """"Không làm được"/"Máy không chắc" không còn gì để bấm ⇒ như "Xong": ngoài 2 lượt gần nhất thì thu gọn, không ghim mãi.
    ĐỘT BIẾN: `conViec` quay lại `!== "xong"` ⇒ lượt thứ 3 bị ghim ⇒ ĐỎ."""
    bo = [_luot(5, "Mới 1", tong=1, xong=1, dat=1), _luot(4, "Mới 2", tong=1, xong=1, dat=1),
          _luot(2, "Toàn lỗi cũ", tong=2, loi=2), _luot(1, "Không chắc cũ", tong=1, cho_nguoi=1)]
    p, the = _mo_luot(trinh_duyet, may_chu, monkeypatch, bo)
    p.wait_for_timeout(300)
    chu = p.locator("#tl-bo-list").inner_text()
    assert the.count() == 2 and "Toàn lỗi cũ" not in chu and "Không chắc cũ" not in chu


def test_dau_trang_dem_ca_may_khong_chac_tren_du_lieu_that(may_chu, trinh_duyet):
    """Dữ liệu seed THẬT (bộ A có 1 video máy không chắc, đếm qua /videos thật): dòng "Việc của bạn" phải nhắc ca đó, không để toàn số 0
    trong khi khối "Máy không chắc" có video. ĐỘT BIẾN: bỏ vế `kc` ở veTomTat ⇒ ĐỎ."""
    from test_thay_logo_trang_browser import _mo
    p, loi_js = _mo(trinh_duyet, may_chu, 1280)
    p.wait_for_function("document.querySelectorAll('#tl-khong-chac .tl-muc').length === 1")
    assert "1 video máy không chắc" in p.locator("#tl-tom-tat").inner_text() and not loi_js


def test_khoi_da_cham_hien_dat_hong_va_chip_loc_dan_toi_khoi(may_chu, trinh_duyet, monkeypatch):
    """Video đã chấm từng biến mất khỏi trang (hộp duyệt chỉ giữ video CHƯA chấm, không khối nào vẽ Đạt/Hỏng) ⇒ chip "Đã đạt"/"Hỏng" mở ra
    trang trống. Nay có khối "Đã chấm": số đếm, nhãn Đạt/Hỏng, mở lại bản đã thay + bản gốc; chip lọc thu khối về đúng nhóm.
    ĐỘT BIẾN: bỏ lệnh vẽ khối "Đã chấm" ⇒ ĐỎ."""
    dat = _dong_mo(71, danh_gia="dat", drive_file_id_ra="OUTDAT" + "y" * 14, ten_video="Video đạt")
    hong = _dong_mo(72, danh_gia="hong", drive_file_id_ra="OUTHONG" + "y" * 13, ten_video="Video hỏng")
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach([dat, hong])),
                   bo=[_luot(1, "Bộ thử", tong=2, xong=2, dat=1, hong=1, thu_muc_ra_id="THUMUC" + "z" * 14)])
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('#tl-da-cham .tl-muc').length === 2")
    k = p.locator("#tl-da-cham")
    chu = k.inner_text()
    assert "Đã chấm 2" in chu.replace("\n", " ") and "✓ Đạt" in chu and "✕ Hỏng" in chu
    xem = k.get_by_role("link", name="▶ Xem video đã thay")
    assert xem.count() == 2 and xem.nth(0).get_attribute("href").endswith("/OUTDAT" + "y" * 14 + "/view")
    assert k.get_by_role("link", name="Bản gốc").count() == 2
    _anh(p, "ux-f2-da-cham-1280.png")
    for chip, con, mat in (("Đã đạt", "Video đạt", "Video hỏng"), ("Hỏng", "Video hỏng", "Video đạt")):
        p.locator("#tl-loc button", has_text=chip).click()
        p.wait_for_function("document.querySelectorAll('#tl-da-cham .tl-muc').length === 1")
        chu = k.inner_text()
        assert con in chu and mat not in chu, (chip, chu)
        p.locator("#tl-loc button", has_text=chip).click()  # tắt chip ⇒ về tất cả
        p.wait_for_function("document.querySelectorAll('#tl-da-cham .tl-muc').length === 2")
