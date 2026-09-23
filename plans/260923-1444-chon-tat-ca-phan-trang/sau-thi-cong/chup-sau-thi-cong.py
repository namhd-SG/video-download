"""Chụp "Chọn tất cả trang này + phân trang" SAU thi công — code THẬT, không chèn DOM.

Chạy: `.venv/bin/python plans/260923-1444-chon-tat-ca-phan-trang/sau-thi-cong/chup-sau-thi-cong.py`
Cùng sân với `../dung-mock.py`: app thật, `/videos` giả 86 video (control = thư viện
lớn nhất trên mini 23/09). Thao tác bằng click thật.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mock", HERE.parent / "dung-mock.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

import tempfile, threading, time  # noqa: E401,E402
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> None:
    a = m.app_mod
    tmp = Path(tempfile.mkdtemp(prefix="videodl-pager-chup-"))
    a.DATA_DIR, a.DB_PATH, a.DOWNLOADS_DIR = tmp, tmp / "j.db", tmp / "d"
    a.COOKIES_DIR, a.COOKIE_TMP_DIR = tmp / "c", tmp / "t"
    a.worker.start = a.worker.stop = lambda: None
    a.app.dependency_overrides[m.require_user] = lambda: "chup@dev.local"
    srv = uvicorn.Server(uvicorn.Config(a.app, host="127.0.0.1", port=m.PORT, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    while not srv.started:
        time.sleep(0.1)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for che_do, vp, scheme in [("sang", 1200, "light"), ("toi", 1200, "dark"), ("dt", 390, "light")]:
                p = br.new_page(viewport={"width": vp, "height": 1000}, color_scheme=scheme)
                p.route("**/videos?*", lambda r: r.fulfill(json={"tong": m.TONG, "videos": m.VIDEOS}))
                p.goto(f"http://127.0.0.1:{m.PORT}/")
                p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
                so = lambda: p.locator("#card-grid .card").count()  # noqa: E731
                p.screenshot(path=str(HERE / f"{che_do}-1-trang-1.png"), full_page=True)
                n1 = so()
                p.click("#chon-trang")
                p.screenshot(path=str(HERE / f"{che_do}-2-chon-tat-ca-trang-1.png"), full_page=True)
                chon = p.inner_text("#selection-count")
                p.locator("#lib-toolbar").get_by_role("button", name="3", exact=True).click()
                p.wait_for_timeout(150)
                p.screenshot(path=str(HERE / f"{che_do}-3-sang-trang-3.png"), full_page=True)
                p.locator(".lib-toolbar").screenshot(path=str(HERE / f"{che_do}-cat-thanh-cong-cu.png"))
                p.locator(".pager").screenshot(path=str(HERE / f"{che_do}-cat-phan-trang.png"))
                print(che_do, "| trang1 thẻ:", n1, "| sau chọn:", chon, "| trang3 thẻ:", so(),
                      "| toast:", p.inner_text("#toast")[:40],
                      "| tràn:", p.evaluate("document.documentElement.scrollWidth > innerWidth"))
                p.close()
            br.close()
    finally:
        srv.should_exit = True
        t.join(timeout=5)


if __name__ == "__main__":
    main()
