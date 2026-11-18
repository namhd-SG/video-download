"""Hàng đợi — thẻ GỌN + popup chi tiết (mock R-07 v2) trên TRÌNH DUYỆT thật.

Dùng lại máy chủ/fixture của `test_bao_thieu_browser.py` (app thật, DB tạm, worker tắt).
Mỗi test ghi đột biến đã chạy và dòng đỏ tương ứng ở docstring.
"""
from __future__ import annotations

import pytest

from test_bao_thieu_browser import (  # noqa: F401 — fixture dùng chung (pytest gom theo tên)
    NGUOI, URL_TAG, _hang, _job, _popup, db, may_chu, trang,
)
from web import models


def _cho_xac_minh(db, tong=40):
    job = models.create_job(db, URL_TAG, tong, NGUOI)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = 'cho_xac_minh', ly_do_dung = 'feed_rong', "
                     "vao_trang_thai_luc = ? WHERE id = ?", (models._now(), job))
    return job


def _chan_giai(p):
    """Chặn POST /jobs/{id}/giai (trả 409) và gom id — chỉ để biết nút có gọi `GiaiCaptcha.giaiNgay` hay không."""
    goi: list[str] = []

    def cong(route):
        goi.append(route.request.url)
        route.fulfill(status=409, content_type="application/json", body='{"detail": "thử"}')

    p.route("**/jobs/*/giai", cong)
    return goi


# ---------------------------------------------------------------- 1. "Tải lại"

def test_tai_lai_gui_post_jobs_voi_url_va_tong_cua_luot(trang, db):
    """Đột biến ĐỎ: gửi `job.xong` thay `job.tong` ở `data-tai-lai` (app.js) ⇒
    `assert posts == [{'url': ..., 'so_luong': 60, ...}]` lệch `so_luong: 7`."""
    job = _job(db, tong=60, tim=0, bo_qua=0, xong=7, trang_thai="failed")
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET usecase = 'Dance', insight_goc = 'Badaboum' WHERE id = ?", (job,))
    p, posts = trang()
    giu: list = []
    p.route("**/jobs", lambda r: (giu.append(r) if r.request.method == "POST" else r.continue_()))
    nut = p.locator(f"#job-{job} [data-tai-lai]")
    assert nut.count() == 1 and nut.inner_text() == "Tải lại"
    nut.click()
    p.wait_for_timeout(300)
    nut.dispatch_event("click")   # bấm đôi khi POST còn bay ⇒ vẫn một POST
    p.wait_for_timeout(300)
    assert len(giu) == 1
    for r in giu:
        r.continue_()
    p.wait_for_function("document.querySelectorAll('#queue-list > li').length === 2")
    assert posts == [{"url": URL_TAG, "so_luong": 60, "usecase": "Dance", "insight_goc": "Badaboum"}]


# ---------------------------------------------------------------- 2. "Tải thêm N cho đủ"

@pytest.mark.parametrize("ma, xong, tong, hien, ten", [
    ("het_vong", 18, 20, True, "Tải thêm 2 cho đủ"),
    ("het_vong", 20, 20, False, None),
    ("cookie_het_han", 5, 20, False, None),
])
def test_tai_them_chi_khi_ma_chay_lai_duoc_va_chua_du(trang, db, ma, xong, tong, hien, ten):
    """Đột biến ĐỎ: bỏ `!MA_CHAY_LAI_DUOC.has(job.ly_do_dung) ||` ở `bao-thieu.js::soChayLai` ⇒ ca
    `cookie_het_han` hiện nút (`assert (...count() == 1) is hien` lệch)."""
    job = _job(db, tong=tong, tim=tong, bo_qua=0, xong=xong, ly_do=ma, trang_thai="failed" if ma.startswith("cookie") else "done")
    p, _ = trang()
    the = _hang(p, job)
    nut = the.locator("[data-chay-lai]")
    assert (nut.count() == 1) is hien, ma
    if hien:
        assert nut.inner_text() == ten
        assert the.locator("[data-tai-lai]").count() == 0, "đã có Tải thêm thì không thêm Tải lại"
    if ma.startswith("cookie"):
        assert the.locator("a[href='settings.html']").inner_text() == "Sửa cookie →"
        assert the.locator("[data-tai-lai]").count() == 1


# ---------------------------------------------------------------- 3. Mở/đóng popup

def test_bam_nut_tren_the_khong_mo_popup_bam_than_the_va_enter_thi_mo_esc_thi_dong(trang, db):
    """Đột biến ĐỎ: bỏ dòng `if (ev.target.closest("button, a, input, label")) return;` ở tay nghe click
    của `#queue-list` (app.js) ⇒ `assert p.locator('#hn-scrim').is_hidden()` sau khi bấm Chép link đỏ."""
    job = _job(db, tong=10, tim=10, bo_qua=0, xong=10)
    p, _ = trang()
    scrim = p.locator("#hn-scrim")
    assert scrim.is_hidden()
    p.locator(f"#job-{job} [data-chep-link]").click()
    p.wait_for_function("!document.getElementById('toast').hidden")
    assert scrim.is_hidden(), "bấm nút trên thẻ không được mở popup"
    p.locator(f"#job-{job} .qi-big").click()
    assert scrim.is_visible()
    assert p.locator("#hn-pop .link-row code").inner_text() == URL_TAG
    p.keyboard.press("Escape")
    assert scrim.is_hidden()
    assert p.evaluate("document.activeElement.id") == f"job-{job}", "đóng xong trả focus về thẻ"
    p.keyboard.press("Enter")
    assert scrim.is_visible()
    p.locator("#hn-pop [data-hn-dong]").click()
    assert scrim.is_hidden()
    p.locator(f"#job-{job}").focus()
    p.keyboard.press("Space")
    assert scrim.is_visible()
    scrim.click(position={"x": 4, "y": 4})   # nền
    assert scrim.is_hidden()


# ---------------------------------------------------------------- 4. Bố cục

def _dung_nhieu_the(db):
    ids = [
        _job(db, tong=100, tim=100, bo_qua=0, xong=100),
        _job(db, tong=20, tim=18, bo_qua=0, xong=18, ly_do="het_vong"),
        _job(db, tong=60, tim=0, bo_qua=0, xong=0, ly_do="cookie_het_han", trang_thai="failed"),
        _job(db, tong=60, tim=0, bo_qua=0, xong=0, ly_do="feed_rong_khong_captcha", trang_thai="failed"),
        _job(db, tong=60, tim=60, bo_qua=0, xong=7, trang_thai="running"),
        _cho_xac_minh(db),
        models.create_job(db, URL_TAG, 30, NGUOI),   # pending
    ]
    return ids


def test_bo_cuc_the_cao_toi_da_240_mot_hang_nut_va_khong_tran_ngang_o_390(trang, db):
    """Đột biến ĐỎ: thêm `<div class="stop-reason">${ctx.stopText}</div>` vào `theGon` (the-luot-gon.js)
    ⇒ thẻ cookie_het_han cao quá 240 (`assert h <= 240`)."""
    ids = _dung_nhieu_the(db)
    p, _ = trang()
    p.set_viewport_size({"width": 1440, "height": 900})
    for jid in ids:
        h = p.locator(f"#job-{jid}").bounding_box()["height"]
        assert h <= 240, (jid, h)
        tops = p.evaluate(
            "(id) => [...document.querySelectorAll(`#job-${id} .hn-nut > *`)].map((e) => Math.round(e.getBoundingClientRect().top))",
            jid)
        assert tops and len(set(tops)) == 1, (jid, tops)
    p.set_viewport_size({"width": 390, "height": 800})
    assert p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    p.locator(f"#job-{ids[2]} .chi-tiet").click()
    assert p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") == 0
    sheet = p.locator("#hn-pop").bounding_box()
    assert sheet["x"] == 0 and sheet["width"] <= 390 and sheet["y"] + sheet["height"] >= 799, "≤560px: bottom sheet"


# ---------------------------------------------------------------- 5. Câu dài chỉ ở popup

def test_cau_dung_dai_khong_nam_tren_the_ma_nam_trong_popup(trang, db):
    """Đột biến ĐỎ: như ca bố cục (vẽ lại `ctx.stopText` lên thẻ) ⇒ `assert cau not in the.inner_text()` đỏ."""
    job = _job(db, tong=60, tim=0, bo_qua=0, xong=0, ly_do="cookie_het_han", trang_thai="failed")
    p, _ = trang()
    cau = p.evaluate("new DOMParser().parseFromString(STOP_REASON_TEXT.cookie_het_han, 'text/html').body.textContent").strip()
    assert len(cau) > 40
    the = _hang(p, job)
    assert cau not in the.inner_text() and the.locator(".stop-reason").count() == 0
    assert the.locator(".hn-note").inner_text() == "Cookie hết hạn"
    q = _popup(p, job)
    assert cau in q.locator(".stop-reason").inner_text()
    assert "cách xử lý" in q.inner_text().lower() and q.locator("ol li").count() == 3


# ---------------------------------------------------------------- 6. Xác minh (điều phối #109)

def test_the_cho_xac_minh_co_dung_mot_nut_giai_ngay_va_bam_van_goi_giai_captcha(trang, db):
    """Đột biến ĐỎ (a): cho `theGon` vẽ thêm `GT.khungHanhDong(job)` ⇒ `count() == 1` thành 2.
    Đột biến ĐỎ (b): đổi `data-giai-ngay` ở nút "Xác minh" của `hanhDong` thành thuộc tính khác ⇒ không có
    POST /jobs/{id}/giai."""
    job = _cho_xac_minh(db)
    p, _ = trang()
    goi = _chan_giai(p)
    the = _hang(p, job)
    assert the.locator("[data-giai-ngay]").count() == 1
    assert p.locator("[data-giai-ngay]").count() == 1
    assert the.locator("[data-giai-ngay]").inner_text() == "Xác minh"
    assert the.locator("[data-huy]").inner_text() == "Rút lượt"
    the.locator("[data-giai-ngay]").click()
    p.wait_for_function("!document.getElementById('toast').hidden")
    assert [u.rsplit("/", 2)[-2] for u in goi] == [str(job)]
    assert p.locator("#hn-scrim").is_hidden()
    # cùng nút ở popup: đi cùng đường, và popup chi tiết nhường chỗ cho cửa sổ giải
    _popup(p, job)
    p.locator("#hn-pop [data-giai-ngay]").click()
    p.wait_for_function("document.getElementById('hn-scrim').hidden")
    assert len(goi) == 2
