"""Cụm của tôi — phía trang: hàm thuần JS (qua node) + luồng thật trên TRÌNH DUYỆT.

Hàm thuần: `tests/js/cum-ban-giao.js` trích hàm THẬT từ web/static/app.js.

Trình duyệt: app thật (uvicorn, DB tạm có 86 video THẬT của người xem, worker
tắt, danh tính giả). Khác `test_library_pagination_browser.py`, ở đây `/videos`
và `/cum` KHÔNG giả: luồng cụm đi qua route + SQL thật, nên chỗ nối FE↔API được
đo, không được dựng tay. Tab Creative Desk bị chặn ở tầng mạng (không bao giờ
chạm máy thật); URL của tab là thứ được giải mã và kiểm.

Không có node / Playwright / Chromium thì các test tương ứng SKIP — đừng đọc
suite xanh thành "đã kiểm".
"""
from __future__ import annotations

import base64
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from web import app as app_mod
from web import models, models_cum

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
HARNESS = Path(__file__).parent / "js"
NGUOI = "cum@dev.local"
TONG = 86


def _node(harness: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này KHÔNG chạy")
    r = subprocess.run([node, str(HARNESS / harness), str(STATIC / "app.js")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _giai_ma(url: str) -> dict:
    b64 = parse_qs(urlparse(url).query)["videodesk"][0]
    return json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))


# --- hàm thuần JS -----------------------------------------------------------

def test_tach_lo_30():
    d = _node("cum-ban-giao.js")
    assert d["lo_64"] == [30, 30, 4]
    assert d["lo_31"] == [30, 1]
    assert d["lo_30"] == [30]
    assert d["lo_0"] == []


def test_tran_js_khop_backend():
    d = _node("cum-ban-giao.js")
    assert d["HANDOFF_MAX"] == models_cum.LO_TOI_DA == 30
    assert d["GAN_CUM_TOI_DA"] == app_mod.MAX_VIDEO_CUM


def test_payload_lo_cua_cum_co_nhan_du_khoa_va_insight_lay_tu_du_lieu_cum():
    d = _node("cum-ban-giao.js")
    for ten, thu, so in (("lo2", 2, 30), ("lo3", 3, 4)):
        p = d[ten]["payload"]
        assert p["v"] == 1 and len(p["items"]) == so
        assert p["nhan"] == {"usecase": "Dance", "insight": "INSIGHT-TU-SERVER",
                             "template": "Goc", "cum_id": 12, "lo": {"thu": thu, "tong": 3}}, \
            "insight phải là `cum.insight` của server, không phải chuỗi JS tự ghép"
    assert d["mot_lo"]["payload"]["nhan"]["lo"] == {"thu": 1, "tong": 1}


def test_lo_khac_nhau_khong_chong_video():
    d = _node("cum-ban-giao.js")
    f2 = {i["f"] for i in d["lo2"]["payload"]["items"]}
    f3 = {i["f"] for i in d["lo3"]["payload"]["items"]}
    assert not f2 & f3


def test_moc_da_mo_chi_ghi_sau_khi_tab_mo_that():
    d = _node("cum-ban-giao.js")
    assert d["mot_lo"]["nhatKy"][:2] == ["open", "POST /cum/12/lo/1/da-mo"]
    chan = d["bi_chan"]
    assert chan["kq"] == "chan"
    assert chan["nhatKy"] == ["open"], "popup bị chặn thì KHÔNG được gọi da-mo"
    assert chan["lo_mo"] == []


def test_ban_giao_chon_tay_khong_co_nhan():
    d = _node("chon-sau-ban-giao.js")
    p = d["binh_thuong"]["payload"]
    assert p["v"] == 1 and len(p["items"]) == 3
    assert "nhan" not in p


def test_dua_vao_cum_trung_ten_thi_dung_lai_cum_co_san():
    d = _node("cum-ban-giao.js")
    assert d["trung_hoa_thuong"] == 12 and d["trung_khac_kieu"] is None
    assert d["dua_trung"]["goi"] == ["POST /cum/12/video"], "trùng (hoa/thường, khoảng trắng) ⇒ KHÔNG tạo cụm mới"
    assert d["dua_trung"]["cum_id_video"] == [12, 12]
    assert d["dua_moi"]["goi"] == ["POST /cum", "POST /cum/99/video"]   # control: khác kiểu ⇒ tạo


# --- trình duyệt thật -------------------------------------------------------

@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-cum-"))
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/", tmp / "jobs.db"
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)
    # KHÔNG xoá `tmp`: lúc khởi động app trỏ thư mục tạm dùng chung của tiến
    # trình (`prepare_data_dir` → COOKIE_TMP_DIR) vào đây, và xoá nó làm test
    # downloader chạy SAU tệp này hỏng `FileNotFoundError` (đo 23/09). Cùng
    # khuôn với test_library_pagination_browser.py.


@pytest.fixture
def page(may_chu):
    url, db = may_chu
    # DB sạch cho MỖI test: xoá cụm cũ, mồi lại 86 video nếu chưa có.
    models.init_db(db)
    with models._connect(db) as conn:
        conn.execute("DELETE FROM cum")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'cum'")
    if models.count_videos(db, NGUOI) == 0:
        job = models.create_job(db, "https://www.tiktok.com/tag/dance", TONG, NGUOI)
        for i in range(TONG):
            models.record_video(db, job_id=job, video_id=f"76870{i:05d}", url=f"https://t/{i}",
                                title=f"Video {i + 1}", drive_file_id=f"drv{i}",
                                tao_luc=f"2026-09-23T00:{i // 60:02d}:{i % 60:02d}+00:00")
    pw_api = pytest.importorskip("playwright.sync_api")
    with pw_api.sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
            pytest.skip(f"không mở được Chromium: {exc}")
        ctx = br.new_context(viewport={"width": 1300, "height": 900})
        # Tab Creative Desk không bao giờ ra mạng thật.
        ctx.route("https://automation.nobidigital.asia/**",
                  lambda r: r.fulfill(body="<html>creative desk giả</html>", content_type="text/html"))
        p = ctx.new_page()
        p.goto(url)
        p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
        yield p
        br.close()


def _cum_api(p) -> list[dict]:
    return p.evaluate("fetch('/cum').then(r => r.json())")["cum"]


def _chon(p, n: int) -> None:
    the = p.locator("#card-grid .card")
    for i in range(n):
        the.nth(i).click()


def _dua_vao_cum_moi(p, goc: str, usecase: str, kieu: str) -> None:
    p.click('[data-action="cum"]')
    f = p.locator("#cum-popover .cum-form")
    f.locator('[data-cum-o="goc"]').fill(goc)
    f.locator('[data-cum-o="usecase"]').fill(usecase)
    f.locator('[data-cum-o="kieu"]').fill(kieu)
    with p.expect_response(lambda r: "/video" in r.url and r.request.method == "POST"):
        f.locator("button[type=submit]").click()
    p.wait_for_function("document.getElementById('cum-head') && !document.getElementById('cum-head').hidden")


def test_tao_cum_dua_3_video_vao_va_ban_giao_mo_tab_dung_nhan(page):
    _chon(page, 3)
    _dua_vao_cum_moi(page, "Badaboum", "Dance", "  couple ")
    rail = page.inner_text("#cum-rail")
    assert "Badaboum couple" in rail
    assert page.locator("#cum-rail .cum-row.on .n").inner_text() == "3"
    assert page.locator("#cum-rail [data-cum-loc='chua'] .n").inner_text() == str(TONG - 3)
    assert page.locator("#card-grid .card").count() == 3, "đang lọc theo cụm vừa tạo"
    assert page.locator("#card-grid .cum-chip").first.inner_text() == "Badaboum couple"

    with page.context.expect_page() as tab_moi:
        with page.expect_response(lambda r: "/da-mo" in r.url):
            page.click("#cum-head [data-mo-lo='1']")
    p = _giai_ma(tab_moi.value.url)
    cum = _cum_api(page)[0]
    assert p["nhan"] == {"usecase": "Dance", "insight": "Badaboum couple", "template": "Goc",
                         "cum_id": cum["id"], "lo": {"thu": 1, "tong": 1}}
    assert len(p["items"]) == 3
    page.wait_for_function("document.querySelector('#cum-head .sent-line')")
    assert "Đã mở Creative Desk cho cụm này lúc" in page.inner_text("#cum-head")
    assert "đã tạo" not in page.inner_text("#cum-head").lower()
    assert [m["thu"] for m in _cum_api(page)[0]["lo_mo"]] == [1]


def test_popup_bi_chan_thi_khong_ghi_moc(page):
    _chon(page, 2)
    _dua_vao_cum_moi(page, "Birthday Virgo", "Portrait", "chibi")
    goi = []
    page.on("request", lambda r: goi.append(r.url) if "/da-mo" in r.url else None)
    page.evaluate("window.open = () => null")
    page.click("#cum-head [data-mo-lo='1']")
    page.wait_for_function("!document.getElementById('toast').hidden")
    assert "chặn tab" in page.inner_text("#toast")
    page.wait_for_timeout(300)
    assert goi == []
    assert _cum_api(page)[0]["lo_mo"] == []
    assert page.locator("#cum-head .sent-line").count() == 0


def test_cum_hon_30_tach_lo_va_moi_lo_mot_moc(page):
    page.click("#so-moi-trang [data-so='100']")
    page.click("#chon-trang")
    _dua_vao_cum_moi(page, "Badaboum", "Dance", "cartoon")
    head = page.inner_text("#cum-head")
    assert f"Tạo 3 bộ tự tìm (30 + 30 + 26)" in head
    assert page.locator("#cum-head .bo-row").count() == 3
    with page.context.expect_page() as tab_moi:
        with page.expect_response(lambda r: "/lo/2/da-mo" in r.url):
            page.click("#cum-head .bo-row[data-lo='2'] [data-mo-lo]")
    p = _giai_ma(tab_moi.value.url)
    assert p["nhan"]["lo"] == {"thu": 2, "tong": 3} and len(p["items"]) == 30
    page.wait_for_function("document.querySelector(\"#cum-head .bo-row[data-lo='2']\").innerText.includes('đã mở')")
    dong = {i: page.inner_text(f"#cum-head .bo-row[data-lo='{i}']") for i in (1, 2, 3)}
    assert "chưa mở" in dong[1] and "chưa mở" in dong[3]
    assert "đã mở Creative Desk lúc" in dong[2] and "Mở lại" in dong[2]
    page.evaluate("localStorage.removeItem('videodl-per-page')")


def test_popover_trung_ten_dung_lai_cum_co_san(page):
    _chon(page, 2)
    _dua_vao_cum_moi(page, "Badaboum", "Dance", "couple")
    page.click("#cum-rail [data-cum-loc='chua']")
    _chon(page, 2)
    _dua_vao_cum_moi(page, " badaboum ", "DANCE", "Couple")
    cums = _cum_api(page)
    assert len(cums) == 1, "trùng tên (hoa/thường, khoảng trắng) phải DÙNG LẠI cụm có sẵn"
    assert cums[0]["so_video"] == 4


def test_gan_sang_cum_khac_la_chuyen_va_loc_cum_ve_trang_1_giu_lua_chon(page):
    _chon(page, 2)
    _dua_vao_cum_moi(page, "Badaboum", "Dance", "couple")
    page.locator("#card-grid .card").first.click()   # chọn 1 video trong cụm A
    _dua_vao_cum_moi(page, "Badaboum", "Dance", "nhóm")
    so = {c["insight"]: c["so_video"] for c in _cum_api(page)}
    assert so == {"Badaboum couple": 1, "Badaboum nhóm": 1}

    # Đổi cụm đang lọc ⇒ về trang 1, lựa chọn GIỮ (y `sauKhiDoiBoLoc`).
    page.click("#cum-rail [data-cum-loc='tat_ca']")
    _nut = page.locator("#lib-toolbar").get_by_role("button", name="2", exact=True)
    _nut.click()
    page.locator("#card-grid .card").first.click()
    page.click("#cum-rail [data-cum-loc='chua']")
    assert "Hiện 1–40 / 84 video" in page.inner_text("#lib-pager-dem")
    assert page.inner_text("#selection-count") == "1 đã chọn"


def test_xoa_cum_dua_video_ve_chua_vao_cum(page):
    _chon(page, 3)
    _dua_vao_cum_moi(page, "Badaboum", "Dance", "couple")
    page.on("dialog", lambda d: d.accept())
    with page.expect_response(lambda r: r.request.method == "DELETE"):
        page.click("#cum-head [data-xoa-cum]")
    page.wait_for_function("document.getElementById('cum-head').hidden")
    assert _cum_api(page) == []
    assert page.locator("#cum-rail [data-cum-loc='chua'] .n").inner_text() == str(TONG)
