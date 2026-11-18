"""R-02b — thân trang Thay logo theo mock B, trên trình duyệt THẬT (Chromium, chặn mạng ngoài): thứ tự khối, nhóm cột dưới gập mặc định,
khung xem kỹ chỉ hiện sau khi bấm một thẻ, giỏ từng video có ×, nhãn "N lượt", lưới thẻ bộ tự tìm 3 cột, MỘT chip trạng thái mỗi hàng lượt.
Dùng lại máy chủ + dữ liệu mẫu của test_thay_logo_1b_browser (bộ N.1AAAA 3 video, thư viện, các lượt mẫu)."""
from __future__ import annotations

from test_thay_logo_1b_browser import (  # noqa: F401 — fixture (kể cả autouse `tinh_nang_bat`) dùng lại
    _chon_ca, _mo, _tab_bo, may_chu, tinh_nang_bat, trinh_duyet,
)

from trinh_duyet_khong_mang import dem_mang_ngoai, mo_trang


def _trang_moi(br, goc, rong=1280):
    """Trang vừa mở, CHƯA bấm gì (khác `_mo`: không mở khung xem kỹ, không mở nhóm cột dưới)."""
    ctx = br.new_context(viewport={"width": rong, "height": 900})
    p = ctx.new_page()
    mo_trang(p, f"{goc}/thay-logo.html", dem_mang_ngoai(ctx))
    p.wait_for_function("document.querySelectorAll('#tl-duyet .tl-the-duyet').length === 2 && document.querySelectorAll('.tl-khoi-tog').length === 4")
    return p


def test_thu_tu_khoi_nhap_roi_cho_duyet_roi_luot_roi_nhom_gap(may_chu, trinh_duyet):
    p = _trang_moi(trinh_duyet, may_chu)
    y = p.evaluate("""() => ['#tl-nhap', '#tl-loc', '#tl-duyet', '.tl-bo-strip', 'aside.tl-cot'].map(s => document.querySelector(s).getBoundingClientRect().top + scrollY)""")
    assert y == sorted(y) and len(set(y)) == 5, y  # Đưa video vào → (lọc +) Chờ bạn duyệt → Lượt của bạn → nhóm gập


def test_nhom_cot_duoi_gap_mac_dinh_bam_tieu_de_moi_mo(may_chu, trinh_duyet):
    p = _trang_moi(trinh_duyet, may_chu)
    tog = p.locator(".tl-khoi-tog")
    assert [tog.nth(i).get_attribute("aria-expanded") for i in range(4)] == ["false"] * 4
    assert p.locator(".tl-khoi-than:visible").count() == 0  # chỉ còn tiêu đề + số
    n = p.locator("#tl-dang-lam .tl-muc").count()
    assert n >= 1 and p.locator("#tl-dang-lam .tl-khoi-tog .so").inner_text() == str(n)  # tiêu đề gập vẫn ghi số video của nhóm
    p.locator("#tl-dang-lam .tl-khoi-tog").click()
    assert p.locator("#tl-dang-lam .tl-khoi-than").is_visible() and p.locator("#tl-dang-lam .tl-muc").first.is_visible()
    p.locator("#tl-dang-lam .tl-khoi-tog").click()
    assert not p.locator("#tl-dang-lam .tl-khoi-than").is_visible()


def test_nut_xem_may_khong_chac_o_bang_luot_tu_mo_nhom_dich(may_chu, trinh_duyet):
    p = _trang_moi(trinh_duyet, may_chu)
    nut = p.locator("#tl-bo-list button", has_text="máy không chắc")
    if nut.count() == 0:
        return  # dữ liệu mẫu không có lượt ở trạng thái "chỉ còn máy không chắc"
    nut.first.click()
    assert p.locator("#tl-khong-chac .tl-khoi-than").is_visible()


def test_khung_xem_ky_chi_hien_sau_khi_bam_the_va_dong_lai_duoc(may_chu, trinh_duyet):
    p = _trang_moi(trinh_duyet, may_chu)
    assert p.locator("#tl-duyet .tl-chi-tiet").count() == 0 and p.locator("#tl-duyet .tl-phim").count() == 0
    posts = []
    p.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "danh-gia" in r.url else None)
    p.locator("#tl-duyet h2").click()  # focus về trang, KHÔNG ở ô nhập
    p.keyboard.press("d")
    p.keyboard.press("ArrowRight")
    p.wait_for_timeout(300)
    assert posts == [] and p.locator("#tl-duyet .tl-chi-tiet").count() == 0  # khung đóng ⇒ phím D/← → không chấm mù video đầu hàng
    p.locator("#tl-duyet .tl-the-anh").first.click()
    assert p.locator("#tl-duyet .tl-chi-tiet").is_visible() and p.locator("#tl-duyet .tl-phim-o").count() == 2
    p.locator("#tl-duyet .tl-dong-soi").click()
    assert p.locator("#tl-duyet .tl-chi-tiet").count() == 0 and p.locator("#tl-duyet .tl-the-duyet").count() == 2


def test_gio_liet_tung_video_co_dau_x_bo_duoc(may_chu, trinh_duyet):
    p, loi = _mo(trinh_duyet, may_chu)
    _tab_bo(p)
    _chon_ca(p, "N.1AAAA").click()
    hang = p.locator("#tl-gio-ds .tl-gio-hang")
    assert hang.count() == 3 and "N.1AAAA" in hang.first.inner_text()
    hang.first.locator(".tl-gio-bo").click()
    assert p.locator("#tl-gio-ds .tl-gio-hang").count() == 2 and p.locator("#tl-dem").inner_text() == "Đã chọn 2 video"
    assert "Nạp 1 video còn lại" in _chon_ca(p, "N.1AAAA").inner_text()  # bỏ ở giỏ ⇒ thẻ bộ cập nhật theo
    assert not loi


def test_nut_chay_ghi_so_luot_khi_gio_tron_hai_nguon(may_chu, trinh_duyet):
    p, loi = _mo(trinh_duyet, may_chu)
    _tab_bo(p)
    _chon_ca(p, "N.1AAAA").click()
    assert p.locator("#tl-tao").inner_text() == "Thay logo 3 video"  # một nguồn ⇒ một lượt, không ghi "lượt"
    p.locator('#tl-tabs [data-tab="thu-vien"]').click()
    p.wait_for_selector("#tl-tab-thu-vien input[type=checkbox]")
    p.locator("#tl-tab-thu-vien input[type=checkbox]").first.check()
    assert p.locator("#tl-tao").inner_text() == "Thay logo 4 video · 2 lượt"  # máy chủ tách giỏ trộn thành hai lượt
    p.locator("#tl-gio-ds .tl-gio-hang", has_text="Thư viện").locator(".tl-gio-bo").click()
    assert p.locator("#tl-tao").inner_text() == "Thay logo 3 video"
    assert not loi


def test_bo_tu_tim_la_luoi_the_ba_cot_va_hang_luot_chi_mot_chip(may_chu, trinh_duyet):
    p, loi = _mo(trinh_duyet, may_chu)
    _tab_bo(p)
    cot = p.evaluate("getComputedStyle(document.querySelector('#tl-tab-bo .tl-vb-ds')).gridTemplateColumns.split(' ').length")
    assert cot == 3
    the = p.locator("#tl-tab-bo .tl-vb-khoi").first
    assert the.locator(".tl-vb-dai i").count() <= 4 and the.locator(".tl-vb-chon-ca").is_visible()
    hang = p.locator("#tl-bo-list .tl-bo-the")
    assert p.locator("#tl-bo-list .tl-bo-tt").count() == hang.count() and hang.count() >= 1
    assert all(hang.nth(i).locator(".tl-bo-tt").get_attribute("title") for i in range(hang.count()))  # chuỗi bước nằm ở title + dòng phụ
    assert not loi


def test_khung_bo_tu_tim_mo_trang_cuon_ve_dau(may_chu, trinh_duyet):
    p, loi = _mo(trinh_duyet, may_chu, 1440)
    _tab_bo(p)
    assert p.evaluate("document.getElementById('tl-vung').scrollTop") == 0
    p.evaluate("document.getElementById('tl-vung').scrollTop = 99999")
    p.locator('#tl-tabs [data-tab="thu-vien"]').click()
    p.locator('#tl-tabs [data-tab="bo"]').click()
    assert p.evaluate("document.getElementById('tl-vung').scrollTop") == 0  # chuyển về tab Bộ tự tìm ⇒ về đầu
    assert not loi


def test_khung_bo_tu_tim_1440_the_cuoi_nam_tron_trong_khung(may_chu, trinh_duyet):
    p, loi = _mo(trinh_duyet, may_chu, 1440)
    _tab_bo(p)
    r = p.evaluate("""() => { const k = document.getElementById('tl-vung').getBoundingClientRect(), t = [...document.querySelectorAll('#tl-tab-bo .tl-vb-khoi')];
      return { n: t.length, duoi: Math.max(...t.map(x => x.getBoundingClientRect().bottom)), khung: k.bottom }; }""")
    assert r["n"] >= 1 and r["duoi"] <= r["khung"] + 0.5, r
    assert not loi


def test_nut_truoc_sau_chi_hien_khi_luoi_the_duyet_tran(may_chu, trinh_duyet, monkeypatch):
    from test_thay_logo_trang_browser import _danh_sach, _dong_mo, _tra_json, _trang_gia
    # Lưới thẻ: hiện hết ⇒ ẩn ‹ › (3 thẻ: 1 hàng ở 1440, 2+1 ở 390); còn thẻ giấu sau "Xem thêm" (8 thẻ) ⇒ hiện
    for so, rong, hien in ((3, 1440, False), (3, 390, False), (8, 1440, True), (8, 390, True)):
        ds = [_dong_mo(60 + i) for i in range(so)]
        p = _trang_gia(trinh_duyet, may_chu, monkeypatch, (lambda d: lambda r: _tra_json(r, _danh_sach(d)))(ds))
        p.set_viewport_size({"width": rong, "height": 900})
        p.goto(f"{may_chu}/thay-logo.html")
        p.wait_for_selector("#tl-duyet .tl-the-duyet")
        assert p.locator("#tl-duyet .tl-nav").first.is_visible() is hien, (so, rong)
