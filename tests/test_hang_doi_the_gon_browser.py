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


# ---------------------------------------------------------------- 7. Nợ sau #112: một nguồn nút giải + không in mã thô

def test_nut_xac_minh_tren_the_va_popup_ve_tu_mot_nguon_gt_khung_hanh_dong(trang, db):
    """Nút "Xác minh" của thẻ gọn VÀ popup phải lấy từ `GiaiCaptchaThe.khungHanhDong` (giai-captcha-the-job.js),
    đứng CHUNG hàng nút với "Rút lượt". Đổi chữ nút ngay trong tệp nguồn đó (route) ⇒ cả thẻ lẫn popup đổi theo.
    Đột biến ĐỎ: cho `the-luot-gon.js::hanhDong` tự vẽ lại nút như trước ⇒ chữ vẫn "Xác minh" ≠ "Xác minh·GT"."""
    job = _cho_xac_minh(db)
    p, _ = trang()

    def sua(route):
        r = route.fetch()
        route.fulfill(response=r, body=r.text().replace(">Xác minh</button>", ">Xác minh·GT</button>"))

    p.route("**/giai-captcha-the-job.js?*", sua)   # máy chủ gắn `?v=<băm>` vào src script
    p.reload()
    p.wait_for_selector(f"#job-{job}")
    hang = _hang(p, job).locator(".hn-nut")
    assert hang.locator("[data-giai-ngay]").inner_text() == "Xác minh·GT"
    assert hang.locator("[data-huy]").inner_text() == "Rút lượt"   # cùng một hàng nút của thẻ
    assert p.locator("[data-giai-ngay]").count() == 1
    q = _popup(p, job)
    assert q.locator("[data-giai-ngay]").inner_text() == "Xác minh·GT"
    assert "chỉ chủ job hoặc admin" in q.locator(".giai-luot").inner_text()


def test_chi_mot_ham_khung_hanh_dong_va_khong_con_in_ma_tho_trong_ma_nguon():
    """Chốt "đừng nhân bản": đúng MỘT `function khungHanhDong` trong web/static, và chuỗi `data-giai-ngay="`
    chỉ ở giai-captcha-the-job.js. Cửa sổ giải không còn in `Mã: <mã>` thô.
    Đột biến ĐỎ: trả lại `BaoThieu.khungHanhDong` (bao-thieu.js) ⇒ đếm được 2 hàm; trả lại
    `(lyDo ? \\`Mã: ${lyDo}\\` : "")` ở giai-captcha-popup.js ⇒ chuỗi `Mã: ${` xuất hiện lại."""
    from pathlib import Path
    tep = {f.name: f.read_text(encoding="utf-8") for f in Path("web/static").glob("*.js")}
    assert sum(s.count("function khungHanhDong") for s in tep.values()) == 1
    assert [n for n, s in tep.items() if 'data-giai-ngay="' in s] == ["giai-captcha-the-job.js"]
    assert "Mã: ${" not in tep["giai-captcha-popup.js"]
    assert "(mã chưa dịch:" not in tep["app.js"]


@pytest.mark.parametrize("ma", ["het_trang", "ma_cu_khong_con_dung"])
def test_ma_dung_khong_co_trong_bang_thi_hien_cau_tieng_viet_khong_in_ma_tho(trang, db, ma):
    """Mã dừng ngoài `STOP_REASON_TEXT` (vd `het_trang` của dữ liệu cũ) ⇒ thẻ + popup chỉ có tiếng Việt.
    Đột biến ĐỎ: trả lại `Dừng sớm (mã chưa dịch: ${...})` ở app.js `ctxThe` ⇒ `ma not in ...` lệch."""
    job = _job(db, tong=60, tim=60, bo_qua=0, xong=11, ly_do=ma, trang_thai="failed")
    p, _ = trang()
    the = _hang(p, job)
    assert ma not in the.inner_text()
    q = _popup(p, job)
    assert ma not in q.inner_text()
    assert "chưa có câu giải thích riêng" in q.locator(".stop-reason").inner_text()
    assert f"#{job}" in q.inner_text()   # câu bảo "kèm mã lượt" ⇒ mã lượt phải có ngay trong popup


# ---------------------------------------------------------------- 8. Dòng nguồn theo trạng thái thật (sau #113)

@pytest.mark.parametrize("trang_thai, xong, mong, khong", [
    ("failed", 11, "đủ số bạn xin, nhưng lượt dừng giữa chừng khi mới tải 11/60.", None),
    ("interrupted", 11, "đủ số bạn xin, nhưng lượt bị ngắt khi mới tải 11/60.", None),
    ("cancelled", 0, "đủ số bạn xin, nhưng lượt đã bị rút khi mới tải 0/60.", None),
    ("done", 59, "đủ số bạn xin, nhưng chỉ tải được 59/60.", None),
    ("done", 60, "Nguồn lần này có 60 video — đủ số bạn xin.", "nhưng"),
])
def test_dong_nguon_du_so_xin_noi_ro_da_tai_bao_nhieu_theo_trang_thai(trang, db, trang_thai, xong, mong, khong):
    """Nguồn dò đủ 60/60 mà lượt kết thúc khi mới tải một phần ⇒ dòng nguồn không được chỉ nói "đủ số bạn xin"
    (ảnh popup lượt Lỗi 11/60 ở #113). Đột biến ĐỎ: bỏ nhánh `KET_THUC_THIEU` trong `bao-thieu.js::dongNguon` ⇒
    bốn ca đầu chỉ còn "— đủ số bạn xin." (`mong in nguon` lệch)."""
    job = _job(db, tong=60, tim=60, bo_qua=0, xong=xong,
               trang_thai=trang_thai if trang_thai in ("done", "failed") else "done")
    if trang_thai in ("interrupted", "cancelled"):
        with models._connect(db) as conn:
            conn.execute("UPDATE jobs SET trang_thai = ? WHERE id = ?", (trang_thai, job))
    p, _ = trang()
    nguon = _popup(p, job).locator(".nguon").inner_text()
    assert mong in nguon, nguon
    if khong:
        assert khong not in nguon, nguon
