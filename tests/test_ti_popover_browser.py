"""ⓘ (`.ti`) mở được bằng chạm / bàn phím — đo trên TRÌNH DUYỆT THẬT (app thật, /videos giả).

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
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang

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

    tmp = Path(tempfile.mkdtemp(prefix="videodl-ti-"))
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
            br = pw.chromium.launch(args=ARGS_CHAN_MANG)
        except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
            pytest.skip(f"không mở được Chromium: {exc}")
        p = br.new_page(viewport={"width": 1200, "height": 900})
        chan = dem_mang_ngoai(p)
        p.route("**/videos?*", lambda r: r.fulfill(json={"tong": TONG, "videos": VIDEOS}))
        mo_trang(p, base_url, chan)
        p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
        yield p
        br.close()


def test_bam_ti_hien_chu_giai_thich_roi_dong_bang_esc_va_bam_ngoai(page):
    ti = page.locator("#chip-vao-bo .ti")
    ti.click()
    pop = page.locator("#ti-pop")
    assert pop.is_visible()
    assert "bộ tự tìm" in pop.inner_text()
    assert ti.get_attribute("aria-expanded") == "true" and ti.get_attribute("aria-describedby") == "ti-pop"
    # ⓘ nằm trong nút chip: bấm ⓘ KHÔNG được bật chip (không đổi phía lưới)
    assert page.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
    page.keyboard.press("Escape")
    assert not pop.is_visible() and ti.get_attribute("aria-expanded") == "false"
    # bàn phím: focus + Enter mở, bấm ra ngoài đóng
    ti.focus()
    page.keyboard.press("Enter")
    assert pop.is_visible()
    page.mouse.click(5, 5)
    assert not pop.is_visible()
