"""Chụp thẻ cookie SAU thi công, cùng sân với `baseline/chup-baseline.py`.

Chạy: `.venv/bin/python plans/260923-1023-cookie-ui/sau-thi-cong/chup-sau-thi-cong.py`

Thư mục tạm, worker tắt, danh tính giả, jar GIẢ (giá trị = "GIA-KHONG-THAT").
Ca thêm so với baseline: dán hỏng khi ĐANG có cookie tốt (baseline ghi CHƯA ĐO).
Chụp sáng rộng · tối rộng · điện thoại 390px.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import web.app as app_mod  # noqa: E402
from web.auth import require_user  # noqa: E402
from web.cookies import cookie_jar_path  # noqa: E402

OUT = Path(__file__).resolve().parent
PORT = 7897
NGUOI = "sau-thi-cong@dev.local"
BAY_GIO = int(time.time())


def ck(name, han=None):
    c = {"name": name, "value": "GIA-KHONG-THAT", "domain": ".tiktok.com", "path": "/"}
    if han is not None:
        c["expirationDate"] = han
    return c


ON = json.dumps([ck("sessionid", BAY_GIO + 30 * 86400), ck("ttwid", BAY_GIO + 365 * 86400)])
PHIEN = json.dumps([ck("sessionid")])  # cookie phiên, không ghi hạn
HET = json.dumps([ck("sessionid", BAY_GIO - 86400)])
RTF = r"{\rtf1\ansi cookie}"
CHUA_DN = json.dumps([ck("ttwid", BAY_GIO + 365 * 86400)])

# (tên ca, jar đang lưu hoặc None, thứ dán vào ô hoặc None)
CA = [
    ("1-chua-co", None, None),
    ("2-dung-duoc", ON, None),
    ("3-phien-khong-han", PHIEN, None),
    ("4-dan-hong-khi-dang-tot", ON, CHUA_DN),
    ("5-het-han", HET, None),
    ("6-jar-hong-dat-tay", RTF, None),
    ("7-dan-hong-khi-chua-co", None, RTF),
]


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="videodl-sau-thi-cong-"))
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    app_mod.worker.start = lambda: None
    app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=PORT,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.1)

    jar = cookie_jar_path(app_mod.COOKIES_DIR, NGUOI)
    url = f"http://127.0.0.1:{PORT}/settings.html"
    ket_qua = []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for che_do, vp, scheme in [("sang", 1000, "light"), ("toi", 1000, "dark"),
                                       ("dt", 390, "light")]:
                page = br.new_page(viewport={"width": vp, "height": 900}, color_scheme=scheme)
                the = page.locator(".nt-the").first
                for ten, luu_san, dan in CA:
                    jar.unlink(missing_ok=True)
                    if luu_san is not None:
                        jar.parent.mkdir(parents=True, exist_ok=True)
                        jar.write_text(luu_san, encoding="utf-8")
                    page.goto(url)
                    page.wait_for_function(
                        "document.getElementById('ck-tt-tieu-de').textContent !== 'Đang kiểm…'")
                    if dan is not None:
                        page.fill("#cookie-json", dan)
                        page.click("#cookie-luu")
                        page.wait_for_function("!document.getElementById('cookie-luu').disabled")
                        page.wait_for_timeout(200)
                    the.screenshot(path=str(OUT / f"{che_do}-{ten}.png"))
                    if che_do == "sang":
                        g = lambda i: page.locator(f"#{i}").inner_text().strip()  # noqa: E731
                        ket_qua.append({
                            "ca": ten, "lop": page.get_attribute("#ck-tt", "class"),
                            "tieu_de": g("ck-tt-tieu-de"), "han": g("ck-han"),
                            "phan_hoi": g("cookie-error") if page.is_visible("#cookie-error") else "",
                            "o_dan_trong": page.input_value("#cookie-json") == "",
                            "o_tai_khoan_hien": page.is_visible("#ck-o-tai-khoan"),
                            "tran_ngang": page.evaluate("document.documentElement.scrollWidth > innerWidth"),
                        })
                page.close()
            br.close()
    finally:
        server.should_exit = True
        t.join(timeout=5)
    (OUT / "ket-qua.json").write_text(json.dumps(ket_qua, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    for r in ket_qua:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
