"""Canh luật "test trình duyệt không chạm mạng ra Internet" (`tests/trinh_duyet_khong_mang.py`)."""
from __future__ import annotations

import functools
import http.server
import re
import threading
from pathlib import Path

import pytest

from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang

TESTS = Path(__file__).resolve().parent
STATIC = TESTS.parent / "web" / "static"


def test_moi_lan_mo_chromium_trong_test_deu_chan_mang_ngoai():
    """Tệp test trình duyệt MỚI mà quên cờ chặn thì `goto` lại phụ thuộc Google Fonts (treo tới 30 s khi mạng chậm)."""
    thieu = []
    for f in sorted(TESTS.glob("test_*.py")):
        for m in re.finditer(r"chromium\.launch\(([^)]*)\)", f.read_text(encoding="utf-8")):
            if "ARGS_CHAN_MANG" not in m.group(1):
                thieu.append(f"{f.name}: {m.group(0)}")
    assert thieu == [], "mở Chromium mà không chặn mạng ngoài:\n" + "\n".join(thieu)


class _Im(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_a):
        pass


def test_trang_that_mo_ngay_va_request_font_bi_chan():
    """Trang `index.html` thật: request Google Fonts phải HỎNG ngay (bị chặn, đếm được) và `load` xong nhanh. Bỏ cờ
    chặn thì font đi mạng thật ⇒ không có request hỏng nào ⇒ test đỏ."""
    pw_api = pytest.importorskip("playwright.sync_api")
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Im, directory=str(STATIC)))
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        with pw_api.sync_playwright() as pw:
            try:
                br = pw.chromium.launch(args=ARGS_CHAN_MANG)
            except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
                pytest.skip(f"không mở được Chromium: {exc}")
            ctx = br.new_context()
            chan = dem_mang_ngoai(ctx)
            p = ctx.new_page()
            mo_trang(p, f"http://127.0.0.1:{web.server_address[1]}/index.html", chan, timeout=10_000)
            p.wait_for_timeout(200)          # sự kiện `requestfailed` tới sau `load`
            br.close()
    finally:
        web.shutdown()
    assert chan.dem.get("fonts.googleapis.com", 0) >= 1, f"font không bị chặn (đếm: {chan})"
