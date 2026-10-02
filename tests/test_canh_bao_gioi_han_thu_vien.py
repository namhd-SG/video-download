"""Thư viện vượt trần nạp (`LIBRARY_MAX` = 2000) phải có cảnh báo RÕ trên trang; đúng bằng
trần thì không. Trình duyệt thật; `/videos` được giả theo trang (limit/offset) để có 2000+
video mà không dựng DB lớn. Đặt `VIDEODL_SHOT_DIR` để lưu ảnh (`shot-canh-bao-2000.png`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pw_api = pytest.importorskip("playwright.sync_api")

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
HARNESS = Path(__file__).parent / "js"


def _videos(n: int) -> list[dict]:
    return [{"video_id": f"76870{i:05d}", "title": f"Video {i + 1}", "author": "a", "duration": 15,
             "play_count": 10, "region": "VN", "url": "https://www.tiktok.com/", "nguon": [],
             "cum_id": None, "vao_bo": None, "tao_luc": "2026-09-23T00:00:00+00:00"}
            for i in range(n)]


@pytest.fixture(scope="module")
def base_url():
    import uvicorn

    import web.app as app_mod
    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-canhbao-"))
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: "canhbao@dev.local"
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


def _mo_trang(base_url, tong: int):
    """Trang thật; `/videos` giả phân trang theo `limit`/`offset` với `tong` video TỔNG cộng."""
    kho = _videos(tong)
    goi: list[int] = []

    def tra(route):
        q = parse_qs(urlparse(route.request.url).query)
        limit, offset = int(q["limit"][0]), int(q["offset"][0])
        goi.append(offset)
        route.fulfill(json={"tong": tong, "videos": kho[offset:offset + limit],
                            "da_don_trong_cum": []})
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    p = br.new_page(viewport={"width": 1200, "height": 900})
    p.route("**/videos?*", tra)
    p.goto(base_url)
    p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
    return p, br, pw, goi


@pytest.mark.parametrize("tong, co_canh_bao", [(2000, False), (2001, True)])
def test_canh_bao_chi_hien_khi_vuot_tran_2000(base_url, tong, co_canh_bao):
    p, br, pw, goi = _mo_trang(base_url, tong)
    try:
        p.wait_for_function(
            "document.getElementById('library-count').textContent.includes('video')")
        el = p.locator("#canh-bao-gioi-han")
        if co_canh_bao:
            assert el.is_visible()
            assert el.inner_text() == f"Thư viện có {tong} video, lưới chỉ nạp 2000 video mới nhất"
            thu_muc = os.environ.get("VIDEODL_SHOT_DIR")
            if thu_muc:
                # Chỉ phần đầu khối thư viện (cảnh báo + nhãn đếm + hàng thẻ đầu), không cả 40 thẻ.
                hop = p.locator("section[aria-label='Thư viện creative']").bounding_box()
                p.screenshot(path=str(Path(thu_muc) / "shot-canh-bao-2000.png"), full_page=True,
                             clip={"x": hop["x"], "y": hop["y"], "width": hop["width"], "height": 520})
        else:
            assert not el.is_visible() and el.inner_text() == ""
        # Cách nạp KHÔNG đổi: nạp theo trang 500 tới 2000 rồi dừng, không nạp video thứ 2001.
        assert goi == [0, 500, 1000, 1500], goi
        nhan = p.inner_text("#library-count")
        assert (f"(đang hiện 2000 trong {tong})" in nhan) is co_canh_bao
    finally:
        br.close()
        pw.stop()


def test_ham_thuan_canh_bao_gioi_han_o_bien():
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần node")
    src = (STATIC / "app.js").read_text()
    i = src.index("function canhBaoGioiHan(")
    d, k = 0, src.index("{", i)
    while True:
        d += src[k] == "{"
        d -= src[k] == "}"
        if d == 0:
            break
        k += 1
    ham = src[i:k + 1]
    r = subprocess.run([node, "-e", ham + ";process.stdout.write(JSON.stringify(["
                        "canhBaoGioiHan(2000,2000),canhBaoGioiHan(2001,2000),canhBaoGioiHan(0,2000),"
                        "canhBaoGioiHan(2001,2000,true),canhBaoGioiHan(2000,2000,true)]))"],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["", "Thư viện có 2001 video, lưới chỉ nạp 2000 video mới nhất", "",
                                    "Có 2001 video đã vào bộ, chỉ nạp 2000 video mới nhất", ""]


def test_vuot_tran_ca_hai_phia_chip_moi_phia_nap_rieng_2000(base_url):
    """Server lọc theo phía chip (`vao_bo=0|1`): lưới mặc định 2500 video chưa vào bộ,
    phía "Đã vào bộ" 2100 video. Mỗi phía có trần nạp RIÊNG 2000 + cảnh báo riêng; chip
    đọc `tong_vao_bo` (lưới mặc định không còn chứa video ẩn để tự đếm)."""
    kho = {0: _videos(2500),
           1: [{**v, "video_id": f"9{v['video_id']}",
                "vao_bo": {"an_luc": "2026-09-30T00:00:00+00:00", "se_don_luc": None,
                           "ma_bo": ["N.0110A"]}} for v in _videos(2100)]}
    goi: list[tuple[int, int]] = []

    def tra(route):
        q = parse_qs(urlparse(route.request.url).query)
        limit, offset, phia = int(q["limit"][0]), int(q["offset"][0]), int(q["vao_bo"][0])
        goi.append((phia, offset))
        route.fulfill(json={"tong": len(kho[phia]), "tong_vao_bo": len(kho[1]),
                            "videos": kho[phia][offset:offset + limit], "da_don_trong_cum": []})
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    try:
        p = br.new_page(viewport={"width": 1280, "height": 900})
        p.route("**/videos?*", tra)
        p.goto(base_url)
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached")
        thu_muc = os.environ.get("VIDEODL_SHOT_DIR")

        def chup(ten):
            if thu_muc:
                hop = p.locator("section[aria-label='Thư viện creative']").bounding_box()
                p.screenshot(path=str(Path(thu_muc) / f"shot-{ten}.png"), full_page=True,
                             clip={"x": hop["x"], "y": hop["y"], "width": hop["width"], "height": 620})

        assert goi == [(0, 0), (0, 500), (0, 1000), (0, 1500)], goi
        assert p.inner_text("#canh-bao-gioi-han") == "Thư viện có 2500 video, lưới chỉ nạp 2000 video mới nhất"
        assert p.inner_text("#chip-vao-bo") == "Đã vào bộ (2100)"
        assert "(đang hiện 2000 trong 2500)" in p.inner_text("#library-count")
        chup("pr2-luoi-mac-dinh-2500")

        goi.clear()
        p.click("#chip-vao-bo")
        p.wait_for_selector("#card-grid[data-nap-phia='1']", state="attached")
        assert goi == [(1, 0), (1, 500), (1, 1000), (1, 1500)], goi
        assert p.inner_text("#canh-bao-gioi-han") == "Có 2100 video đã vào bộ, chỉ nạp 2000 video mới nhất"
        assert "(đang hiện 2000 trong 2100)" in p.inner_text("#library-count")
        assert p.locator("#card-grid .bo-ma").count() > 0, "lưới phía chip là video đã vào bộ"
        chup("pr2-chip-da-vao-bo-2100")
    finally:
        br.close()
        pw.stop()


def _mo_hai_phia(base_url, so: dict, giu_phia1: list | None = None, loi_phia1: bool = False,
                 loi_phia0_sau_lan_dau: bool = False):
    """Trang thật; `/videos` giả theo phía `vao_bo` với `so[phia]` video. `giu_phia1` (một
    list) ⇒ request phía 1 bị GIỮ lại trong list, người gọi tự `tra_lai(route)` sau.
    `loi_phia1` ⇒ phía 1 trả 500; `loi_phia0_sau_lan_dau` ⇒ phía 0 trả 500 từ lượt nạp thứ
    hai (lượt đầu lúc mở trang vẫn được). Trả thêm `giu_cum`: bật `giu_cum["bat"]` ⇒ mọi
    `GET /cum` sau đó bị giữ trong `giu_cum["ds"]` (người gọi `route.continue_()`)."""
    kho = {0: _videos(so[0]),
           1: [{**v, "video_id": f"9{v['video_id']}",
                "vao_bo": {"an_luc": "2026-09-30T00:00:00+00:00", "se_don_luc": None, "ma_bo": []}}
               for v in _videos(so[1])]}

    def tra_lai(route):
        q = parse_qs(urlparse(route.request.url).query)
        limit, offset, phia = int(q["limit"][0]), int(q["offset"][0]), int(q["vao_bo"][0])
        route.fulfill(json={"tong": len(kho[phia]), "tong_vao_bo": len(kho[1]),
                            "videos": kho[phia][offset:offset + limit], "da_don_trong_cum": []})

    so_lan_phia0 = [0]

    def tra(route):
        if "vao_bo=0" in route.request.url and "offset=0&" in route.request.url:
            so_lan_phia0[0] += 1
            if loi_phia0_sau_lan_dau and so_lan_phia0[0] > 1:
                route.fulfill(status=500, body="loi")
                return
        if loi_phia1 and "vao_bo=1" in route.request.url:
            route.fulfill(status=500, body="loi")
            return
        if giu_phia1 is not None and "vao_bo=1" in route.request.url:
            giu_phia1.append(route)
            return
        tra_lai(route)
    giu_cum = {"bat": False, "ds": []}

    def tra_cum(route):
        if giu_cum["bat"]:
            giu_cum["ds"].append(route)
            return
        route.continue_()
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    try:
        p = br.new_page(viewport={"width": 1280, "height": 900})
        p.route("**/videos?*", tra)
        p.route("**/cum", tra_cum)
        p.goto(base_url)
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached")
    except Exception:
        br.close()
        pw.stop()
        raise
    return p, br, pw, tra_lai, giu_cum


def test_bam_chip_hai_lan_nhanh_luot_cu_ve_tre_khong_ghi_de(base_url):
    """Bật chip (phía 1 trả trễ) rồi tắt ngay: lượt phía 1 về SAU lượt phía 0 không được
    ghi đè lưới — lưới cuối cùng là phía 0, đúng trạng thái chip."""
    giu: list = []
    p, br, pw, tra_lai, _ = _mo_hai_phia(base_url, {0: 30, 1: 5}, giu_phia1=giu)
    try:
        p.click("#chip-vao-bo")                     # lượt phía 1: bị giữ
        p.wait_for_function("document.getElementById('card-grid').dataset.napPhia === ''")
        p.click("#chip-vao-bo")                     # lượt phía 0: về ngay
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached")
        assert len(giu) == 1
        cum_sau = []
        p.on("request", lambda r: cum_sau.append(r.url) if r.url.endswith("/cum") else None)
        with p.expect_response(lambda r: "vao_bo=1" in r.url):
            tra_lai(giu.pop())                      # lượt phía 1 về SAU
        het = time.monotonic() + 1.5
        while time.monotonic() < het and not cum_sau:
            p.wait_for_timeout(50)
        assert cum_sau == [], "lượt bị thay không được đi tiếp tới /cum"
        assert p.get_attribute("#card-grid", "data-nap-phia") == "0"
        assert p.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
        assert p.locator("#card-grid .card").count() > 0
    finally:
        br.close()
        pw.stop()


def test_chip_bat_ma_chua_co_video_nao_vao_bo_la_khong_khop_khong_phai_thu_vien_trong(base_url):
    p, br, pw, _, _ = _mo_hai_phia(base_url, {0: 5, 1: 0})
    try:
        p.click("#chip-vao-bo")
        p.wait_for_selector("#card-grid[data-nap-phia='1']", state="attached")
        assert p.locator("#no-match-state").is_visible()
        assert not p.locator("#empty-state").is_visible()
    finally:
        br.close()
        pw.stop()


def _cho_vong_su_kien(p):
    """Chờ trang chạy hết các việc đã xếp hàng (promise + macrotask) — thay cho chờ theo giờ."""
    p.evaluate("() => new Promise((r) => setTimeout(r, 0))")
    p.evaluate("() => new Promise((r) => setTimeout(r, 0))")


def _cho_dieu_kien(p, dk, tran_s: float = 10.0):
    """Bơm vòng sự kiện Playwright (callback route chạy ở phía Python) tới khi `dk()` đúng.
    Chờ theo ĐIỀU KIỆN, có trần — không phải chờ một khoảng giờ cố định."""
    het = time.monotonic() + tran_s
    while not dk():
        assert time.monotonic() < het, "quá trần chờ điều kiện"
        p.wait_for_timeout(20)


def test_luot_cu_cho_cum_ve_sau_khong_ve_de_luot_moi(base_url):
    """Lượt bật chip đã nhận video nhưng còn chờ `/cum`; người dùng tắt chip ngay. `/cum`
    của lượt CŨ về trước ⇒ lượt cũ không được vẽ lưới hay đặt `data-nap-phia`."""
    p, br, pw, _, giu_cum = _mo_hai_phia(base_url, {0: 30, 1: 5})
    try:
        giu_cum["bat"] = True
        p.click("#chip-vao-bo")                     # lượt phía 1: chờ /cum
        _cho_dieu_kien(p, lambda: len(giu_cum["ds"]) == 1)
        p.click("#chip-vao-bo")                     # lượt phía 0: chờ /cum
        _cho_dieu_kien(p, lambda: len(giu_cum["ds"]) == 2)
        giu_cum["bat"] = False
        with p.expect_response("**/cum"):
            giu_cum["ds"].pop(0).continue_()        # /cum của lượt CŨ (phía 1) về trước
        _cho_vong_su_kien(p)
        assert p.get_attribute("#card-grid", "data-nap-phia") == "", "lượt cũ không đặt tín hiệu"
        assert p.get_attribute("#card-grid", "aria-busy") == "true"
        giu_cum["ds"].pop(0).continue_()
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached")
        assert p.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
    finally:
        br.close()
        pw.stop()


def test_bam_chip_hai_lan_luot_sau_loi_chip_ve_phia_luoi_dang_ve(base_url):
    """Lưới đang phía 0. Bật chip (phía 1 bị giữ) rồi tắt ngay (phía 0 lỗi 500): lưới vẫn
    là phía 0 ⇒ chip phải TẮT — về phía lưới đang vẽ, không phải "phía trước lần bấm cuối"
    (là phía 1)."""
    giu: list = []
    p, br, pw, tra_lai, _ = _mo_hai_phia(base_url, {0: 8, 1: 3}, giu_phia1=giu,
                                         loi_phia0_sau_lan_dau=True)
    try:
        with p.expect_request(lambda r: "vao_bo=1" in r.url):
            p.click("#chip-vao-bo")
        with p.expect_response(lambda r: "vao_bo=0" in r.url):
            p.click("#chip-vao-bo")
        p.wait_for_function("document.getElementById('toast').textContent.includes('Không tải lại được thư viện')")
        assert p.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
        assert p.get_attribute("#card-grid", "data-nap-phia") == "0"
        assert p.get_attribute("#card-grid", "aria-busy") == "false"
        cum_sau = []
        p.on("request", lambda r: cum_sau.append(r.url) if r.url.endswith("/cum") else None)
        with p.expect_response(lambda r: "vao_bo=1" in r.url):
            tra_lai(giu.pop())                      # lượt phía 1 (đã bị thay) về muộn
        # Lượt bị thay phải DỪNG trước `/cum`. Không có chốt thì nó gọi `/cum` rồi vẽ đè
        # ⇒ đếm request `/cum` trong một cửa sổ có trần (phép âm cần cửa sổ; đột biến
        # bỏ chốt đã chạy và ĐỎ ở đây).
        het = time.monotonic() + 1.5
        while time.monotonic() < het and not cum_sau:
            p.wait_for_timeout(50)
        assert cum_sau == [], "lượt bị thay không được gọi /cum"
        assert p.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
        assert p.get_attribute("#card-grid", "data-nap-phia") == "0"
        assert p.locator("#card-grid .card").count() == 8
    finally:
        br.close()
        pw.stop()


def test_nap_phia_chip_loi_thi_chip_ve_phia_cu(base_url):
    """`/videos?vao_bo=1` lỗi ⇒ lưới vẫn là phía 0 ⇒ chip phải về lại phía 0 (không để
    chip "Đã vào bộ" bật trên lưới mặc định), hết `aria-busy`, và nói lỗi."""
    p, br, pw, _, _ = _mo_hai_phia(base_url, {0: 8, 1: 3}, loi_phia1=True)
    try:
        p.click("#chip-vao-bo")
        p.wait_for_function("document.getElementById('toast').textContent.includes('Không tải lại được thư viện')")
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached")
        assert p.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
        assert p.get_attribute("#card-grid", "aria-busy") == "false"
        assert p.locator("#card-grid .card").count() == 8
    finally:
        br.close()
        pw.stop()


def test_moi_video_da_vao_bo_luoi_mac_dinh_la_khong_khop_khong_phai_thu_vien_trong(base_url):
    """Phía 0 rỗng, phía 1 có 4 ⇒ chip tắt: thư viện KHÔNG trống — "không khớp bộ lọc"."""
    p, br, pw, _, _ = _mo_hai_phia(base_url, {0: 0, 1: 4})
    try:
        assert p.inner_text("#chip-vao-bo") == "Đã vào bộ (4)"
        assert p.locator("#no-match-state").is_visible()
        assert not p.locator("#empty-state").is_visible()
    finally:
        br.close()
        pw.stop()


def test_lan_nap_dau_loi_khong_noi_thu_vien_trong(base_url):
    """Lần nạp ĐẦU `/videos` lỗi ⇒ chưa có gì để quay về: KHÔNG được hiện "Thư viện chưa
    có video nào" (thư viện chưa nạp được, không phải trống)."""
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    try:
        p = br.new_page(viewport={"width": 1280, "height": 900})
        with p.expect_response(lambda r: "/videos?" in r.url):
            p.route("**/videos?*", lambda route: route.fulfill(status=500, body="loi"))
            p.goto(base_url)
        _cho_vong_su_kien(p)
        assert not p.locator("#empty-state").is_visible()
    finally:
        br.close()
        pw.stop()


def test_lan_dau_loi_roi_bam_chip_cung_loi_chip_ve_tat_het_dang_nap(base_url):
    """Lần nạp đầu lỗi, người dùng bấm chip, lượt đó cũng lỗi ⇒ chip về tắt, lưới hết
    `aria-busy` (không kẹt "đang nạp" mãi)."""
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    try:
        p = br.new_page(viewport={"width": 1280, "height": 900})
        p.route("**/videos?*", lambda route: route.fulfill(status=500, body="loi"))
        with p.expect_response(lambda r: "/videos?" in r.url):
            p.goto(base_url)
        with p.expect_response(lambda r: "vao_bo=1" in r.url):
            p.click("#chip-vao-bo")
        _cho_vong_su_kien(p)
        assert p.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
        assert p.get_attribute("#card-grid", "aria-busy") == "false"
        assert not p.locator("#empty-state").is_visible()
    finally:
        br.close()
        pw.stop()
