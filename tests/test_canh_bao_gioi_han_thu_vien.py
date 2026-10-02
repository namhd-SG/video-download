"""Thư viện vượt trần nạp (`LIBRARY_MAX`) phải có cảnh báo RÕ trên trang; từ 80 % trần
(`LIBRARY_CANH_BAO_SOM`) có cảnh báo SỚM; dưới mức đó thì không. Trình duyệt thật; `/videos`
được giả theo trang (limit/offset) để có hàng nghìn video mà không dựng DB lớn. Đặt
`VIDEODL_SHOT_DIR` để lưu ảnh. Mọi con số đọc từ `app.js` — đổi trần không phải sửa test.
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
_SRC = (STATIC / "app.js").read_text(encoding="utf-8")
TRAN = int(re.search(r"const LIBRARY_MAX = (\d+);", _SRC).group(1))
TRANG = int(re.search(r"const LIBRARY_PAGE = (\d+);", _SRC).group(1))
SOM = -(-TRAN * 8 // 10)   # Math.ceil(TRAN * 0.8) — chép lại có chủ đích để test bắt lệch
OFFSETS = list(range(0, TRAN, TRANG))


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
    # Lỗi giữa chừng (goto chậm khi máy bận) mà không đóng ⇒ vòng Playwright rò ⇒ MỌI test
    # trình duyệt chạy sau đó đỏ dây chuyền ("Sync API inside the asyncio loop").
    try:
        p = br.new_page(viewport={"width": 1200, "height": 900})
        p.route("**/videos?*", tra)
        p.goto(base_url)
        p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
    except Exception:
        br.close()
        pw.stop()
        raise
    return p, br, pw, goi


@pytest.mark.parametrize("tong, loai", [(SOM - 1, "khong"), (SOM, "som"), (TRAN, "som"),
                                        (TRAN + 1, "cat")])
def test_canh_bao_som_tu_80_phan_tram_va_cat_khi_vuot_tran(base_url, tong, loai):
    p, br, pw, goi = _mo_trang(base_url, tong)
    try:
        p.wait_for_function(
            "document.getElementById('library-count').textContent.includes('video')")
        el = p.locator("#canh-bao-gioi-han")
        if loai == "khong":
            assert not el.is_visible() and el.inner_text() == ""
            assert el.get_attribute("data-muc") == ""
            assert "som" not in (el.get_attribute("class") or "").split()
        else:
            # Chỉ "đã cắt" ngắt ngang trình đọc màn hình; "sắp chạm" là status.
            assert el.get_attribute("role") == ("alert" if loai == "cat" else "status")
            assert el.is_visible()
            # Hai mức nhìn khác nhau: "som" vàng (class `som`), "cat" đỏ (không class `som`).
            assert el.get_attribute("data-muc") == loai
            assert ("som" in (el.get_attribute("class") or "").split()) is (loai == "som")
            mau = p.evaluate("getComputedStyle(document.getElementById('canh-bao-gioi-han')).color")
            mau_warn = p.evaluate("(() => { const d = document.createElement('div'); d.style.color = 'var(--warn)';"
                                  " document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove();"
                                  " return c; })()")
            assert (mau == mau_warn) is (loai == "som"), (loai, mau, mau_warn)
            assert el.inner_text() == (
                f"Thư viện có {tong} video, lưới chỉ nạp {TRAN} video mới nhất" if loai == "cat"
                else f"Thư viện có {tong} video — sắp chạm trần nạp {TRAN}")
            thu_muc = os.environ.get("VIDEODL_SHOT_DIR")
            if thu_muc:
                # Chỉ phần đầu khối thư viện (cảnh báo + nhãn đếm + hàng thẻ đầu), không cả 40 thẻ.
                hop = p.locator("section[aria-label='Thư viện creative']").bounding_box()
                p.screenshot(path=str(Path(thu_muc) / f"shot-canh-bao-{loai}-{tong}.png"),
                             full_page=True,
                             clip={"x": hop["x"], "y": hop["y"], "width": hop["width"], "height": 520})
        # Nạp theo trang `TRANG` tới đủ `tong` hoặc tới trần rồi dừng.
        assert goi == [o for o in OFFSETS if o < tong], goi
        nhan = p.inner_text("#library-count")
        assert (f"(đang hiện {TRAN} trong {tong})" in nhan) is (loai == "cat")
    finally:
        br.close()
        pw.stop()


def test_ham_thuan_canh_bao_gioi_han_o_bien():
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần node")
    src = (STATIC / "app.js").read_text()

    def trich(ten):
        i = src.index(f"function {ten}(")
        d, k = 0, src.index("{", i)
        while True:
            d += src[k] == "{"
            d -= src[k] == "}"
            if d == 0:
                return src[i:k + 1]
            k += 1
    ham = trich("mucGioiHan") + "\n" + trich("canhBaoGioiHan")
    r = subprocess.run([node, "-e", ham + ";process.stdout.write(JSON.stringify(["
                        "canhBaoGioiHan(2000,2000),canhBaoGioiHan(2001,2000),canhBaoGioiHan(0,2000),"
                        "canhBaoGioiHan(2001,2000,true),canhBaoGioiHan(2000,2000,true),"
                        "canhBaoGioiHan(3999,5000,false,4000),canhBaoGioiHan(4000,5000,false,4000),"
                        "canhBaoGioiHan(5000,5000,true,4000),canhBaoGioiHan(5001,5000,false,4000)]))"],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["", "Thư viện có 2001 video, lưới chỉ nạp 2000 video mới nhất", "",
                                    "Có 2001 video đã vào bộ, chỉ nạp 2000 video mới nhất", "",
                                    "", "Thư viện có 4000 video — sắp chạm trần nạp 5000",
                                    "Có 5000 video đã vào bộ — sắp chạm trần nạp 5000",
                                    "Thư viện có 5001 video, lưới chỉ nạp 5000 video mới nhất"]


def test_moc_canh_bao_som_dung_80_phan_tram_tran():
    assert re.search(r"const LIBRARY_CANH_BAO_SOM = Math\.ceil\(LIBRARY_MAX \* 0\.8\);", _SRC)


def test_vuot_tran_ca_hai_phia_chip_moi_phia_nap_rieng(base_url):
    """Server lọc theo phía chip (`vao_bo=0|1`): lưới mặc định TRAN+500 video chưa vào bộ,
    phía "Đã vào bộ" TRAN+100 video. Mỗi phía có trần nạp RIÊNG + cảnh báo riêng; chip
    đọc `tong_vao_bo` (lưới mặc định không còn chứa video ẩn để tự đếm)."""
    n0, n1 = TRAN + 500, TRAN + 100
    kho = {0: _videos(n0),
           1: [{**v, "video_id": f"9{v['video_id']}",
                "vao_bo": {"an_luc": "2026-09-30T00:00:00+00:00", "se_don_luc": None,
                           "ma_bo": ["N.0110A"]}} for v in _videos(n1)]}
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

        assert goi == [(0, o) for o in OFFSETS], goi
        assert p.inner_text("#canh-bao-gioi-han") == f"Thư viện có {n0} video, lưới chỉ nạp {TRAN} video mới nhất"
        assert p.inner_text("#chip-vao-bo") == f"Đã vào bộ ({n1})"
        assert f"(đang hiện {TRAN} trong {n0})" in p.inner_text("#library-count")
        chup(f"pr2-luoi-mac-dinh-{n0}")

        goi.clear()
        p.click("#chip-vao-bo")
        p.wait_for_selector("#card-grid[data-nap-phia='1']", state="attached")
        assert goi == [(1, o) for o in OFFSETS], goi
        assert p.inner_text("#canh-bao-gioi-han") == f"Có {n1} video đã vào bộ, chỉ nạp {TRAN} video mới nhất"
        assert f"(đang hiện {TRAN} trong {n1})" in p.inner_text("#library-count")
        assert p.locator("#card-grid .bo-ma").count() > 0, "lưới phía chip là video đã vào bộ"
        chup(f"pr2-chip-da-vao-bo-{n1}")
    finally:
        br.close()
        pw.stop()


def _mo_hai_phia(base_url, so: dict, giu_phia1: list | None = None, loi_phia1: bool = False,
                 loi_phia0_sau_lan_dau: bool = False, giu_phia0_sau_lan_dau: list | None = None):
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
            if giu_phia0_sau_lan_dau is not None and so_lan_phia0[0] > 1:
                giu_phia0_sau_lan_dau.append(route)
                return
        if loi_phia1 and "vao_bo=1" in route.request.url:
            route.fulfill(status=500, body="loi")
            return
        if giu_phia1 is not None and "vao_bo=1" in route.request.url:
            giu_phia1.append(route)
            return
        tra_lai(route)
    giu_cum = {"bat": False, "ds": [], "huy": []}

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
        # Request bị trang HUỶ (AbortController của lượt nạp bị thay) — bất biến pha 1.
        p.on("requestfailed", lambda r: giu_cum["huy"].append(r.url))
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
    p, br, pw, tra_lai, gc = _mo_hai_phia(base_url, {0: 30, 1: 5}, giu_phia1=giu)
    try:
        p.click("#chip-vao-bo")                     # lượt phía 1: bị giữ
        p.wait_for_function("document.getElementById('card-grid').dataset.napPhia === ''")
        p.click("#chip-vao-bo")                     # lượt phía 0: về ngay
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached")
        assert len(giu) == 1
        cum_sau = []
        p.on("request", lambda r: cum_sau.append(r.url) if r.url.endswith("/cum") else None)
        # Lượt phía 1 bị thay ⇒ request của nó phải bị HUỶ, không chỉ bị bỏ qua.
        _cho_dieu_kien(p, lambda: any("vao_bo=1" in u for u in gc["huy"]))
        _tha(giu.pop(), tra_lai)                    # lượt phía 1 "về" SAU (đã huỷ)
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


def _tha(route, ham):
    """Thả một route đang giữ. Request đã bị trang huỷ thì route có thể đã đóng ⇒ bỏ qua."""
    try:
        ham(route)
    except Exception:  # noqa: BLE001
        pass


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
        # /cum của lượt CŨ phải bị HUỶ khi lượt mới bắt đầu.
        _cho_dieu_kien(p, lambda: any(u.endswith("/cum") for u in giu_cum["huy"]))
        _tha(giu_cum["ds"].pop(0), lambda r: r.continue_())   # /cum của lượt CŨ "về" trước
        _cho_vong_su_kien(p)
        assert p.get_attribute("#card-grid", "data-nap-phia") == "", "lượt cũ không đặt tín hiệu"
        assert "danh sách cụm" not in p.inner_text("#toast"), "/cum bị huỷ của lượt cũ không được báo lỗi"
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
    p, br, pw, tra_lai, gc = _mo_hai_phia(base_url, {0: 8, 1: 3}, giu_phia1=giu,
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
        _cho_dieu_kien(p, lambda: any("vao_bo=1" in u for u in gc["huy"]))
        _tha(giu.pop(), tra_lai)                    # lượt phía 1 (đã bị thay, đã huỷ) về muộn
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
        # Lần đầu hỏng: toast 2,6 s rồi trang trống là im lặng ⇒ ô lỗi thường trực.
        assert p.inner_text("#error").startswith("Không tải được thư viện")
        # Làm mới nạp được ⇒ câu lỗi cũ thành SAI ⇒ phải gỡ.
        p.unroute("**/videos?*")
        p.route("**/videos?*", lambda route: route.fulfill(json={
            "tong": 3, "tong_vao_bo": 0, "videos": _videos(3), "da_don_trong_cum": []}))
        truoc = p.get_attribute("#card-grid", "data-luot-xong")
        p.click("#library-refresh")
        p.wait_for_function(f"document.getElementById('card-grid').dataset.luotXong !== '{truoc}'")
        assert p.inner_text("#error") == ""
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


def test_luot_bi_thay_loi_khong_de_mat_cau_bao_cua_luot_moi(base_url):
    """Bấm "Làm mới" (lượt phía 0 bị giữ), rồi bấm chip: lượt phía 1 nạp xong và báo "Đã bỏ
    2 video…". Lượt "Làm mới" (đã bị thay) sau đó lỗi 500 ⇒ KHÔNG được toast "Không tải
    lại được thư viện" đè lên — thư viện đã nạp được."""
    giu: list = []
    p, br, pw, _, gc = _mo_hai_phia(base_url, {0: 8, 1: 3}, giu_phia0_sau_lan_dau=giu)
    try:
        the = p.locator("#card-grid .card")
        the.nth(0).click()
        the.nth(1).click()
        p.click("#library-refresh")
        _cho_dieu_kien(p, lambda: len(giu) == 1)
        p.click("#chip-vao-bo")
        p.wait_for_selector("#card-grid[data-nap-phia='1']", state="attached")
        assert p.inner_text("#toast").startswith("Đã bỏ 2 video")
        # Lượt "Làm mới" bị thay ⇒ request của nó bị HUỶ; thả nó với 500 cũng không được
        # sinh toast nào.
        _cho_dieu_kien(p, lambda: any("vao_bo=0" in u for u in gc["huy"]))
        _tha(giu.pop(), lambda r: r.fulfill(status=500, body="loi"))
        _cho_vong_su_kien(p)
        assert p.inner_text("#toast").startswith("Đã bỏ 2 video"), p.inner_text("#toast")
        assert p.get_attribute("#card-grid", "data-nap-phia") == "1"
    finally:
        br.close()
        pw.stop()


def test_trang_nap_khong_vuot_tran_trang_cua_server_va_chia_het_tran():
    """`LIBRARY_PAGE` > `MAX_VIDEOS_PAGE_SIZE` ⇒ server trả 400 ngay trang 0 ⇒ lưới trắng — mà
    mọi test trình duyệt đều giả `/videos` nên không bắt được. Và trần không chia hết trang
    ⇒ vòng nạp vượt trần (nạp 5000 trong khi băng nói 4500)."""
    import web.app as app_mod
    assert TRANG <= app_mod.MAX_VIDEOS_PAGE_SIZE, (TRANG, app_mod.MAX_VIDEOS_PAGE_SIZE)
    assert TRAN % TRANG == 0, (TRAN, TRANG)


def test_server_that_nhan_trang_co_limit_bang_LIBRARY_PAGE(tmp_path, monkeypatch):
    """Gọi route thật với đúng `limit` trang dùng, trên TRANG+1 video thật — một trang
    đầy đẩy TRANG id vào các câu `IN (…)` (nguồn, cụm, vào bộ). Không qua mock."""
    import web.app as app_mod
    from web import models
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "_la_admin", lambda email: False)
    toi = "a@astronex.ai"
    job = models.create_job(db, "https://www.tiktok.com/tag/a", TRANG + 1, toi)
    for i in range(TRANG + 1):
        models.record_video(db, job_id=job, video_id=f"v{i:05d}", url=f"https://t.co/{i}",
                            tao_luc=f"2026-09-01T00:{i // 60 % 60:02d}:{i % 60:02d}+00:00")
    r = app_mod.list_videos(limit=TRANG, offset=0, vao_bo=0, nguoi_tao=toi)
    assert len(r["videos"]) == TRANG and r["tong"] == TRANG + 1


def test_lam_moi_cung_so_khong_ghi_lai_bang_canh_bao(base_url):
    """Băng vẽ lại mỗi lượt nạp. Ghi lại CÙNG chữ thay nút chữ ⇒ trình đọc màn hình đọc lại
    câu cảnh báo mỗi lần Làm mới / job xong ⇒ cùng `tong` thì KHÔNG được có đột biến DOM nào
    trong băng (MutationObserver đếm)."""
    p, br, pw, goi = _mo_trang(base_url, SOM)
    try:
        p.wait_for_selector("#canh-bao-gioi-han:not([hidden])")
        p.evaluate("""() => { window.__dotBienBang = 0;
            new MutationObserver((ds) => { window.__dotBienBang += ds.length; })
              .observe(document.getElementById('canh-bao-gioi-han'),
                       { childList: true, characterData: true, subtree: true }); }""")
        # `data-nap-phia` được đặt SAU `veCanhBaoGioiHan`, cùng khối đồng bộ, ở cuối lượt
        # nạp ⇒ xoá nó trước khi bấm rồi chờ nó quay lại = lượt Làm mới đã vẽ xong thật
        # (`aria-busy` không dùng được: Làm mới không đặt nó).
        p.evaluate("document.getElementById('card-grid').dataset.napPhia = ''")
        p.click("#library-refresh")
        p.wait_for_selector("#card-grid[data-nap-phia='0']", state="attached")
        assert p.evaluate("window.__dotBienBang") == 0
        assert p.get_attribute("#canh-bao-gioi-han", "role") == "status"
    finally:
        br.close()
        pw.stop()


def test_lam_moi_het_phien_ra_man_het_phien_khong_ra_toast_rong(base_url):
    """Phiên Access hết hạn (302) lúc bấm Làm mới ⇒ màn "hết phiên", không phải toast
    "Không tải lại được thư viện: " với chữ rỗng."""
    p, br, pw, _, _ = _mo_hai_phia(base_url, {0: 5, 1: 0})
    try:
        p.unroute("**/videos?*")
        p.route("**/videos?*", lambda r: r.fulfill(status=302, headers={"location": "/cdn-cgi/access/login"}))
        p.evaluate("document.getElementById('toast').textContent = ''")
        p.click("#library-refresh")
        p.wait_for_selector("#session-expired:not([hidden])")
        assert "Không tải lại được thư viện" not in p.inner_text("#toast")
    finally:
        br.close()
        pw.stop()


def test_bo_video_roi_nap_lai_hong_van_bao_so_da_bo(base_url):
    """Bỏ 2 video xong (tệp đã vào Thùng rác) mà lượt nạp lại thư viện hỏng ⇒ toast tóm
    tắt VẪN ra số đã bỏ, kèm "không tải lại được thư viện" — không mất câu xác nhận."""
    p, br, pw, _, _ = _mo_hai_phia(base_url, {0: 6, 1: 0}, loi_phia0_sau_lan_dau=True)
    try:
        p.route("**/videos/loai", lambda r: r.fulfill(json={
            "da_loai": json.loads(r.request.post_data)["video_ids"], "khong_phai_cua_ban": [], "drive_truot": []}))
        p.on("dialog", lambda d: d.accept())
        the = p.locator("#card-grid .card")
        the.nth(0).click()
        the.nth(1).click()
        p.click('[data-action="loai"]')
        p.wait_for_function("document.getElementById('toast').textContent.includes('đã bỏ 2')")
        chu = p.inner_text("#toast")
        assert "không tải lại được thư viện" in chu, chu
    finally:
        br.close()
        pw.stop()


def test_bo_video_roi_het_phien_van_bao_so_da_bo(base_url):
    """Bỏ 2 video xong (tệp đã vào Thùng rác) mà lúc nạp lại thì phiên hết ⇒ màn hết phiên
    VÀ toast tóm tắt vẫn ra số đã bỏ — không mất câu xác nhận việc đã làm."""
    p, br, pw, _, _ = _mo_hai_phia(base_url, {0: 6, 1: 0})
    try:
        p.route("**/videos/loai", lambda r: r.fulfill(json={
            "da_loai": json.loads(r.request.post_data)["video_ids"], "khong_phai_cua_ban": [], "drive_truot": []}))
        p.on("dialog", lambda d: d.accept())
        the = p.locator("#card-grid .card")
        the.nth(0).click()
        the.nth(1).click()
        p.unroute("**/videos?*")
        p.route("**/videos?*", lambda r: r.fulfill(status=302, headers={"location": "/cdn-cgi/access/login"}))
        p.click('[data-action="loai"]')
        p.wait_for_selector("#session-expired:not([hidden])")
        p.wait_for_function("document.getElementById('toast').textContent.includes('đã bỏ 2')")
        assert "phiên đã hết hạn" in p.inner_text("#toast")
    finally:
        br.close()
        pw.stop()


def test_cum_di_dang_chi_bao_loi_cum_thu_vien_van_ve(base_url):
    """`/cum` trả JSON không có mảng `cum` ⇒ lưới vẫn vẽ (chỉ là lỗi cụm), không kẹt
    `aria-busy`, không "Không tải lại được thư viện"."""
    p, br, pw, _, _ = _mo_hai_phia(base_url, {0: 5, 1: 0})
    try:
        p.unroute("**/cum")
        p.route("**/cum", lambda r: r.fulfill(json={"loi": "dị dạng"}))
        truoc = p.get_attribute("#card-grid", "data-luot-xong")
        p.click("#library-refresh")
        p.wait_for_function(f"document.getElementById('card-grid').dataset.luotXong !== '{truoc}'")
        assert "danh sách cụm" in p.inner_text("#toast")
        assert "Không tải lại được thư viện" not in p.inner_text("#toast")
        assert p.get_attribute("#card-grid", "aria-busy") == "false"
        assert p.locator("#card-grid .card").count() == 5
    finally:
        br.close()
        pw.stop()
