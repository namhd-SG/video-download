"""Đo tải thật của lưới ở mức trần `LIBRARY_MAX` — chỉ chạy khi `VIDEODL_DO_HIEU_NANG=1`.

Đổi trần là đổi tải thật lên trình duyệt người dùng, nên số phải đo, không đoán. Trình duyệt
thật, `/videos` giả theo trang với video tổng hợp ĐỆM cho đúng cỡ JSON đo trên prod
(~1,2–1,7 KB/video, 02/10). In một dòng JSON số đo; assert chỉ chặn "treo" (trần rộng), không
chặn số đẹp — số để người đọc PR phán. Đọc số cho đúng: chạy trên LOCALHOST (không mạng,
không tunnel, không nén); thời gian tính cả việc Python dựng + chuyển body qua Playwright; heap
là `usedJSHeapSize` trước GC (chỉ báo thô); thời gian thao tác là cận trên (cộng 1 vòng
đi-về của Playwright).
"""
from __future__ import annotations

import json
import os
import re
import socket
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang

if os.environ.get("VIDEODL_DO_HIEU_NANG") != "1":
    pytest.skip("phép đo hiệu năng — bật bằng VIDEODL_DO_HIEU_NANG=1", allow_module_level=True)

pw_api = pytest.importorskip("playwright.sync_api")

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
TRAN = int(re.search(r"const LIBRARY_MAX = (\d+);", (STATIC / "app.js").read_text()).group(1))
CO_DICH_BYTE = 1450   # trung bình đo trên prod (1,2–1,7 KB/video)
NGUON = [f"https://www.tiktok.com/tag/chu-de-{k}" for k in range(12)]


def _video(i: int) -> dict:
    v = {"video_id": f"7687{i:08d}", "title": f"Video {i + 1}", "author": f"tac_gia_{i % 50}",
         "duration": [9, 22, 75, 240][i % 4], "play_count": 1000 + i, "region": ["VN", "US", "TH"][i % 3],
         "url": f"https://www.tiktok.com/@tac_gia_{i % 50}/video/7687{i:08d}",
         "drive_file_id": f"1Drive{i:010d}AbCdEfGhIjKl", "nguon": [NGUON[i % 12], NGUON[(i + 5) % 12]],
         "cum_id": None, "vao_bo": None, "music_id": f"{i:019d}",
         "tao_luc": f"2026-09-{1 + i % 28:02d}T0{i % 10}:00:00+00:00", "description": ""}
    du = CO_DICH_BYTE - len(json.dumps(v, ensure_ascii=False).encode())
    v["description"] = "x" * max(du, 0)
    return v


@pytest.fixture(scope="module")
def base_url():
    import uvicorn

    import web.app as app_mod
    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-hieunang-"))
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: "hieunang@dev.local"
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
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


def test_do_luoi_o_muc_tran(base_url):
    kho = [_video(i) for i in range(TRAN)]
    byte_tong = [0]

    def tra(route):
        q = parse_qs(urlparse(route.request.url).query)
        limit, offset = int(q["limit"][0]), int(q["offset"][0])
        body = json.dumps({"tong": TRAN, "tong_vao_bo": 0, "videos": kho[offset:offset + limit],
                           "da_don_trong_cum": []}, ensure_ascii=False)
        byte_tong[0] += len(body.encode())
        route.fulfill(body=body, content_type="application/json")

    with pw_api.sync_playwright() as pw:
        try:
            # Cờ này cho `performance.memory` số thật thay vì số làm tròn theo bậc.
            br = pw.chromium.launch(args=["--enable-precise-memory-info", *ARGS_CHAN_MANG])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"không mở được Chromium: {exc}")
        p = br.new_page(viewport={"width": 1280, "height": 900})
        chan = dem_mang_ngoai(p)
        p.route("**/videos?*", tra)
        t0 = time.perf_counter()
        mo_trang(p, base_url, chan)
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached", timeout=60_000)
        t_ve = time.perf_counter() - t0
        so_the = p.locator("#card-grid .card").count()
        heap = p.evaluate("performance.memory ? performance.memory.usedJSHeapSize : null")

        def do(hanh_dong, cho):
            t = time.perf_counter()
            hanh_dong()
            p.wait_for_function(cho, timeout=30_000)
            return time.perf_counter() - t

        # Lọc "Dài": mở hộp, tick mục đầu ⇒ chờ huy hiệu số + lưới vẽ lại.
        p.locator(".filter-trigger").nth(1).click()
        t_loc = do(lambda: p.locator(".filter-panel:not([hidden]) input[type=checkbox]").first.click(),
                   "document.querySelector('.filter-trigger .count') !== null")
        p.click("#library-count")   # bấm ra ngoài ⇒ trang tự đóng hộp lọc
        p.wait_for_function("!document.querySelector('.filter-panel:not([hidden])')")
        # Chọn tất cả trang này (40 thẻ mặc định).
        t_chon = do(lambda: p.click("#chon-trang"),
                    "!document.getElementById('selection-bar').hidden")
        # Đổi 100 thẻ/trang rồi sang trang 2.
        t_100 = do(lambda: p.click('#so-moi-trang [data-so="100"]'),
                   "document.querySelectorAll('#card-grid .card').length === 100")
        heap2 = p.evaluate("performance.memory ? performance.memory.usedJSHeapSize : null")
        br.close()

    so = {"tran": TRAN, "json_tong_MB": round(byte_tong[0] / 1e6, 2), "toi_luoi_ve_xong_s": round(t_ve, 2),
          "the_tren_trang": so_the, "heap_sau_nap_MB": heap and round(heap / 1e6, 1),
          "loc_dai_s": round(t_loc, 3), "chon_tat_ca_trang_s": round(t_chon, 3),
          "doi_100_moi_trang_s": round(t_100, 3), "heap_cuoi_MB": heap2 and round(heap2 / 1e6, 1)}
    print("DO_HIEU_NANG " + json.dumps(so, ensure_ascii=False))
    # Chỉ chặn TREO (trần rộng), không chặn số đẹp.
    assert t_ve < 30 and t_loc < 5 and t_chon < 5 and t_100 < 5, so
