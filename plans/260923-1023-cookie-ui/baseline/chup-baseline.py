"""Chụp baseline trang Cài đặt — cookie — TRƯỚC khi thiết kế lại.

Chạy: `.venv/bin/python plans/260923-1023-cookie-ui/baseline/chup-baseline.py`

Không đụng dữ liệu thật: mọi đường dẫn của `web.app` trỏ vào một thư mục tạm,
worker bị tắt (không job nào chạy), danh tính giả qua `dependency_overrides`.
Jar là jar GIẢ tự sinh — giá trị cookie là chuỗi cố định "GIA-KHONG-THAT".

Hai đường, vì bốn mã cookie đi ra màn hình qua hai chỗ khác nhau:
  A. jar ĐANG LƯU  — mở trang, đọc khối "Trạng thái" (GET /me/cookie)
  B. lúc DÁN       — gõ vào ô, bấm Lưu, đọc dòng lỗi (PUT /me/cookie trả 400)
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

# Tham số 1 (tuỳ chọn): thư mục ra — để chụp bản đã vá mà không đè ảnh baseline.
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
PORT = 7899
NGUOI = "baseline@dev.local"
GIA = "GIA-KHONG-THAT"
BAY_GIO = int(time.time())


def ck(name: str, han: int | None) -> dict:
    c = {"name": name, "value": GIA, "domain": ".tiktok.com", "path": "/"}
    if han is not None:
        c["expirationDate"] = han
    return c


# (tên ca, nội dung tệp, mã mong đợi) — mã mong đợi là thứ `cookies.py` TRẢ,
# không phải thứ UI hiện; so hai thứ đó chính là mục đích của baseline.
CA = [
    ("1-on-dung-duoc", json.dumps([ck("sessionid", BAY_GIO + 30 * 86400),
                                   ck("ttwid", BAY_GIO + 365 * 86400)]), "dung_duoc"),
    ("2-khong-doc-duoc", r"{\rtf1\ansi cookie}", "cookie_khong_doc_duoc"),
    ("3-rong", "[]", "cookie_rong"),
    ("4-chua-dang-nhap", json.dumps([ck("ttwid", BAY_GIO + 365 * 86400)]), "cookie_chua_dang_nhap"),
    ("5-het-han", json.dumps([ck("sessionid", BAY_GIO - 86400)]), "cookie_het_han"),
]


def chuan_bi(tmp: Path) -> None:
    app_mod.DATA_DIR = tmp
    app_mod.DB_PATH = tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR = tmp / "downloads"
    app_mod.COOKIES_DIR = tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    app_mod.worker.start = lambda: None
    app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI


def doc_khoi(page) -> dict:
    g = lambda i: page.locator(f"#{i}").inner_text().strip()  # noqa: E731
    return {"chip": g("cookie-chip"), "trang_thai": g("ck-trang-thai"),
            "han": g("ck-han"), "van_tay": g("ck-van-tay"), "loi": g("cookie-error")}


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="videodl-baseline-"))
    chuan_bi(tmp)
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=PORT,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.1)

    jar = cookie_jar_path(app_mod.COOKIES_DIR, NGUOI)
    ket_qua = []
    url = f"http://127.0.0.1:{PORT}/settings.html"
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            page = br.new_page(viewport={"width": 1100, "height": 900})
            khoi = page.locator("#vung-cua-toi .panel").first

            def chup(ten: str) -> None:
                page.wait_for_function(
                    "document.getElementById('cookie-chip').textContent !== 'Đang kiểm…'")
                khoi.screenshot(path=str(OUT / f"{ten}.png"))

            # Ca 0: chưa có jar.
            jar.unlink(missing_ok=True)
            page.goto(url)
            chup("A0-chua-co-jar")
            ket_qua.append({"duong": "A", "ca": "0-chua-co-jar", "mong": None, **doc_khoi(page)})

            for ten, noi_dung, mong in CA:
                # A — jar đang lưu (đặt tay, đi vòng qua cổng kiểm của PUT).
                jar.parent.mkdir(parents=True, exist_ok=True)
                jar.write_text(noi_dung, encoding="utf-8")
                page.goto(url)
                chup(f"A{ten}")
                ket_qua.append({"duong": "A", "ca": ten, "mong": mong, **doc_khoi(page)})

                # B — dán vào ô rồi bấm Lưu, bắt đầu từ trạng thái chưa có jar.
                jar.unlink(missing_ok=True)
                page.goto(url)
                chup(f"B{ten}-truoc")
                page.fill("#cookie-json", noi_dung)
                page.click("#cookie-luu")
                page.wait_for_function(
                    "!document.getElementById('cookie-luu').disabled")
                page.wait_for_timeout(300)
                chup(f"B{ten}")
                ket_qua.append({"duong": "B", "ca": ten, "mong": mong,
                                "jar_ton_tai_sau": jar.exists(), **doc_khoi(page)})
                jar.unlink(missing_ok=True)
            br.close()
    finally:
        server.should_exit = True
        t.join(timeout=5)

    (OUT / "ket-qua.json").write_text(json.dumps(ket_qua, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    for r in ket_qua:
        print(json.dumps(r, ensure_ascii=False))
    print("tmp:", tmp)


if __name__ == "__main__":
    main()
