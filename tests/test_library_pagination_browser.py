"""Thư viện: "Chọn tất cả trang này" + phân trang — đo trên TRÌNH DUYỆT THẬT.

App thật (uvicorn, thư mục tạm, worker tắt, danh tính giả), `/videos` trả 86 video
GIẢ qua `page.route` — 86 là thư viện lớn nhất trên mini hôm 23/09. Bấm nút thật,
đếm thẻ thật; không đọc chuỗi trong app.js.

Phân trang gắn với DOM, bộ lọc và `renderCard`, nên harness node với DOM giả
phải dựng lại quá nhiều thứ — dựng bằng tay là mù đúng với lỗi ở chỗ nối.
Không có Playwright/Chromium thì test này KHÔNG chạy (skip), đừng đọc suite xanh
thành "đã kiểm".
"""

from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

pw_api = pytest.importorskip("playwright.sync_api")

TONG = 86
VIDEOS = [{"video_id": f"76870{i:05d}", "title": f"Video {i + 1}", "author": "a",
           "duration": 15, "play_count": 1000, "region": "VN" if i < 60 else "US",
           "url": "https://www.tiktok.com/", "nguon": []} for i in range(TONG)]


@pytest.fixture(scope="module")
def base_url():
    import uvicorn

    import web.app as app_mod
    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-pager-"))
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: "pager@dev.local"
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/"
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)


@pytest.fixture
def page(base_url):
    with pw_api.sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
            pytest.skip(f"không mở được Chromium: {exc}")
        p = br.new_page(viewport={"width": 1200, "height": 900})
        p.route("**/videos?*", lambda r: r.fulfill(json={"tong": TONG, "videos": VIDEOS}))
        p.goto(base_url)
        p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
        yield p
        br.close()


def _the(p) -> int:
    return p.locator("#card-grid .card").count()


def _chon(p) -> int:
    return p.locator("#card-grid .card.selected").count()


def _so_da_chon(p) -> str:
    return p.locator("#selection-count").inner_text()


def _nut_so(p, vung: str, n: int):
    """Nút SỐ trang — "Sau ›" từ trang 1 cũng mang `data-trang=2`, nên chọn theo tên."""
    return p.locator(vung).get_by_role("button", name=str(n), exact=True)


def _bam_trang(p, n: int) -> None:
    _nut_so(p, "#lib-toolbar", n).click()


def test_mac_dinh_40_moi_trang_ra_40_40_6(page):
    assert _the(page) == 40
    assert "Hiện 1–40 / 86 video" in page.inner_text("#lib-pager-dem")
    _bam_trang(page, 2)
    assert _the(page) == 40
    _bam_trang(page, 3)
    assert _the(page) == 6
    assert "Hiện 81–86 / 86 video" in page.inner_text("#lib-pager-dem")


def test_nut_trang_o_ca_tren_lan_duoi(page):
    """Điều phối 14:50: 40 thẻ mà chỉ có nút ở đáy thì vẫn kéo mỏi tay."""
    assert _nut_so(page, "#lib-toolbar", 2).count() == 1
    assert _nut_so(page, "#lib-pager", 2).count() == 1
    _nut_so(page, "#lib-pager", 3).click()   # nút ở DƯỚI cũng phải chạy
    assert _the(page) == 6


def test_chon_tat_ca_chi_lay_trang_dang_xem(page):
    page.click("#chon-trang")
    assert _chon(page) == 40
    assert _so_da_chon(page) == "40 đã chọn", "chỉ 40 id của trang 1, không phải 86"
    assert "Bỏ chọn trang này" in page.inner_text("#chon-trang")
    page.click("#chon-trang")
    assert _chon(page) == 0 and page.is_hidden("#selection-bar")


def test_doi_trang_giu_lua_chon_va_dem_ngoai_trang(page):
    """User 26/09: "mở qua trang mới không bị mất chọn" (đảo quyết định 23/09)."""
    page.click("#chon-trang")
    _bam_trang(page, 2)
    assert page.is_visible("#selection-bar")
    assert _so_da_chon(page) == "40 đã chọn"
    assert _chon(page) == 0, "trang 2 chưa chọn thẻ nào"
    assert page.inner_text("#selection-ngoai") == "· 40 không hiện ở trang này"
    assert "Đã bỏ chọn" not in page.inner_text("#toast")
    _bam_trang(page, 1)
    assert _chon(page) == 40 and page.inner_text("#selection-ngoai") == ""


def test_doi_so_moi_trang_giu_lua_chon(page):
    """User 26/09 10:35 — đổi số/trang: "giữ"."""
    page.click("#chon-trang")
    page.click("#so-moi-trang [data-so='30']")
    assert _the(page) == 30
    assert _so_da_chon(page) == "40 đã chọn"
    assert _chon(page) == 30
    assert page.inner_text("#selection-ngoai") == "· 10 không hiện ở trang này"
    page.evaluate("localStorage.removeItem('videodl-per-page')")


def test_xoa_khi_co_video_o_trang_khac_hoi_kem_so(page):
    """Thao tác hàng loạt trên video KHÔNG thấy ⇒ hộp xác nhận phải nêu số đó."""
    page.click("#chon-trang")
    _bam_trang(page, 2)
    page.locator("#card-grid .card").first.click()
    cau = []
    page.once("dialog", lambda d: (cau.append(d.message), d.dismiss()))
    page.click("#selection-bar [data-action='loai']")
    assert cau and cau[0].startswith("Bỏ 41 video")
    assert "40 video không hiện ở trang này" in cau[0]
    assert _so_da_chon(page) == "41 đã chọn", "bấm Huỷ thì không đụng lựa chọn"


def test_dua_vao_cum_khi_co_video_o_trang_khac_hoi_truoc(page):
    page.click("#chon-trang")
    _bam_trang(page, 2)
    cau = []
    page.once("dialog", lambda d: (cau.append(d.message), d.dismiss()))
    page.click("#selection-bar [data-action='cum']")
    assert cau and "40 video không hiện ở trang này" in cau[0]
    assert page.is_hidden("#cum-popover"), "Huỷ ⇒ không mở hộp gán cụm"


def test_100_moi_trang_ra_1_trang_va_an_nut(page):
    page.click("#so-moi-trang [data-so='100']")
    assert _the(page) == 86
    assert page.locator("#lib-toolbar [data-trang]").count() == 0
    assert "Hiện 1–86 / 86 video" in page.inner_text("#lib-pager-dem")


def test_doi_so_moi_trang_nho_qua_lan_tai_lai(page):
    page.click("#so-moi-trang [data-so='20']")
    assert _the(page) == 20
    page.reload()
    page.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
    assert _the(page) == 20, "số/trang phải nhớ qua localStorage"
    page.evaluate("localStorage.removeItem('videodl-per-page')")


def test_doi_bo_loc_ve_trang_1_va_giu_lua_chon(page):
    """Điều phối chốt 14:50: đổi bộ lọc ⇒ trang 1, GIỮ lựa chọn (như trước phân trang)."""
    _bam_trang(page, 2)
    page.locator("#card-grid .card").first.click()
    assert _so_da_chon(page) == "1 đã chọn"
    # Đường của người dùng: mở hộp "Thị trường" rồi tick VN (checkbox chỉ được
    # dựng khi mở hộp).
    page.click('#filter-bar [data-toggle="thi_truong"]')
    # `click`, không `check`: `renderFilterBar` DỰNG LẠI thanh lọc ngay trong sự kiện
    # change (có từ trước), nên `check` chờ mãi trạng thái của một phần tử đã thay.
    page.click('#filter-bar input[data-group="thi_truong"][value="VN"]')
    assert "Hiện 1–40 / 60 video" in page.inner_text("#lib-pager-dem"), "phải về trang 1"
    assert _so_da_chon(page) == "1 đã chọn", "đổi bộ lọc không được xoá lựa chọn"


def test_bam_them_the_o_trang_2_giu_so_khong_hien(page):
    page.click("#chon-trang")
    _bam_trang(page, 2)
    page.locator("#card-grid .card").first.click()
    assert _so_da_chon(page) == "41 đã chọn"
    assert page.inner_text("#selection-ngoai") == "· 40 không hiện ở trang này"


def test_video_bi_bo_loc_an_cung_tinh_la_khong_hien(page):
    """Chọn ở trang 1 (VN) rồi lọc US ⇒ các thẻ đã chọn không nằm ở trang nào của bộ lọc."""
    page.locator("#card-grid .card").first.click()
    page.click('#filter-bar [data-toggle="thi_truong"]')
    page.click('#filter-bar input[data-group="thi_truong"][value="US"]')
    assert _so_da_chon(page) == "1 đã chọn"
    assert page.inner_text("#selection-ngoai") == "· 1 không hiện ở trang này"
