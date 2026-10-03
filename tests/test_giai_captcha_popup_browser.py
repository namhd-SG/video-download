"""Popup "giải xác minh trong Video Desk" — luồng thật trên TRÌNH DUYỆT (Chromium + Playwright).

Backend thật (uvicorn trên 127.0.0.1, DB tạm, cờ `VIDEODL_PROFILE_CAPTCHA` BẬT bằng env), danh
tính giả. KHÔNG có worker: test đóng vai worker bằng cách đặt `PhienGiai` (khung ảnh, trạng thái)
và đổi `trang_thai` trong DB qua đúng các hàm mà worker gọi. KHÔNG TikTok; mọi request ra ngoài
127.0.0.1 (font Google…) bị chặn ở tầng trình duyệt. Không có Playwright/Chromium thì SKIP —
đọc dòng skip trước khi tin suite xanh.

Bất biến soi ở đây (người dùng → máy chủ): `buttons` đi NGUYÊN; toạ độ theo pixel ảnh KHÔNG làm
tròn; `seq` lô liên tiếp từ 0; gesture bị bỏ (`pointercancel`/`lostpointercapture`/`blur`) ⇒ KHÔNG
có `up`; nút phải ⇒ không gửi; không có nút ×.

Đột biến phải ĐỎ (bảng ở báo cáo): làm tròn toạ độ · seq đứng yên · gửi `up` khi pointercancel ·
bỏ kiểm nút trái · bỏ kiểm vai chỉ-xem · thêm nút × · bỏ nhận diện hết phiên · SSE chỉ cho
pending/running · thẻ job hiện nút giải cho mọi job.
"""
from __future__ import annotations

import base64
import io
import socket
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from giai_captcha_http import Sse
from web import giai_captcha as gc
from web import models, profile_theo_job
from web import models_giai_captcha as mgc

NGUOI = "chu.popup@dev.local"
URL = "https://www.tiktok.com/@vi-du.kenh"
TB = "token-bbbbbbbb"          # "người khác" giữ khoá điều khiển trong test chỉ-xem
META = {"deviceWidth": 1280, "deviceHeight": 900, "pageScaleFactor": 1, "scrollOffsetX": 0, "scrollOffsetY": 0}


def _jpeg_b64() -> str:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 563), (205, 208, 206))
    d = ImageDraw.Draw(im)
    d.rectangle((230, 190, 570, 380), fill=(255, 255, 255))
    d.rectangle((250, 300, 550, 330), fill=(225, 228, 226))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=60)
    return base64.b64encode(buf.getvalue()).decode()


JPEG = _jpeg_b64()


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    import web.app as app_mod
    from web.auth import require_user

    tmp_ctx = tempfile.TemporaryDirectory(prefix="videodl-popup-")
    tmp = Path(tmp_ctx.name)
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    models.init_db(app_mod.DB_PATH)
    models.ghi_nhan_nguoi_dung(app_mod.DB_PATH, NGUOI)
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    han = time.monotonic() + 10
    while not server.started:
        assert t.is_alive() and time.monotonic() < han, "uvicorn không khởi động được"
        time.sleep(0.05)
    yield port, app_mod.DB_PATH
    server.should_exit = True
    t.join(timeout=8)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)
    tmp_ctx.cleanup()


@pytest.fixture(autouse=True)
def _co_bat(monkeypatch):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    gc._PHIEN.clear()
    yield
    gc._PHIEN.clear()


@pytest.fixture
def db(may_chu):
    _, db = may_chu
    with models._connect(db) as conn:
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'jobs'")
    return db


@pytest.fixture(scope="module")
def trinh_duyet():
    pw_api = pytest.importorskip("playwright.sync_api")
    pw = pw_api.sync_playwright().start()
    try:
        # Chặn mọi host ngoài 127.0.0.1 ngay ở tầng DNS của trình duyệt (font Google…): không dùng
        # `route` phía Python vì nó bắt MỌI request chờ vòng lặp Playwright — mà vòng đó đứng yên khi
        # test chờ bằng vòng `sleep`.
        br = pw.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"])
    except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    yield br
    br.close()
    pw.stop()


class Ghi:
    """Gom POST `/giai/chuot` và `/giai/lenh` mà trang gửi đi, cùng mã trả về."""

    def __init__(self, page):
        self.chuot: list[dict] = []
        self.lenh: list[dict] = []
        self.mat_chuot: list[int] = []
        self.token_sse: list[str] = []
        # Thứ tự lô gửi/trả và lệnh gửi, để kiểm `huy_gesture` tới SAU mọi lô của gesture.
        self.thu_tu: list[tuple[str, object]] = []
        page.on("request", self._khi_gui)
        page.on("response", self._khi_ve)

    def _khi_gui(self, r):
        if "/giai/khung" in r.url:
            self.token_sse.append(parse_qs(urlsplit(r.url).query)["token"][0])
        if r.method != "POST":
            return
        if r.url.endswith("/giai/chuot"):
            self.chuot.append(r.post_data_json)
            self.thu_tu.append(("lo_gui", r.post_data_json["seq"]))
        elif r.url.endswith("/giai/lenh"):
            self.lenh.append(r.post_data_json)
            self.thu_tu.append(("lenh_gui", r.post_data_json["lenh"]))

    def _khi_ve(self, r):
        if r.request.method == "POST" and r.url.endswith("/giai/chuot"):
            self.mat_chuot.append(r.status)
            self.thu_tu.append(("lo_ve", r.request.post_data_json["seq"]))

    def su_kien(self) -> list[dict]:
        """Mọi sự kiện đã gửi, xếp theo `seq` của lô rồi theo thứ tự trong lô."""
        return [e for lo in sorted(self.chuot, key=lambda x: x["seq"]) for e in lo["su_kien"]]


def _mo(trinh_duyet, may_chu, *, rong=1001, cao=1000):
    """Trả (page, ctx). Chỉ 127.0.0.1 (chặn ở cấp trình duyệt, xem `trinh_duyet`)."""
    ctx = trinh_duyet.new_context(viewport={"width": rong, "height": cao})
    page = ctx.new_page()
    return page, ctx


@pytest.fixture
def mo_trang(trinh_duyet, may_chu):
    """`mo_trang(**viewport)` ⇒ (page, ghi) đã vào Video Desk; đóng context khi test xong."""
    dong = []

    def _mo_trang(rong=1001, cao=1000, truoc=None):
        page, ctx = _mo(trinh_duyet, may_chu, rong=rong, cao=cao)
        dong.append(ctx)
        ghi = Ghi(page)
        if truoc:
            truoc(page)
        page.goto(f"http://127.0.0.1:{may_chu[0]}/")
        page.wait_for_selector("#queue-list li")
        return page, ghi

    yield _mo_trang
    for c in dong:
        c.close()


def tao_job(db, trang_thai="cho_xac_minh", ly_do="feed_rong", so_lan=0, tong=20):
    jid = models.create_job(db, URL, tong, NGUOI)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET trang_thai = ?, vao_trang_thai_luc = ?, so_lan_giai_ngay = ?, "
                     "ly_do_dung = ? WHERE id = ?", (trang_thai, models._now(), so_lan, ly_do, jid))
    return jid


def cho_trang(page, dieu_kien, giay=8.0) -> bool:
    """Chờ `dieu_kien()` mà vẫn để Playwright xử lý sự kiện (listener Python chỉ chạy trong lời gọi
    Playwright — vòng `sleep` thuần làm đứng cả request/response/console)."""
    han = time.monotonic() + giay
    while time.monotonic() < han:
        if dieu_kien():
            return True
        page.wait_for_timeout(30)
    return dieu_kien()


def den_dang_giai(page, db, jid):
    """Đóng vai worker: popup đã nối SSE ⇒ job sang `dang_giai`, có phiên + khung ảnh đầu tiên."""
    assert cho_trang(page, lambda: (gc.lay_phien(jid) is not None and gc.lay_phien(jid).so_sse >= 1)), "popup chưa nối SSE"
    assert mgc.chuyen_trang_thai(db, jid, ("cho_giai", "dang_mo"), "dang_giai")
    phien = gc.lay_phien(jid)
    phien.worker_giu = True
    phien.dat_trang_thai("dang_giai", 250)
    phien.dat_khung(JPEG, META)
    return phien


def mo_popup_dang_giai(mo_trang, db, **kw):
    """Job `cho_xac_minh` → bấm "Tôi giải ngay" → popup → (worker giả) `dang_giai` + khung. Trả (page, ghi, jid, phien)."""
    jid = tao_job(db)
    page, ghi = mo_trang(**kw)
    page.click(".nut-giai-ngay")
    page.wait_for_selector("#gc-bg")
    phien = den_dang_giai(page, db, jid)
    page.wait_for_function("() => { const a = document.querySelector('#gc-anh'); return a && a.naturalWidth === 800; }")
    page.wait_for_selector(".gc-frame.dieu-khien")
    return page, ghi, jid, phien


def khung_rect(page) -> dict:
    return page.evaluate("""() => { const r = document.querySelector('#gc-anh').getBoundingClientRect();
        return {x: r.x, y: r.y, w: r.width, h: r.height}; }""")


def doi_gui(page, ms=300):
    page.wait_for_timeout(ms)   # gom lô 40 ms + một vòng HTTP


# ---------------------------------------------------------------------------
# Thẻ job ở bốn bước giải
# ---------------------------------------------------------------------------

def test_the_job_bon_buoc_giai_co_nhan_nut_va_cau_dung(mo_trang, db):
    a = tao_job(db, "cho_xac_minh", "khong_do_duoc_feed", so_lan=1)
    b = tao_job(db, "cho_giai", "feed_rong")
    c = tao_job(db, "dang_mo", "het_gio_giai")
    d = tao_job(db, "dang_giai", "feed_rong")
    e = tao_job(db, "cancelled", "het_gio_giai")
    page, _ = mo_trang()

    def the(jid):
        return page.locator(f"#job-{jid}")

    # cho_xac_minh: nhãn, nút "Tôi giải ngay" kèm số lượt, câu riêng trỏ tới nút, Rút lượt.
    assert the(a).locator(".status-badge").inner_text() == "Cần xác minh"
    assert the(a).locator(".nut-giai-ngay").count() == 1
    assert "còn 2 lần" in the(a).locator(".giai-luot").inner_text()
    assert "không tự giải" in the(a).locator(".stop-reason").inner_text()
    assert the(a).locator("[data-huy]").count() == 1
    assert "24 giờ" in the(a).locator(".xn-note").inner_text()
    # cho_giai: nhãn, mở lại cửa sổ, rút được; KHÔNG câu dừng cũ (lý do cũ còn nguyên trong DB).
    assert the(b).locator(".status-badge").inner_text() == "Chờ mở trang giải"
    assert the(b).locator("[data-mo-giai]").count() == 1 and the(b).locator("[data-huy]").count() == 1
    assert the(b).locator(".stop-reason").count() == 0
    # dang_mo / dang_giai: có nút mở lại cửa sổ, KHÔNG có Rút lượt (máy chủ trả 409), không "Tôi giải ngay".
    for jid, nhan in ((c, "Đang mở trang giải"), (d, "Đang giải")):
        assert the(jid).locator(".status-badge").inner_text() == nhan
        assert the(jid).locator("[data-mo-giai]").count() == 1
        assert the(jid).locator("[data-huy]").count() == 0
        assert the(jid).locator(".nut-giai-ngay").count() == 0
        assert the(jid).locator(".stop-reason").count() == 0
    # Job đã rút giữ mã cũ trong DB nhưng thẻ không nhắc lại chuyện đã qua.
    assert the(e).locator(".stop-reason").count() == 0
    # Hết lượt ⇒ nút khoá, nói đúng lý do.
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET so_lan_giai_ngay = ? WHERE id = ?", (gc.TRAN_GIAI_NGAY, a))
    page.reload()
    page.wait_for_selector(f"#job-{a} .nut-giai-ngay")
    assert page.locator(f"#job-{a} .nut-giai-ngay").is_disabled()
    assert "đã dùng đủ" in page.locator(f"#job-{a} .giai-luot").inner_text()


def test_rut_luot_o_cho_xac_minh_thanh_da_rut(mo_trang, db):
    """"Rút lượt" trên thẻ `cho_xac_minh` đi qua DELETE thật: job `cancelled`, thẻ hiện "Đã rút", nút giải biến mất."""
    jid = tao_job(db, "cho_xac_minh", "feed_rong")
    page, _ = mo_trang()
    page.click(f"#job-{jid} [data-huy]")
    page.wait_for_function("(id) => document.querySelector(`#job-${id} .status-badge`).textContent === 'Đã rút'", arg=jid)
    assert page.locator(f"#job-{jid} .nut-giai-ngay").count() == 0
    assert models.get_job(db, jid)["trang_thai"] == "cancelled"


def test_co_tat_the_job_nhu_cu_khong_co_nut_giai(mo_trang, db, monkeypatch):
    """Cờ TẮT: job `failed` với `feed_rong` trông y như trước — không nhãn mới, không nút giải."""
    monkeypatch.delenv(profile_theo_job.ENV_PROFILE_CAPTCHA, raising=False)
    jid = tao_job(db, "failed", "feed_rong")
    xong = tao_job(db, "done", None)
    page, _ = mo_trang()
    the = page.locator(f"#job-{jid}")
    assert the.locator(".status-badge").inner_text() == "Lỗi"
    assert "RỖNG" in the.locator(".stop-reason").inner_text()
    assert page.locator(".nut-giai-ngay, [data-mo-giai], .can-xn, .xn-note, .giai-luot").count() == 0
    assert page.locator(f"#job-{xong}[data-status=done]").count() == 1
    assert page.locator("#gc-bg").count() == 0


def test_sse_tien_do_giu_cho_trang_thai_moi(mo_trang, db):
    """Job `cho_xac_minh` vẫn có luồng `/events`: đổi trạng thái ở DB lên thẻ trong ~1 s, không phải chờ nhịp poll 5 s."""
    jid = tao_job(db, "cho_xac_minh")
    mo_ra = []
    page, _ = mo_trang(truoc=lambda p: p.on("request", lambda r: mo_ra.append(r.url) if r.url.endswith("/events") else None))
    assert cho_trang(page, lambda: any(u.endswith(f"/jobs/{jid}/events") for u in mo_ra), 3)
    t0 = time.monotonic()
    assert mgc.chuyen_trang_thai(db, jid, "cho_xac_minh", "cho_giai")
    page.wait_for_function(
        "(id) => document.querySelector(`#job-${id} .status-badge`).textContent === 'Chờ mở trang giải'",
        arg=jid, timeout=3500)
    assert time.monotonic() - t0 < 3.5


# ---------------------------------------------------------------------------
# Popup: mở, chuột, bỏ gesture
# ---------------------------------------------------------------------------

def test_popup_gui_lo_buttons_nguyen_toa_do_khong_lam_tron_seq_lien_tiep(mo_trang, db):
    page, ghi, jid, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    assert r["x"] % 1 != 0, "viewport lẻ để khung nằm ở nửa pixel — nếu không, làm tròn không phân định được"
    diem = [(r["x"] + 120.5, r["y"] + 140.25)]                       # rê chuột (buttons 0)
    keo = [(r["x"] + 120.5 + 17.3 * i, r["y"] + 140.25 + 3.7 * i) for i in range(1, 9)]
    page.mouse.move(*diem[0])
    page.mouse.down()
    for p in keo:
        page.mouse.move(*p)
    page.mouse.up()
    doi_gui(page)

    lo = sorted(ghi.chuot, key=lambda x: x["seq"])
    assert lo and [x["seq"] for x in lo] == list(range(len(lo))), "seq phải liên tiếp từ 0"
    assert len({x["token"] for x in lo}) == 1
    assert all(x["khung_w"] == 800 for x in lo)
    assert ghi.mat_chuot and set(ghi.mat_chuot) == {200}
    ev = ghi.su_kien()
    # rê (buttons 0) · down (1) · 8 move (1) · up (0), đúng thứ tự người tạo
    assert [(e["k"], e["buttons"]) for e in ev] == (
        [("move", 0), ("down", 1)] + [("move", 1)] * 8 + [("up", 0)])
    r = khung_rect(page)   # đo lại ngay trước khi so (bố cục đã ổn định)
    he = 800 / r["w"]
    mong = diem + [diem[0]] + keo + [keo[-1]]
    for e, (cx, cy) in zip(ev, mong):
        assert e["x"] == pytest.approx((cx - r["x"]) * he, abs=1e-3)
        assert e["y"] == pytest.approx((cy - r["y"]) * he, abs=1e-3)
    assert any(abs(e["x"] - round(e["x"])) > 1e-3 for e in ev), "toàn số nguyên ⇒ nghi bị làm tròn"
    ts = [e["t"] for e in ev]
    assert ts == sorted(ts) and ts[-1] > ts[0] > 0   # e.timeStamp thật, không phải 0


def test_popup_khung_thu_nho_van_doi_dung_don_vi(mo_trang, db):
    """Cửa sổ hẹp ⇒ khung hiển thị < 800 px: x,y vẫn theo pixel ẢNH (nhân naturalWidth / chiều rộng hiển thị)."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db, rong=700, cao=1000)
    r = khung_rect(page)
    assert r["w"] < 790
    page.mouse.move(r["x"] + 50.5, r["y"] + 60.5)
    page.mouse.down()
    page.mouse.move(r["x"] + 150.5, r["y"] + 90.5)
    page.mouse.up()
    doi_gui(page)
    ev = ghi.su_kien()
    he = 800 / r["w"]
    assert ev[0]["x"] == pytest.approx(50.5 * he, abs=1e-3)
    assert ev[-1]["x"] == pytest.approx(150.5 * he, abs=1e-3) and ev[-1]["y"] == pytest.approx(90.5 * he, abs=1e-3)
    assert he > 1.0 and all(l["khung_w"] == 800 for l in ghi.chuot)


@pytest.mark.parametrize("cach", ["pointercancel", "lostpointercapture", "blur"])
def test_bo_gesture_khong_gui_up(mo_trang, db, cach):
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.mouse.move(r["x"] + 130, r["y"] + 110)
    doi_gui(page)
    truoc = len(ghi.su_kien())
    if cach == "blur":
        page.evaluate("() => window.dispatchEvent(new Event('blur'))")
    else:
        page.evaluate("(ten) => document.querySelector('#gc-khung').dispatchEvent(new PointerEvent(ten, {pointerId: 1, bubbles: true}))",
                      cach)
    page.mouse.move(r["x"] + 160, r["y"] + 120)    # phần còn lại của gesture đã bỏ
    page.mouse.up()
    doi_gui(page)
    ev = ghi.su_kien()
    assert len(ev) == truoc, "sau khi bỏ gesture không được gửi thêm sự kiện nào của gesture đó"
    assert "up" not in [e["k"] for e in ev]
    assert "Thao tác bị ngắt" in page.locator("#gc-note").inner_text()
    # Bỏ gesture không làm hỏng popup: lần nhấn kế tiếp là gesture mới.
    page.mouse.move(r["x"] + 200, r["y"] + 200)
    page.mouse.down()
    page.mouse.up()
    doi_gui(page)
    assert [e["k"] for e in ghi.su_kien()].count("down") == 2
    assert [e["k"] for e in ghi.su_kien()].count("up") == 1
    # Máy chủ chỉ tự huỷ khi HỤT seq; popup im lặng ⇒ nút kẹt nhấn. Popup phải báo `huy_gesture` ĐÚNG
    # một lần (gesture thứ hai kết thúc bằng `up` thật ⇒ không báo) và SAU khi mọi lô của gesture bị
    # bỏ đã được trả lời — lô `down` tới sau lệnh huỷ thì nút lại kẹt (R15b).
    # ĐỘT BIẾN: bỏ lời gọi `baoHuyGesture` ⇒ ĐỎ; gửi lệnh trước khi chờ lô đang bay ⇒ ĐỎ.
    huy = [l for l in ghi.lenh if l["lenh"] == "huy_gesture"]
    assert len(huy) == 1 and huy[0]["token"] == ghi.token_sse[-1]
    vi_tri = ghi.thu_tu.index(("lenh_gui", "huy_gesture"))
    gui_truoc = [s for k, s in ghi.thu_tu[:vi_tri] if k == "lo_gui"]
    assert gui_truoc, "phải có lô chứa `down` gửi trước lệnh huỷ"
    assert all(("lo_ve", s) in ghi.thu_tu[:vi_tri] for s in gui_truoc), \
        "huy_gesture gửi khi còn lô chưa được trả lời"


def test_huy_gesture_ngay_khi_lo_con_trong_bo_dem_van_toi_sau_moi_lo(mo_trang, db):
    """Huỷ NGAY sau khi kéo (lô còn trong bộ đệm 40 ms / đang bay): popup phải xả bộ đệm, chờ mọi lô
    được trả lời rồi mới gửi `huy_gesture`. ĐỘT BIẾN: bỏ `await Promise.allSettled(...)` ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.mouse.move(r["x"] + 130, r["y"] + 110)
    page.evaluate("() => window.dispatchEvent(new Event('blur'))")
    assert cho_trang(page, lambda: any(l["lenh"] == "huy_gesture" for l in ghi.lenh), 5)
    doi_gui(page)
    vi_tri = ghi.thu_tu.index(("lenh_gui", "huy_gesture"))
    gui_truoc = [s for k, s in ghi.thu_tu[:vi_tri] if k == "lo_gui"]
    assert any(e["k"] == "down" for lo in ghi.chuot if lo["seq"] in gui_truoc for e in lo["su_kien"]), \
        "lô chứa `down` phải được gửi TRƯỚC lệnh huỷ"
    assert all(("lo_ve", s) in ghi.thu_tu[:vi_tri] for s in gui_truoc), \
        "huy_gesture gửi khi còn lô chưa được trả lời"
    assert [l["lenh"] for l in ghi.lenh] == ["huy_gesture"]


def tre_truoc_khi_gui(page, duong: str, ms: int) -> None:
    """Hoãn mọi `fetch` tới URL chứa `duong` thêm `ms` TRƯỚC khi gửi — mở cửa sổ đua một cách xác định
    (request ra mạng muộn, nên bộ ghi `Ghi` thấy đúng thứ tự gửi thật)."""
    page.evaluate("""([duong, ms]) => { const f = window.fetch;
        window.fetch = async (u, o) => { if (String(u).includes(duong)) await new Promise(r => setTimeout(r, ms));
                                         return f(u, o); }; }""", [duong, ms])


def test_khong_mo_gesture_moi_khi_lenh_huy_chua_tra_loi(mo_trang, db):
    """Review F3: máy chủ huỷ "gesture đang dở" lúc lệnh TỚI ⇒ `down` mới gửi khi lệnh còn bay có thể bị
    chính lệnh đó xoá. Popup không mở gesture mới cho tới khi lệnh được trả lời.
    ĐỘT BIẾN: bỏ chặn `P.dangHuy` ở `khiNhan` ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    tre_truoc_khi_gui(page, "/giai/lenh", 600)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.mouse.move(r["x"] + 130, r["y"] + 110)
    doi_gui(page)
    page.evaluate("() => window.dispatchEvent(new Event('blur'))")
    page.mouse.up()
    page.mouse.move(r["x"] + 200, r["y"] + 200)        # lần nhấn mới TRONG lúc lệnh huỷ còn treo
    page.mouse.down()
    page.mouse.move(r["x"] + 220, r["y"] + 200)
    page.mouse.up()
    doi_gui(page)
    assert [e["k"] for e in ghi.su_kien()].count("down") == 1, "không được mở gesture mới khi lệnh huỷ chưa trả lời"
    assert cho_trang(page, lambda: [l["lenh"] for l in ghi.lenh] == ["huy_gesture"], 5)
    page.wait_for_timeout(700)
    page.mouse.move(r["x"] + 300, r["y"] + 300)        # lệnh đã trả lời ⇒ nhấn lại được
    page.mouse.down()
    page.mouse.up()
    doi_gui(page)
    assert [e["k"] for e in ghi.su_kien()].count("down") == 2


def test_lenh_da_giai_gui_sau_moi_lo_dang_bay(mo_trang, db):
    """Review F4: lô chứa `up` cuối còn đang bay khi bấm "Đã giải xong" ⇒ lệnh phải gửi SAU khi lô đó
    được trả lời (máy chủ thôi phát sau lệnh). ĐỘT BIẾN: bỏ `await Promise.allSettled` ở `guiLenh` ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    tre_truoc_khi_gui(page, "/giai/chuot", 400)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.mouse.move(r["x"] + 130, r["y"] + 110)
    page.mouse.up()
    page.click("#gc-actions button:has-text('Đã giải xong')")
    assert cho_trang(page, lambda: len(ghi.lenh) == 1, 5)
    vi_tri = ghi.thu_tu.index(("lenh_gui", "da_giai"))
    seq_up = [lo["seq"] for lo in ghi.chuot if any(e["k"] == "up" for e in lo["su_kien"])]
    assert seq_up and all(("lo_ve", s) in ghi.thu_tu[:vi_tri] for s in seq_up), \
        "da_giai gửi khi lô chứa `up` chưa được trả lời"


def test_nut_phai_khong_gui_gi(mo_trang, db):
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.mouse.move(r["x"] + 100, r["y"] + 100)      # rê (buttons 0) — người tạo, được gửi
    page.mouse.down(button="right")
    page.mouse.move(r["x"] + 140, r["y"] + 120)
    page.mouse.up(button="right")
    page.mouse.down(button="middle")
    page.mouse.up(button="middle")
    doi_gui(page)
    ev = ghi.su_kien()
    assert [e["k"] for e in ev] == ["move"] and ev[0]["buttons"] == 0
    assert "Thao tác bị ngắt" not in page.locator("#gc-note").inner_text()
    assert ghi.lenh == [], "chưa từng có gesture nút trái ⇒ không báo huy_gesture" 


def test_chi_xem_khong_gui_chuot_va_khoa_nut(mo_trang, db, may_chu):
    jid = tao_job(db, "cho_giai", "feed_rong")
    giu = Sse(may_chu[0], jid, TB)       # "người khác" nối trước ⇒ giữ quyền điều khiển
    try:
        assert giu.status == 200
        giu.doc("trang_thai")
        page, ghi = mo_trang()
        page.click(f"#job-{jid} [data-mo-giai]")
        page.wait_for_selector("#gc-bg")
        assert cho_trang(page, lambda: gc.lay_phien(jid).so_sse >= 2)
        phien = gc.lay_phien(jid)
        assert mgc.chuyen_trang_thai(db, jid, "cho_giai", "dang_giai")
        phien.worker_giu = True
        phien.dat_trang_thai("dang_giai", 250)
        phien.dat_khung(JPEG, META)
        page.wait_for_selector(".gc-over.xem")
        assert page.locator(".gc-role").inner_text() == "Chỉ xem"
        assert page.locator("#gc-actions button[disabled]").count() == 2
        r = khung_rect(page)
        page.mouse.move(r["x"] + 100, r["y"] + 100)
        page.mouse.down()
        page.mouse.move(r["x"] + 150, r["y"] + 100)
        page.mouse.up()
        doi_gui(page)
        assert ghi.chuot == [], "người chỉ xem không được gửi chuột"
        # Người chỉ xem đóng được popup (không có × nhưng có "Đóng"); người giữ khoá vẫn giữ.
        page.click("#gc-actions [data-dong]")
        assert page.locator("#gc-bg").count() == 0
        assert cho_trang(page, lambda: gc.lay_phien(jid).so_sse == 1)
        assert gc.lay_phien(jid).token == TB
    finally:
        giu.dong_ket_noi()


def test_popup_khong_co_nut_x_va_khong_dong_bang_esc(mo_trang, db):
    page, ghi, jid, _ = mo_popup_dang_giai(mo_trang, db)
    assert page.locator("#gc-x").count() == 0
    assert page.locator("[aria-label*='Đóng popup'], .gc-x").count() == 0
    chu_nut = [t.strip() for t in page.locator("#gc-bg button").all_inner_texts()]
    assert chu_nut == ["Đã giải xong", "Dừng job"]
    assert "×" not in page.locator("#gc-bg").inner_text()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.locator("#gc-bg").count() == 1


def test_bi_ngat_hien_ghi_chu_va_het_gio_cho_giai_lai(mo_trang, db):
    page, ghi, jid, phien = mo_popup_dang_giai(mo_trang, db)
    phien.so_lan_tai_lai = 1
    phien.thong_bao("bi_ngat", ly_do="thieu_lo", so_lan_tai_lai=1)
    page.wait_for_function("() => document.querySelector('#gc-note').textContent.includes('Thao tác bị ngắt')")
    assert "1 lần nữa" in page.locator("#gc-note").inner_text()
    # Hết giờ: worker đưa job về `cho_xac_minh` rồi đóng phiên.
    assert mgc.chuyen_trang_thai(db, jid, "dang_giai", "cho_xac_minh", ly_do=gc.LD_HET_GIO)
    phien.dong("cho_xac_minh", gc.LD_HET_GIO)
    page.wait_for_selector(".gc-closed")
    assert "Hết thời gian giải" in page.locator(".gc-closed h4").inner_text()
    assert "còn 2 lần" in page.locator("[data-giai-lai]").inner_text()
    assert page.locator("#gc-timer").inner_text().endswith("0:00")
    # "Tôi giải ngay (còn 2 lần)" mở popup mới với token mới.
    page.click("[data-giai-lai]")
    page.wait_for_function("() => document.querySelectorAll('#gc-bg').length === 1 && !document.querySelector('.gc-closed')")
    assert db_so_lan(db, jid) == 2


def db_so_lan(db, jid):
    with models._connect(db) as conn:
        return conn.execute("SELECT so_lan_giai_ngay FROM jobs WHERE id = ?", (jid,)).fetchone()[0]


def test_phien_het_han_giua_chung_bao_dang_nhap_lai(mo_trang, db):
    page, ghi, jid, _ = mo_popup_dang_giai(mo_trang, db)
    # Cloudflare Access hết phiên ⇒ 302 sang trang đăng nhập; `redirect: "manual"` cho opaqueredirect.
    page.route("**/giai/chuot", lambda route: route.fulfill(status=302, headers={"Location": "https://dang-nhap.invalid/"}))
    r = khung_rect(page)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.mouse.up()
    page.wait_for_selector(".gc-closed")
    assert "Phiên đăng nhập đã hết" in page.locator(".gc-closed h4").inner_text()
    assert page.locator("[data-tai-lai-trang]").count() == 1
    assert page.locator("[data-dong]").count() == 1
    # Đóng popup (không nhả lệnh nào): trang trên máy chủ vẫn do máy chủ tự đóng sau 5 phút.
    page.click("[data-dong]")
    assert page.locator("#gc-bg").count() == 0


@pytest.mark.parametrize("lenh, nhan", [("da_giai", "Đã giải xong"), ("dung", "Dừng job")])
def test_nut_lenh_gui_token_va_dong_popup_khi_ket_thuc(mo_trang, db, lenh, nhan):
    page, ghi, jid, phien = mo_popup_dang_giai(mo_trang, db)
    page.click(f"#gc-actions button:has-text('{nhan}')")
    assert cho_trang(page, lambda: len(ghi.lenh) == 1, 5)
    assert ghi.lenh[0]["lenh"] == lenh and ghi.lenh[0]["token"] == ghi.token_sse[-1]
    # Bấm đúp không gửi lệnh thứ hai.
    page.wait_for_timeout(150)
    assert page.locator("#gc-actions button[disabled]").count() == 2
    # Worker làm theo lệnh rồi đóng phiên.
    if lenh == "da_giai":
        assert mgc.chuyen_trang_thai(db, jid, "dang_giai", "running", ly_do=None)
        phien.dong("running")
    else:
        assert mgc.chuyen_trang_thai(db, jid, "dang_giai", "failed", ly_do=gc.LD_DUNG_KHONG_CAPTCHA)
        phien.dong("failed", gc.LD_DUNG_KHONG_CAPTCHA)
    page.wait_for_function("() => !document.querySelector('#gc-bg')", timeout=5000)
    assert len(ghi.lenh) == 1


def test_goi_y_khong_thay_captcha_sau_mot_luc_khong_thao_tac(mo_trang, db):
    page, ghi, jid, _ = mo_popup_dang_giai(mo_trang, db)
    assert "Kéo/bấm trực tiếp" in page.locator("#gc-note").inner_text()
    page.clock.install()
    page.clock.run_for(16000)
    page.wait_for_function("() => document.querySelector('#gc-note').textContent.includes('Không thấy captcha?')")
    # Bấm chuột là hết gợi ý.
    r = khung_rect(page)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.mouse.up()
    page.wait_for_function("() => document.querySelector('#gc-note').textContent.includes('Kéo/bấm trực tiếp')")
