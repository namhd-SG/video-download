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
        elif r.request.method == "POST" and r.url.endswith("/giai/lenh"):
            self.thu_tu.append(("lenh_ve", r.request.post_data_json["lenh"]))

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
    # Bỏ gesture không làm hỏng popup: lần nhấn kế tiếp là gesture mới. Chờ lệnh huỷ được trả lời trước — trong
    # lúc huỷ còn bay popup CHẶN chuột (ĐP-728 A1) và cú nhấn bị bỏ đúng thiết kế; chờ cố định thì chập chờn
    # khi máy chậm (huỷ về sau ~300 ms).
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5)
    page.mouse.move(r["x"] + 200, r["y"] + 200)
    page.mouse.down()
    page.mouse.up()
    doi_gui(page)
    assert [e["k"] for e in ghi.su_kien()].count("down") == 2
    assert [e["k"] for e in ghi.su_kien()].count("up") == 1
    # Máy chủ chỉ tự huỷ khi HỤT seq; popup im lặng ⇒ nút kẹt nhấn. Popup phải báo `huy_gesture` ĐÚNG
    # một lần (gesture thứ hai kết thúc bằng `up` thật ⇒ không báo), mang `den_seq` = số lô đã cấp lúc đó
    # (lô tới muộn hơn lệnh bị máy chủ bỏ — luật B). ĐỘT BIẾN: bỏ lời gọi `baoHuyGesture` ⇒ ĐỎ.
    huy = [l for l in ghi.lenh if l["lenh"] == "huy_gesture"]
    assert len(huy) == 1 and huy[0]["token"] == ghi.token_sse[-1]
    vi_tri = ghi.thu_tu.index(("lenh_gui", "huy_gesture"))
    gui_truoc = [s for k, s in ghi.thu_tu[:vi_tri] if k == "lo_gui"]
    assert gui_truoc and huy[0]["den_seq"] == max(gui_truoc) + 1

def tre_truoc_khi_gui(page, duong: str, ms: int, chua: str = "", so_lan: int = 10**6) -> None:
    """Hoãn `fetch` tới URL chứa `duong` (và body chứa `chua`, tối đa `so_lan` lần đầu) thêm `ms` TRƯỚC
    khi gửi — mở cửa sổ đua một cách xác định (request ra mạng muộn, nên `Ghi` thấy đúng thứ tự gửi
    thật). Chỉ nhắm đúng request cần hoãn: hoãn cả request đối chứng thì chính bộ hoãn che thứ tự."""
    page.evaluate("""([duong, ms, chua, soLan]) => { const f = window.fetch; let n = 0;
        window.fetch = async (u, o) => {
            if (String(u).includes(duong) && String((o && o.body) || "").includes(chua) && n < soLan) {
                n += 1; await new Promise(r => setTimeout(r, ms));
            }
            return f(u, o); }; }""", [duong, ms, chua, so_lan])


def chan_lenh_huy(page, so_lan: int, *, treo: bool = False) -> list:
    """`so_lan` lệnh `huy_gesture` đầu tiên: trả 500 (hoặc TREO — không bao giờ trả lời, `treo=True`).
    Đi qua `page.route` nên request vẫn hiện trong `Ghi`. Trả list các route đang treo (giữ tham chiếu)."""
    dem, treo_ds = {"n": 0}, []

    def xu_ly(route):
        if "huy_gesture" in (route.request.post_data or "") and dem["n"] < so_lan:
            dem["n"] += 1
            if treo:
                treo_ds.append(route)      # không fulfill/continue ⇒ request đứng tới khi popup tự huỷ
                return
            route.fulfill(status=500, content_type="application/json", body='{"detail": "giả lập lỗi"}')
            return
        route.continue_()

    page.route("**/giai/lenh", xu_ly)
    return treo_ds


def _keo_roi_blur(page, r, x=100):
    page.mouse.move(r["x"] + x, r["y"] + 100)
    page.mouse.down()
    page.mouse.move(r["x"] + x + 30, r["y"] + 110)
    doi_gui(page)
    page.evaluate("() => window.dispatchEvent(new Event('blur'))")


def _so(ghi, k):
    return [e["k"] for e in ghi.su_kien()].count(k)


def test_dang_huy_chan_moi_su_kien_cu_nhan_trong_luc_do_bi_bo_va_bao(mo_trang, db):
    """ĐP-728 A1: từ lúc bỏ gesture tới khi `huy_gesture` trả 200, popup BỎ MỌI sự kiện chuột/wheel
    (cả hover). Cú nhấn trong lúc đó bị bỏ (đánh đổi đã chốt) và có chữ báo. Huỷ xong ⇒ nhấn lại chạy
    bình thường. ĐỘT BIẾN: bỏ chặn ở `xaLo` ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    tre_truoc_khi_gui(page, "/giai/lenh", 600, chua="huy_gesture")
    _keo_roi_blur(page, r)
    truoc = len(ghi.su_kien())
    page.mouse.up()
    page.mouse.move(r["x"] + 200, r["y"] + 200)          # hover + cú nhấn mới khi lệnh huỷ còn treo
    page.mouse.down()
    page.mouse.move(r["x"] + 220, r["y"] + 200)
    page.mouse.up()
    page.mouse.wheel(0, 120)
    doi_gui(page)
    assert "đang huỷ thao tác cũ" in page.locator("#gc-note").inner_text()
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5)
    doi_gui(page)
    assert len(ghi.su_kien()) == truoc, "không sự kiện nào được gửi khi còn đang huỷ"
    page.mouse.move(r["x"] + 300, r["y"] + 300)
    page.mouse.down()
    page.mouse.up()
    doi_gui(page)
    assert _so(ghi, "down") == 2 and _so(ghi, "up") == 1


def test_giu_nut_xuyen_qua_luc_huy_truot_roi_tha_khong_gui_gi(mo_trang, db):
    """Review #49 vòng 2 MUST-FIX: huỷ trượt hẳn (500 × 4) trong lúc người VẪN GIỮ nút, rồi thả ⇒ 0 sự
    kiện tới máy chủ (không `up` nào hoàn tất cú kéo cũ). Cú nhấn kế tiếp chỉ để thử huỷ lại (bị bỏ);
    huỷ được rồi thì nhấn lại chạy bình thường. ĐỘT BIẾN: bỏ chặn ở `xaLo` ⇒ ĐỎ; huỷ trượt mà mở chặn
    ⇒ ĐỎ; bỏ thử-huỷ-lại ở `khiNhan` ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    chan_lenh_huy(page, 4)
    _keo_roi_blur(page, r)
    truoc = len(ghi.su_kien())
    page.mouse.move(r["x"] + 160, r["y"] + 120)          # vẫn giữ nút
    assert cho_trang(page, lambda: [l["lenh"] for l in ghi.lenh].count("huy_gesture") == 4, 6)
    assert cho_trang(page, lambda: "chưa báo được máy chủ" in page.locator("#gc-note").inner_text(), 3)
    page.mouse.move(r["x"] + 180, r["y"] + 120)
    page.mouse.up()                                      # thả SAU khi huỷ trượt
    page.mouse.move(r["x"] + 190, r["y"] + 140)          # hover
    doi_gui(page)
    assert len(ghi.su_kien()) == truoc, "huỷ trượt: không sự kiện nào được tới máy chủ"
    page.mouse.down()                                    # chỉ để thử huỷ lại — bị bỏ
    page.mouse.up()
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu[-1:], 5)
    doi_gui(page)
    assert [l["lenh"] for l in ghi.lenh].count("huy_gesture") == 5 and len(ghi.su_kien()) == truoc
    page.mouse.move(r["x"] + 300, r["y"] + 300)
    page.mouse.down()
    page.mouse.up()
    doi_gui(page)
    assert _so(ghi, "down") == 2 and _so(ghi, "up") == 1



def test_huy_truot_roi_may_chu_bao_bi_ngat_van_hien_goi_y_nhan_de_thu_lai(mo_trang, db):
    """Review #49 NIT-4: huỷ trượt hẳn (500 × 4) ⇒ chữ "nhấn để thử lại"; rồi SSE `bi_ngat` của máy chủ
    tới (đổi `loai` thành "may_chu") ⇒ chuột VẪN bị chặn nên chữ đó phải còn, không bị thay bằng chữ
    "trang đã tải lại". Chờ ĐIỀU KIỆN (bộ đếm `bi_ngat` gắn vào EventSource trước popup), không chờ N ms.
    ĐỘT BIẾN: kiểm `huyTruot` chỉ khi loai === "cuc_bo" (như trước) ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_dem_bi_ngat(mo_trang, db)
    r = khung_rect(page)
    chan_lenh_huy(page, 4)
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: [l["lenh"] for l in ghi.lenh].count("huy_gesture") == 4, 6)
    assert cho_trang(page, lambda: "chưa báo được máy chủ" in page.locator("#gc-note").inner_text(), 3)
    phien.thong_bao("bi_ngat", ly_do="thieu_lo", so_lan_tai_lai=1)
    assert cho_trang(page, lambda: page.evaluate("() => window.__biNgat") == 1, 3)
    note = page.locator("#gc-note").inner_text()
    assert "chưa báo được máy chủ" in note and "Nhấn vào ảnh để thử lại" in note, note


def _mo_popup_dem_bi_ngat(mo_trang, db):
    """Như `mo_popup_dang_giai` nhưng gắn bộ đếm `bi_ngat` vào EventSource TRƯỚC khi popup nối SSE,
    để test chờ ĐIỀU KIỆN "popup đã xử lý `bi_ngat`" thay vì chờ N ms."""
    jid = tao_job(db)
    page, ghi = mo_trang()
    page.evaluate("""() => { const ES = window.EventSource; window.__biNgat = 0;
        window.EventSource = function (u, o) { const es = new ES(u, o);
            es.addEventListener('bi_ngat', () => { window.__biNgat += 1; }); return es; };
        window.EventSource.prototype = ES.prototype; }""")
    page.click(".nut-giai-ngay")
    page.wait_for_selector("#gc-bg")
    phien = den_dang_giai(page, db, jid)
    page.wait_for_selector(".gc-frame.dieu-khien")
    return page, ghi, phien


def test_dang_huy_roi_may_chu_bao_bi_ngat_van_hien_chu_dang_huy(mo_trang, db):
    """Cùng gốc với NIT-4, nhánh còn lại: lệnh huỷ còn TREO (chuột đang bị chặn) mà SSE `bi_ngat` của
    máy chủ tới ⇒ chữ "đang huỷ thao tác cũ" phải còn, không bị thay bằng "trang đã tải lại".
    ĐỘT BIẾN: kiểm `chanChuot` chỉ khi loai === "cuc_bo" ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_dem_bi_ngat(mo_trang, db)
    r = khung_rect(page)
    tre_truoc_khi_gui(page, "/giai/lenh", 3000, chua="huy_gesture")
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: "đang huỷ thao tác cũ" in page.locator("#gc-note").inner_text(), 3)
    phien.thong_bao("bi_ngat", ly_do="thieu_lo", so_lan_tai_lai=1)
    assert cho_trang(page, lambda: page.evaluate("() => window.__biNgat") == 1, 3)
    assert not any(l["lenh"] == "huy_gesture" for l in ghi.lenh), "lệnh huỷ phải còn đang treo lúc kiểm"
    note = page.locator("#gc-note").inner_text()
    assert "đang huỷ thao tác cũ" in note, note



def test_lo_can_luot_thu_thi_chan_keo_va_trang_thai_go_chan(mo_trang, db):
    """Mạng hỏng thật (mọi POST `/chuot` thất bại) ⇒ lô cạn lượt thử ⇒ popup CHẶN kéo, thôi tiêu `seq` vào
    POST không tới được máy chủ. `trang_thai` về (máy chủ nhắc lại mỗi 5 s) ⇒ gỡ chặn, kéo lại tới máy chủ.
    Không chặn chỉ vì SSE nối lại chớp nhoáng (onerror CONNECTING) — chỉ khi POST cạn lượt thử.
    ĐỘT BIẾN: không gán `matKetNoiHan` khi cạn lượt ⇒ rê chuột vẫn bắn request ⇒ ĐỎ; không gỡ khi
    `trang_thai` về ⇒ kéo không bao giờ tới máy chủ ⇒ ĐỎ."""
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    dem = {"n": 0}

    def chan(route):
        dem["n"] += 1
        route.abort()

    page.route("**/giai/chuot", chan)
    page.mouse.move(r["x"] + 50, r["y"] + 50)              # hover ⇒ một lô ⇒ 1 lần gửi + 3 lần thử lại
    assert cho_trang(page, lambda: "Mất kết nối tới máy chủ" in page.locator("#gc-note").inner_text(), 6)
    da_chan = dem["n"]
    assert da_chan >= 4, da_chan
    for i in range(5):                                      # rê tiếp trong lúc chặn
        page.mouse.move(r["x"] + 60 + 10 * i, r["y"] + 60)
    doi_gui(page, 500)
    assert dem["n"] == da_chan, "đang chặn kéo: không được bắn thêm POST `/chuot` nào"
    page.unroute("**/giai/chuot")
    truoc = len(ghi.su_kien())
    phien.dat_trang_thai("dang_giai", 200)                  # đổi phiên bản ⇒ SSE gửi `trang_thai` ngay
    assert cho_trang(page, lambda: "Mất kết nối tới máy chủ" not in page.locator("#gc-note").inner_text(), 6)
    # Máy chủ có kỳ ⇒ `trang_thai` về kích ĐỒNG BỘ CHỦ ĐỘNG (lô đã mất): popup gửi `huy_gesture` và chặn chuột tới khi
    # được trả lời — rê trong lúc đó bị bỏ đúng thiết kế. Chờ phản hồi đó thay vì rê một lần rồi hy vọng.
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5)
    page.mouse.move(r["x"] + 200, r["y"] + 120)
    assert cho_trang(page, lambda: len(ghi.su_kien()) > truoc, 5), "gỡ chặn xong thì rê chuột phải tới máy chủ"



def test_sse_loi_connecting_khong_chan_keo(mo_trang, db):
    """SSE đứt (luồng máy chủ kết thúc không có `ket_thuc` ⇒ EventSource `onerror` khi CONNECTING) KHÔNG được
    chặn kéo: chỉ lô CẠN lượt thử mới bật `matKetNoiHan`. Gây đứt bằng cách đổi chủ job tạm thời (luồng SSE
    kiểm quyền mỗi giây rồi tự dừng), trả lại chủ ngay để EventSource nối lại được. Quan sát qua lớp
    `dieu-khien` của khung (bật/tắt đúng theo `dieuKhienDuoc()`).
    ĐỘT BIẾN: bật `matKetNoiHan` ngay ở `onerror` ⇒ khung mất `dieu-khien` ⇒ ĐỎ."""
    page, ghi, jid, _ = mo_popup_dang_giai(mo_trang, db)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET nguoi_tao = ? WHERE id = ?", ("khac@x.vn", jid))
    try:
        assert cho_trang(page, lambda: "Mất kết nối tới máy chủ" in page.locator("#gc-note").inner_text(), 8)
    finally:
        with models._connect(db) as conn:
            conn.execute("UPDATE jobs SET nguoi_tao = ? WHERE id = ?", (NGUOI, jid))
    assert page.locator(".gc-frame.dieu-khien").count() == 1, "SSE lỗi (CONNECTING) không được chặn kéo"


def test_bi_chan_vi_can_luot_thi_lo_200_go_chan_khong_cho_trang_thai(mo_trang, db, monkeypatch):
    """Một lô cạn lượt thử ⇒ chặn; một lô KHÁC còn đang bay rồi được 200 ⇒ gỡ chặn ngay (mạng đã thông),
    không phải chờ `trang_thai` nhắc lại. Tắt nhịp nhắc lại để không lẫn đường gỡ.
    ĐỘT BIẾN: không gỡ `matKetNoiHan` khi lô 200 ⇒ còn chặn ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu, pha = [], {"n": 0}

    def chan(route):
        pha["n"] += 1
        if pha["n"] == 1:
            giu.append(route)                      # lô đầu treo, chưa trả lời
        else:
            route.abort()                          # mọi lần sau trượt ⇒ lô sau cạn lượt thử

    page.route("**/giai/chuot", chan)
    page.mouse.move(r["x"] + 50, r["y"] + 50)
    assert cho_trang(page, lambda: len(giu) == 1, 3)
    page.wait_for_timeout(60)
    page.mouse.move(r["x"] + 90, r["y"] + 60)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 0, 6), "phải bị chặn"
    giu[0].continue_()                             # lô treo tới máy chủ ⇒ 200
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 1, 3), "lô 200 phải gỡ chặn"
    page.unroute("**/giai/chuot")


def test_can_luot_giua_cu_keo_thi_bo_cu_keo_khong_gui_up_sau_khi_go_chan(mo_trang, db):
    """Đang giữ chuột kéo thì lô cạn lượt thử ⇒ cú kéo bị BỎ im lặng; gỡ chặn rồi người nhả chuột ⇒ KHÔNG gửi
    `up` (một `up` muộn sẽ hoàn tất cú kéo cũ trên trang). Cú kéo mới sau đó chạy bình thường.
    ĐỘT BIẾN: bỏ `boCuChi` khi cạn lượt ⇒ `up` của cú kéo cũ được gửi ⇒ ĐỎ."""
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.route("**/giai/chuot", lambda route: route.abort())
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    page.mouse.down()
    page.mouse.move(r["x"] + 80, r["y"] + 62)
    # Bằng chứng cú kéo đã bị BỎ khi cạn lượt: popup báo huỷ (`/lenh` vẫn tới được máy chủ ⇒ máy chủ có kỳ đổi
    # kỳ và đẩy `trang_thai` ⇒ chặn chỉ thoáng qua), hoặc bị chặn nếu chưa kịp.
    assert cho_trang(page, lambda: any(l["lenh"] == "huy_gesture" for l in ghi.lenh)
                     or page.locator(".gc-frame.dieu-khien").count() == 0, 6), "phải bỏ cú kéo"
    page.unroute("**/giai/chuot")
    phien.dat_trang_thai("dang_giai", 200)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 1, 6)
    # Máy chủ có kỳ ⇒ `trang_thai` về kích ĐỒNG BỘ CHỦ ĐỘNG (thêm một `huy_gesture`): chuột bị chặn tới khi mọi lệnh
    # huỷ được trả lời — cú kéo mới trong lúc đó bị bỏ đúng thiết kế. Chờ tới khi không còn lệnh huỷ nào đang bay.
    huy_gui = lambda: ghi.thu_tu.count(("lenh_gui", "huy_gesture"))
    assert cho_trang(page, lambda: huy_gui() >= 2 and huy_gui() == ghi.thu_tu.count(("lenh_ve", "huy_gesture")), 5)
    page.mouse.up()                                # nhả nút của cú kéo đã bị bỏ
    page.mouse.move(r["x"] + 200, r["y"] + 200)
    page.mouse.down()
    page.mouse.move(r["x"] + 220, r["y"] + 205)
    page.mouse.up()                                # cú kéo mới, trọn vẹn
    so_up = lambda: sum(1 for lo in ghi.chuot for e in lo["su_kien"] if e["k"] == "up")
    assert cho_trang(page, lambda: so_up() >= 1, 5)
    doi_gui(page)
    assert so_up() == 1, "chỉ cú kéo mới được có `up`"



# ---------------------------------------------------------------------------
# Kỳ (`ky`) phía popup. Máy chủ THẬT đã có kỳ; các test dưới tự ĐỔI kỳ của máy chủ (`_doi_ky`) thay vì chờ một lý do
# huỷ thật, để chọn được `ky_mat_nut` (không có worker phát lô nên huỷ thật luôn thấy sự kiện chưa phát). 409 `ky_cu`
# đặc thù trả bằng `page.route`.
# ---------------------------------------------------------------------------

def _gia_ky(monkeypatch):
    """Giữ chỗ: máy chủ thật đã gửi `ky`/`ky_mat_nut` trong `trang_thai` (trước PR máy chủ, hàm này giả hai trường)."""


def _doi_ky(phien, ky, mat_nut=False, day=True):
    """Máy chủ huỷ gesture ⇒ kỳ `ky` (bỏ hàng phát, đệm lô, `seq` về 0 — như `_huy_gesture_unlocked`); `mat_nut` = lần
    huỷ đó bỏ thao tác nút chưa phát (⇒ `ky_mat_nut = ky`). `day=False`: chưa đẩy `trang_thai` (test tự bắn)."""
    with phien.khoa:
        phien.bo_phat.huy()
        phien.ky = gc._ky_ke_tiep()           # cùng bộ đếm với huỷ thật: kỳ sau đó vẫn tăng ngặt
        assert phien.ky == ky, (phien.ky, ky)
        if mat_nut:
            phien.ky_mat_nut = ky
        phien.expected_seq = 0
        phien._cho_lo.clear()
        phien._cho_lo_tu = None
        if day:
            phien._doi()


def _keo(page, r, x0=100, y0=100):
    page.mouse.move(r["x"] + x0, r["y"] + y0)
    page.mouse.down()
    page.mouse.move(r["x"] + x0 + 30, r["y"] + y0 + 5)
    page.mouse.up()


def _lo_gui_sau(ghi, n):
    return ghi.chuot[n:]


def test_doi_ky_sau_cu_keo_tron_bao_keo_lai(mo_trang, db, monkeypatch):
    """ĐP-848 điều kiện (1), ca A8 nút=F (C3/C4): cú kéo đã gửi TRỌN và được 200, rồi máy chủ huỷ nó trước khi phát
    (đổi kỳ, `ky_mat_nut` = kỳ mới) ⇒ popup phải BÁO "đồng bộ lại — kéo lại từ đầu"; mất cú kéo phải THẤY ĐƯỢC.
    ĐỘT BIẾN: bỏ gán `biNgat = dong_bo` trong `doiKy` ⇒ ĐỎ; bỏ vế `ky_mat_nut` ⇒ ĐỎ."""
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    _keo(page, r)
    assert cho_trang(page, lambda: ghi.chuot and all(("lo_ve", lo["seq"]) in ghi.thu_tu for lo in ghi.chuot)
                     and any(e["k"] == "up" for lo in ghi.chuot for e in lo["su_kien"]), 5)
    _doi_ky(phien, 1, mat_nut=True)
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 5)


def test_doi_ky_sau_cu_keo_da_phat_khong_bao(mo_trang, db, monkeypatch):
    """C5 (ca âm): cú kéo được 200 trọn, máy chủ huỷ vì lý do KHÔNG đụng nó (`ky_mat_nut` không đổi) ngay sau đó ⇒
    KHÔNG báo "kéo lại" (cửa sổ thời gian cũ báo nhầm ở đây). Chờ điều kiện: popup đã học kỳ 1.
    ĐỘT BIẾN: luôn báo khi đổi kỳ ⇒ ĐỎ; Set không xoá lô khi 200 ⇒ ĐỎ."""
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    _keo(page, r)
    assert cho_trang(page, lambda: ghi.chuot and all(("lo_ve", lo["seq"]) in ghi.thu_tu for lo in ghi.chuot)
                     and any(e["k"] == "up" for lo in ghi.chuot for e in lo["su_kien"]), 5)
    doi_gui(page, 100)
    _doi_ky(phien, 1)
    _hoc_ky_moi(page, ghi, r, 1)
    assert "Đã đồng bộ lại với máy chủ" not in page.locator("#gc-note").inner_text()


def test_doi_ky_khi_lo_keo_chua_toi_bao_keo_lai(mo_trang, db, monkeypatch):
    """C2 (ca A8 thieu_lo): lô chứa cú kéo CHƯA được 200 (còn treo trên mạng — máy chủ không biết nội dung lô hụt,
    `ky_mat_nut` không đổi) mà kỳ đổi ⇒ popup tự biết và BÁO, bất kể đã bao lâu. ĐỘT BIẾN: bỏ vế `loNut` ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = []

    def chuot(route):
        # Mọi lô kỳ 0 (kể cả lần thử lại sau timeout 8 s) treo suốt test; kỳ sau đi thẳng tới máy chủ.
        if route.request.post_data_json.get("ky") == 0:
            giu.append(route)
        else:
            route.continue_()

    page.route("**/giai/chuot", chuot)
    _keo(page, r)
    assert cho_trang(page, lambda: any(e["k"] == "up" for x in giu for e in x.request.post_data_json["su_kien"]), 5)
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 5)
    # Lô kỳ 0 vẫn treo (không bao giờ 200); route giữ tới hết test, context đóng thì tự dọn.
    # Lô treo của kỳ 0 chỉ được tính ĐÚNG MỘT lần đổi kỳ: kéo trọn ở kỳ 1 (được 200), kỳ 2 về ⇒ KHÔNG báo.
    # ĐỘT BIẾN: `doiKy` không thay Set mới ⇒ lô kỳ 0 còn treo làm báo lại ở kỳ 2 ⇒ ĐỎ.
    n = len(ghi.chuot)
    _keo(page, r, 300, 300)
    assert cho_trang(page, lambda: _lo_gui_sau(ghi, n) and all(("lo_ve", lo["seq"]) in ghi.thu_tu
                     for lo in _lo_gui_sau(ghi, n) if lo.get("ky") == 1)
                     and any(e["k"] == "up" for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), 5)
    assert "Đã đồng bộ lại với máy chủ" not in page.locator("#gc-note").inner_text()
    _doi_ky(phien, 2)
    _hoc_ky_moi(page, ghi, r, 2)
    assert "Đã đồng bộ lại với máy chủ" not in page.locator("#gc-note").inner_text()


def test_lo_chi_re_bi_ky_cu_roi_doi_ky_khong_bao(mo_trang, db, monkeypatch):
    """Lô CHỈ RÊ (buttons=0) nhận 409 `ky_cu` (chưa bao giờ 200) rồi kỳ mới về ⇒ KHÔNG báo "kéo lại": không có
    thao tác nút nào bị mất (cửa sổ thời gian cũ cũng im ở đây; vế `loNut` không được nhận lô rê).
    ĐỘT BIẾN: Set nhận cả lô rê ⇒ ĐỎ; tính rê là thao tác nút ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.route("**/giai/chuot", lambda route: route.fulfill(
        status=409, content_type="application/json", body='{"detail": {"ma": "ky_cu", "ky": 1}}'))
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    assert cho_trang(page, lambda: 409 in ghi.mat_chuot, 5)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 0, 5), "phải tạm chặn"
    page.unroute("**/giai/chuot")
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 1, 5), "kỳ mới phải gỡ chặn"
    _hoc_ky_moi(page, ghi, r, 1)
    assert "Đã đồng bộ lại với máy chủ" not in page.locator("#gc-note").inner_text()


def test_doi_ky_khi_200_chua_ve_bao_thua_da_chap_nhan(mo_trang, db, monkeypatch):
    """C6 — báo thừa ĐÃ CHẤP NHẬN (ĐP-862): lô kéo đã tới máy chủ (đã phát) nhưng phản hồi 200 chưa về lúc kỳ đổi ⇒
    popup không phân biệt được với lô hụt ⇒ báo "kéo lại" (người kéo thêm một lần). Test ghi lại hành vi này để
    thay đổi về sau là CÓ CHỦ ĐÍCH."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = []

    def chuot(route):
        giu.append((route, route.fetch()))     # máy chủ đã nhận + trả lời; popup chưa thấy phản hồi

    page.route("**/giai/chuot", chuot)
    _keo(page, r)
    assert cho_trang(page, lambda: any(e["k"] == "up" for x, _ in giu for e in x.request.post_data_json["su_kien"]), 5)
    assert all(resp.status == 200 for _, resp in giu)
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 5)
    for x, resp in giu:
        x.fulfill(response=resp)
    page.unroute("**/giai/chuot")


def test_dong_bo_chu_dong_dang_huy_hien_chu_dang_huy(mo_trang, db, monkeypatch):
    """Review agy vd-c7c R3b T2: đồng bộ chủ động (lô cạn lượt thử ⇒ `trang_thai` về ⇒ `huy_gesture`) chặn chuột mà
    không đặt `biNgat` ⇒ trước đây chữ vẫn là gợi ý kéo bình thường trong khi cú nhấn bị BỎ IM LẶNG. Lệnh huỷ treo ⇒
    chữ "đang huỷ thao tác cũ" phải hiện. ĐỘT BIẾN: `tinhMan` chỉ xét `biNgat` ⇒ ĐỎ."""
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = chan_lenh_huy(page, 1, treo=True)
    page.route("**/giai/chuot", lambda route: route.abort())
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 0, 6), "phải bị chặn"
    page.unroute("**/giai/chuot")
    phien.dat_trang_thai("dang_giai", 200)
    assert cho_trang(page, lambda: len(giu) == 1, 5), "đồng bộ chủ động phải gửi huy_gesture"
    assert cho_trang(page, lambda: "đang huỷ thao tác cũ" in page.locator("#gc-note").inner_text(), 3), \
        page.locator("#gc-note").inner_text()


def test_doi_ky_khi_chi_re_chuot_khong_bao(mo_trang, db, monkeypatch):
    """Ca âm: chỉ rê chuột (không nhấn nút) rồi kỳ đổi ⇒ KHÔNG báo "kéo lại" (không có cú kéo nào mất).
    Chờ điều kiện: kỳ mới đã được học (lô kế mang `ky = 1`). ĐỘT BIẾN: tính cả hover là thao tác ⇒ ĐỎ."""
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.mouse.move(r["x"] + 50, r["y"] + 50)
    page.mouse.move(r["x"] + 60, r["y"] + 55)
    assert cho_trang(page, lambda: len(ghi.chuot) >= 1, 5)
    _doi_ky(phien, 1)
    n = len(ghi.chuot)
    i = 0
    while not any(lo.get("ky") == 1 for lo in _lo_gui_sau(ghi, n)) and i < 60:
        page.mouse.move(r["x"] + 70 + i, r["y"] + 60)
        page.wait_for_timeout(50)
        i += 1
    assert any(lo.get("ky") == 1 for lo in _lo_gui_sau(ghi, n)), "popup chưa học kỳ mới"
    assert "Đã đồng bộ lại với máy chủ" not in page.locator("#gc-note").inner_text()


def test_doi_ky_lo_ke_mang_ky_moi_va_seq_ve_0(mo_trang, db, monkeypatch):
    """Sau khi đổi kỳ, lô kế tiếp mang `ky` mới và `seq` đánh lại từ 0 (máy chủ mới đặt `expected_seq = 0` mỗi
    kỳ). Trước đó các lô mang `ky = 0`. ĐỘT BIẾN: không đặt `seqLo = 0` trong `doiKy` ⇒ ĐỎ."""
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    _keo(page, r)
    assert cho_trang(page, lambda: len(ghi.chuot) >= 1, 5)
    assert all(lo.get("ky") == 0 for lo in ghi.chuot) and max(lo["seq"] for lo in ghi.chuot) >= 0
    _doi_ky(phien, 1, mat_nut=True)
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 5)
    n = len(ghi.chuot)
    _keo(page, r, 300, 300)
    assert cho_trang(page, lambda: len(_lo_gui_sau(ghi, n)) >= 1, 5)
    moi = _lo_gui_sau(ghi, n)
    assert moi[0]["ky"] == 1 and moi[0]["seq"] == 0, moi[0]


def test_lo_ky_cu_tam_chan_keo_toi_khi_ky_moi_ve(mo_trang, db, monkeypatch):
    """Lô của ĐÚNG kỳ popup đang biết nhận 409 `ky_cu` (máy chủ vừa sang kỳ mới, popup chưa nhận `trang_thai`)
    ⇒ tạm chặn kéo; `trang_thai` mang kỳ mới ⇒ gỡ chặn và báo "kéo lại". Tắt nhịp nhắc lại để không lẫn đường.
    ĐỘT BIẾN: bỏ `choKy = true` ⇒ không bị chặn ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.route("**/giai/chuot", lambda route: route.fulfill(
        status=409, content_type="application/json", body='{"detail": {"ma": "ky_cu", "ky": 1}}'))
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    page.mouse.down()
    page.mouse.move(r["x"] + 80, r["y"] + 62)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 0, 5), "phải tạm chặn"
    page.unroute("**/giai/chuot")
    page.mouse.up()
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 1, 5), "kỳ mới phải gỡ chặn"
    assert "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text()
    assert not any(e["k"] == "up" for lo in ghi.chuot for e in lo["su_kien"]), "không gửi `up` của cú kéo đã chết"


def test_huy_bi_ky_cu_coi_nhu_da_huy_khong_bao_chua_bao_duoc(mo_trang, db, monkeypatch):
    """Lệnh huỷ nhận 409 `ky_cu` ⇒ máy chủ đã tự huỷ (đã sang kỳ mới) ⇒ coi như ĐÃ huỷ: không hiện "chưa báo
    được máy chủ", không thử lại; kéo tạm chặn tới khi kỳ mới về. ĐỘT BIẾN: coi `ky_cu` là chưa huỷ ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)

    def lenh(route):
        if "huy_gesture" in (route.request.post_data or ""):
            route.fulfill(status=409, content_type="application/json", body='{"detail": {"ma": "ky_cu", "ky": 1}}')
        else:
            route.continue_()

    page.route("**/giai/lenh", lenh)
    _keo_roi_blur(page, r)
    assert cho_trang(page, lambda: [l["lenh"] for l in ghi.lenh].count("huy_gesture") >= 1, 5)
    doi_gui(page, 500)
    assert [l["lenh"] for l in ghi.lenh].count("huy_gesture") == 1, "không thử lại khi đã là ky_cu"
    assert "chưa báo được máy chủ" not in page.locator("#gc-note").inner_text()
    assert page.locator(".gc-frame.dieu-khien").count() == 0, "chưa học kỳ mới ⇒ chưa được kéo"
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 1, 5)


def test_lo_khong_toi_duoc_thi_dong_bo_chu_dong_khi_dieu_khien_lai(mo_trang, db, monkeypatch):
    """Lô cạn lượt thử (mạng hỏng) ⇒ khi `trang_thai` về và lại điều khiển được, popup GỬI `huy_gesture` ngay
    (mang `ky`) để máy chủ sang kỳ mới — cú kéo kế tiếp bắt đầu sạch thay vì chờ máy chủ tự phát hiện hụt 2 s.
    ĐỘT BIẾN: bỏ nhánh đồng bộ chủ động ⇒ không có `huy_gesture` ⇒ ĐỎ."""
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.route("**/giai/chuot", lambda route: route.abort())
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 0, 6), "phải bị chặn"
    page.unroute("**/giai/chuot")
    assert not [l for l in ghi.lenh if l["lenh"] == "huy_gesture"]
    phien.dat_trang_thai("dang_giai", 200)
    assert cho_trang(page, lambda: any(l["lenh"] == "huy_gesture" for l in ghi.lenh), 5)
    huy = [l for l in ghi.lenh if l["lenh"] == "huy_gesture"][0]
    assert huy.get("ky") == 0


def test_may_chu_chua_co_ky_lo_khong_mang_ky(mo_trang, db, monkeypatch):
    """Máy chủ cũ (không gửi `ky` trong `trang_thai` — giả bằng cách bỏ trường): lô và lệnh huỷ KHÔNG mang trường `ky`
    — popup chạy đúng giao thức cũ (deploy popup trước máy chủ). ĐỘT BIẾN: luôn gửi `ky` ở lô ⇒ ĐỎ; luôn gửi `ky` ở
    lệnh huỷ ⇒ ĐỎ."""
    goc = gc.PhienGiai.anh_chup

    def anh_chup_cu(self, token, email):
        d = goc(self, token, email)
        d.pop("ky", None)
        d.pop("ky_mat_nut", None)
        return d

    monkeypatch.setattr(gc.PhienGiai, "anh_chup", anh_chup_cu)
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    # Máy chủ ở đây CÓ kỳ nên từ chối lô thiếu `ky` (400) ⇒ trả 200 giả cho lô để popup đi tiếp tới lệnh huỷ.
    page.route("**/giai/chuot", lambda route: route.fulfill(status=200, content_type="application/json",
                                                            body='{"ok": true}'))
    _keo(page, r)
    assert cho_trang(page, lambda: len(ghi.chuot) >= 1, 5)
    assert all("ky" not in lo for lo in ghi.chuot)
    _keo_roi_blur(page, r, 300)
    page.mouse.up()
    assert cho_trang(page, lambda: any(l["lenh"] == "huy_gesture" for l in ghi.lenh), 5)
    assert all("ky" not in l for l in ghi.lenh if l["lenh"] == "huy_gesture")


def _giu_lenh_huy_trong_trang(page):
    """Lệnh `huy_gesture` đầu tiên đứng TRONG trang (không ra mạng) tới khi gọi `window.__thaHuy()`; lúc đó nó
    nhận ngay một 200 giả. Thả bằng JS — cùng lượt với sự kiện chuột — để thứ tự "cú nhấn mới rồi phản hồi huỷ
    về" là XÁC ĐỊNH (thả từ Python thì bộ gom 40 ms có thể xả trước)."""
    page.evaluate("""() => { const f = window.fetch; let da = false;
        window.fetch = async (u, o) => {
            if (!da && String((o && o.body) || "").includes("huy_gesture")) {
                da = true;
                await new Promise((r) => { window.__thaHuy = r; });
                return new Response('{"ok": true}', {status: 200, headers: {"content-type": "application/json"}});
            }
            return f(u, o); }; }""")


def _con_tro(page, ten, x, y, buttons, button=0):
    """Bắn một PointerEvent chuột tổng hợp vào khung (toạ độ tương đối ảnh)."""
    return f"""document.querySelector('#gc-khung').dispatchEvent(new PointerEvent('{ten}', {{
        pointerId: 7, pointerType: 'mouse', bubbles: true, cancelable: true, button: {button}, buttons: {buttons},
        clientX: document.querySelector('#gc-anh').getBoundingClientRect().x + {x},
        clientY: document.querySelector('#gc-anh').getBoundingClientRect().y + {y} }}));"""


def test_huy_cu_tra_ve_sau_doi_ky_khong_xoa_cu_keo_moi(mo_trang, db, monkeypatch):
    """Review #52 SHOULD-1: lệnh huỷ còn treo, kỳ mới về (`doiKy` gỡ chặn vì máy chủ đã huỷ khi đổi kỳ), người
    bắt đầu cú kéo MỚI; rồi phản hồi của lệnh huỷ CŨ mới về. Phản hồi đó thuộc lần huỷ đã hết hiệu lực ⇒ KHÔNG
    được xoá `buf` (mất `down` ⇒ move/`up` mồ côi, hoặc mất `up` ⇒ nút kẹt). Cú kéo mới phải tới máy chủ trọn
    vẹn: `down` … `up`, kỳ 1, seq từ 0. ĐỘT BIẾN: `.then` của lệnh huỷ xoá `buf` vô điều kiện ⇒ ĐỎ; `doiKy` không
    gỡ chặn ⇒ ĐỎ (chữ vẫn "đang huỷ thao tác cũ")."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    _giu_lenh_huy_trong_trang(page)
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: page.evaluate("() => typeof window.__thaHuy === 'function'"), 5)
    assert "đang huỷ thao tác cũ" in page.locator("#gc-note").inner_text()
    _doi_ky(phien, 1)
    # Kỳ mới đã gỡ chặn: chữ thôi "đang huỷ", về chữ của lần bỏ gesture (blur ⇒ "cuc_bo").
    assert cho_trang(page, lambda: "Cửa sổ vừa mất con trỏ" in page.locator("#gc-note").inner_text(), 5)
    n = len(ghi.chuot)
    # Cú nhấn mới vào `buf` (bộ gom chưa xả — còn 40 ms) rồi phản hồi huỷ cũ về NGAY trong cùng lượt JS.
    page.evaluate("() => {" + _con_tro(page, "pointerdown", 300, 300, 1) + " window.__thaHuy(); }")
    page.wait_for_timeout(100)
    page.evaluate("() => {" + _con_tro(page, "pointermove", 330, 305, 1) + _con_tro(page, "pointerup", 330, 305, 0) + "}")
    assert cho_trang(page, lambda: any(e["k"] == "up" for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), 5)
    doi_gui(page)
    moi = sorted(_lo_gui_sau(ghi, n), key=lambda x: x["seq"])
    assert all(lo["ky"] == 1 for lo in moi) and [lo["seq"] for lo in moi] == list(range(len(moi))), moi
    assert [e["k"] for lo in moi for e in lo["su_kien"]] == ["down", "move", "up"]
    assert page.locator(".gc-frame.dieu-khien").count() == 1
    assert "chưa báo được máy chủ" not in page.locator("#gc-note").inner_text()


def _hoc_ky_moi(page, ghi, r, ky):
    """Rê chuột tới khi một lô mang `ky` mới (popup đã học kỳ). Trả số lô trước đó."""
    n = len(ghi.chuot)
    i = 0
    while not any(lo.get("ky") == ky for lo in _lo_gui_sau(ghi, n)) and i < 60:
        page.mouse.move(r["x"] + 400 + i, r["y"] + 60)
        page.wait_for_timeout(50)
        i += 1
    assert any(lo.get("ky") == ky for lo in _lo_gui_sau(ghi, n)), "popup chưa học kỳ mới"
    return n


def test_409_ky_cu_cua_lo_ky_cu_toi_muon_khong_khoa_keo(mo_trang, db, monkeypatch):
    """Review #52 SHOULD-3 (khoá vĩnh viễn, lớp L1/B2): lô kỳ 0 còn đang bay, kỳ 1 về và popup đã học; rồi 409
    `ky_cu` của lô kỳ 0 mới tới. Lô đó thuộc kỳ ĐÃ bỏ ⇒ bỏ qua: KHÔNG tạm chặn (`trang_thai` kế mang CÙNG kỳ 1 nên
    không ai gỡ ⇒ chặn kéo + vô hiệu 2 nút tới lần đổi kỳ sau). Tắt nhịp nhắc lại. ĐỘT BIẾN: bỏ guard
    `lo.ky === p.ky` ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = []

    def chuot(route):
        if not giu:
            giu.append(route)              # lô đầu (kỳ 0) treo
        else:
            route.continue_()

    page.route("**/giai/chuot", chuot)
    page.mouse.move(r["x"] + 50, r["y"] + 50)
    assert cho_trang(page, lambda: len(giu) == 1, 5)
    assert giu[0].request.post_data_json["ky"] == 0
    _doi_ky(phien, 1)
    _hoc_ky_moi(page, ghi, r, 1)
    giu[0].fulfill(status=409, content_type="application/json", body='{"detail": {"ma": "ky_cu", "ky": 1}}')
    assert cho_trang(page, lambda: ("lo_ve", 0) in ghi.thu_tu and ghi.mat_chuot.count(409) == 1, 5)
    doi_gui(page)
    assert page.locator(".gc-frame.dieu-khien").count() == 1, "409 của lô kỳ cũ không được khoá kéo"
    assert page.locator("#gc-actions button[data-lenh]:not([disabled])").count() == 2
    page.unroute("**/giai/chuot")


def test_doi_ky_giua_cu_keo_khong_gui_up_mo_coi(mo_trang, db, monkeypatch):
    """Review #52 SHOULD-4: đang giữ chuột (down + move đã gửi ở kỳ 0) thì kỳ 1 về ⇒ gesture dở thuộc kỳ đã bỏ.
    Người nhả chuột ⇒ KHÔNG lô kỳ 1 nào chứa `up` (một `up` mồ côi ở kỳ mới sẽ thả nút trên trang không có `down`),
    có chữ "đồng bộ lại". Cú kéo mới sau đó chạy bình thường ở kỳ 1. ĐỘT BIẾN: `doiKy` không bỏ `cuChi` ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    page.mouse.down()
    page.mouse.move(r["x"] + 80, r["y"] + 62)
    assert cho_trang(page, lambda: any(e["k"] == "down" for lo in ghi.chuot for e in lo["su_kien"]), 5)
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 5)
    n = len(ghi.chuot)
    page.mouse.up()
    doi_gui(page)
    _keo(page, r, 300, 300)
    assert cho_trang(page, lambda: any(e["k"] == "up" for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), 5)
    doi_gui(page)
    moi = sorted(_lo_gui_sau(ghi, n), key=lambda x: x["seq"])
    assert all(lo["ky"] == 1 for lo in moi)
    assert [e["k"] for lo in moi for e in lo["su_kien"] if e["k"] != "move"] == ["down", "up"], moi


# `trang_thai` kỳ 1 bắn thẳng vào EventSource của popup (bắt bởi `_mo_popup_bat_es`) — cùng lượt JS với sự kiện chuột.
_TRANG_THAI_KY_1 = """ window.__es.dispatchEvent(new MessageEvent('trang_thai', { lastEventId: 'test', data: JSON.stringify({
    trang_thai: 'dang_giai', vai: 'dieu_khien', con_lai_giay: 250, so_lan_tai_lai: 0, ky: 1, ky_mat_nut: 0 }) })); """


def _mo_popup_bat_es(mo_trang, db, monkeypatch):
    """Popup `dang_giai` với máy chủ giả có kỳ, giữ EventSource ở `window.__es`; máy chủ (giả) đã sang kỳ 1 nhưng
    chưa đẩy `trang_thai` — test tự bắn bằng `_TRANG_THAI_KY_1`. Tắt nhịp nhắc lại. Trả (page, ghi, phien)."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    jid = tao_job(db)
    page, ghi = mo_trang()
    page.evaluate("""() => { const ES = window.EventSource;
        window.EventSource = function (u, o) { const es = new ES(u, o); window.__es = es; return es; };
        window.EventSource.prototype = ES.prototype; }""")
    page.click(".nut-giai-ngay")
    page.wait_for_selector("#gc-bg")
    phien = den_dang_giai(page, db, jid)
    page.wait_for_selector(".gc-frame.dieu-khien")
    page.wait_for_function("() => { const a = document.querySelector('#gc-anh'); return a && a.naturalWidth === 800; }")
    _doi_ky(phien, 1, day=False)
    return page, ghi, phien


def test_cu_nhap_con_trong_bo_gom_luc_doi_ky_bao_keo_lai(mo_trang, db, monkeypatch):
    """Review #52 vòng 2 SHOULD-1: cú nhấp TRỌN (down + up) còn trong bộ gom 40 ms đúng lúc kỳ mới về ⇒ `doiKy` bỏ nó
    (không bao giờ được gửi) — máy chủ không biết, Set chưa có lô nào ⇒ chỉ popup biết ⇒ phải BÁO "kéo lại", không mất
    im lặng. Không lô nào được gửi. ĐỘT BIẾN: bỏ vế `buf` trong `coThaoTac` ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_bat_es(mo_trang, db, monkeypatch)
    n = len(ghi.chuot)
    page.evaluate("() => {" + _con_tro(page, "pointerdown", 300, 300, 1) + _con_tro(page, "pointerup", 300, 300, 0)
                  + _TRANG_THAI_KY_1 + "}")
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 3)
    doi_gui(page)
    assert not any(e["k"] in ("down", "up") for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), "cú nhấp đã bỏ"


def test_chi_re_con_trong_bo_gom_luc_doi_ky_khong_bao(mo_trang, db, monkeypatch):
    """Ca âm của vế `buf`: chỉ RÊ chuột còn trong bộ gom lúc kỳ mới về ⇒ không báo (rê không phải thao tác nút).
    ĐỘT BIẾN: vế `buf` tính mọi sự kiện ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_bat_es(mo_trang, db, monkeypatch)
    page.evaluate("() => {" + _con_tro(page, "pointermove", 300, 300, 0) + _TRANG_THAI_KY_1 + "}")
    doi_gui(page)
    _hoc_ky_moi(page, ghi, khung_rect(page), 1)
    assert "Đã đồng bộ lại với máy chủ" not in page.locator("#gc-note").inner_text()


def test_doi_ky_khi_huy_dang_bay_lenh_da_giai_khong_cho_huy_cu(mo_trang, db, monkeypatch):
    """Review #52 vòng 2 NIT-1: lệnh huỷ TREO, kỳ mới về (máy chủ đã huỷ ⇒ lần huỷ đó hết hiệu lực), người bấm "Đã giải
    xong" ⇒ `da_giai` gửi NGAY, không đứng chờ lệnh huỷ cũ (≈ 13 s thử lại). ĐỘT BIẾN: `doiKy` không đặt
    `dangHuy = false` ⇒ `guiLenh` chờ lệnh huỷ ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = chan_lenh_huy(page, 10, treo=True)
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: len(giu) == 1, 5)
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: "Cửa sổ vừa mất con trỏ" in page.locator("#gc-note").inner_text(), 5)
    page.click("#gc-actions button:has-text('Đã giải xong')")
    assert cho_trang(page, lambda: any(l["lenh"] == "da_giai" for l in ghi.lenh), 2), \
        "da_giai phải gửi ngay, không chờ lệnh huỷ đã hết hiệu lực"
    assert len(giu) == 1, "lệnh huỷ cũ vẫn còn treo lúc da_giai đi"


def _mo_popup_loc_trang_thai(mo_trang, db, monkeypatch):
    """Popup `dang_giai` (máy chủ thật có kỳ) mà test BỎ ĐƯỢC `trang_thai` THẬT (`window.__boTrangThai = true`) — để kỳ
    mới chỉ tới qua PHẢN HỒI lệnh huỷ; `trang_thai` tổng hợp (`_TRANG_THAI_KY_1`, `lastEventId` "test") vẫn qua.
    Tắt nhịp nhắc lại. Trả (page, ghi, phien)."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    jid = tao_job(db)
    page, ghi = mo_trang()
    page.evaluate("""() => { const ES = window.EventSource; window.__boTrangThai = false;
        window.EventSource = function (u, o) { const es = new ES(u, o); window.__es = es;
            const goc = es.addEventListener.bind(es);
            es.addEventListener = (loai, fn, tuy) => goc(loai, loai === 'trang_thai'
                ? (ev) => { if (!window.__boTrangThai || ev.lastEventId === 'test') fn(ev); } : fn, tuy);
            return es; };
        window.EventSource.prototype = ES.prototype; }""")
    page.click(".nut-giai-ngay")
    page.wait_for_selector("#gc-bg")
    phien = den_dang_giai(page, db, jid)
    page.wait_for_selector(".gc-frame.dieu-khien")
    page.wait_for_function("() => { const a = document.querySelector('#gc-anh'); return a && a.naturalWidth === 800; }")
    return page, ghi, phien


def test_hoc_ky_tu_phan_hoi_huy_bao_keo_lai_khi_mat_lo(mo_trang, db, monkeypatch):
    """Đồng bộ ở đường cạn lượt thử: lô kéo không tới máy chủ ⇒ popup tự huỷ (không đặt `biNgat`) ⇒ phản hồi
    `{ok, ky, ky_mat_nut}` ⇒ popup học kỳ NGAY từ phản hồi và BÁO "kéo lại" (lô có nút chưa 200). `trang_thai` bị bỏ
    nên chỉ đường phản hồi có thể báo. ĐỘT BIẾN: `doiKy` từ phản hồi luôn im (`bao=false` cũ) ⇒ ĐỎ. (Bỏ hẳn học kỳ từ
    phản hồi, hoặc gọi `doiKy` trước cổng hiệu lực: test kế tiếp ĐỎ.)"""
    page, ghi, phien = _mo_popup_loc_trang_thai(mo_trang, db, monkeypatch)
    r = khung_rect(page)
    page.evaluate("() => { window.__boTrangThai = true; }")
    page.route("**/giai/chuot", lambda route: route.abort())
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    page.mouse.down()
    page.mouse.move(r["x"] + 80, r["y"] + 62)
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 8)
    assert phien.ky == 1
    doi_gui(page)
    # Chữ "mất kết nối" (cạn lượt thử) che chữ báo; một `trang_thai` CÙNG kỳ 1 gỡ nó mà KHÔNG gọi `doiKy` (popup đã
    # học kỳ 1 từ phản hồi) ⇒ chữ "đồng bộ lại" lúc đó chỉ có thể do đường phản hồi đặt.
    page.evaluate("() => {" + _TRANG_THAI_KY_1 + "}")
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 3), \
        page.locator("#gc-note").inner_text()
    page.unroute("**/giai/chuot")


def test_phan_hoi_huy_mang_ky_mat_nut_bao_mat_cu_nhap_da_200(mo_trang, db, monkeypatch):
    """Ca CHỈ máy chủ biết: lô rê `seq` 0 hụt (cạn lượt thử), lô cú nhấp `seq` 1 đã được 200 nhưng nằm chờ sau chỗ hụt
    ở máy chủ (Set của popup rỗng). Đồng bộ chủ động ⇒ máy chủ huỷ, bỏ cú nhấp đang chờ ⇒ phản hồi mang `ky_mat_nut`
    = kỳ mới ⇒ popup BÁO "kéo lại". `trang_thai` thật bị bỏ; một `trang_thai` tổng hợp CÙNG kỳ 0 kích đồng bộ chủ động,
    một cái CÙNG kỳ 1 sau đó gỡ chữ "mất kết nối". ĐỘT BIẾN: phản hồi huỷ không chuyển `ky_mat_nut` ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_loc_trang_thai(mo_trang, db, monkeypatch)
    r = khung_rect(page)
    page.evaluate("() => { window.__boTrangThai = true; }")

    def chuot(route):
        if route.request.post_data_json.get("seq") == 0 and route.request.post_data_json.get("ky") == 0:
            route.abort()                            # lô 0 (chỉ rê) không bao giờ tới
        else:
            route.continue_()

    page.route("**/giai/chuot", chuot)
    page.mouse.move(r["x"] + 50, r["y"] + 50)
    page.wait_for_timeout(60)
    page.mouse.move(r["x"] + 120, r["y"] + 120)
    page.mouse.down()
    page.mouse.up()
    assert cho_trang(page, lambda: 200 in ghi.mat_chuot, 3), "lô cú nhấp phải được 200"
    assert cho_trang(page, lambda: phien._cho_lo, 3), "cú nhấp phải nằm chờ ở máy chủ"
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 0, 6), "lô 0 cạn lượt ⇒ chặn"
    page.evaluate("() => {" + _TRANG_THAI_KY_1.replace("ky: 1, ky_mat_nut: 0", "ky: 0, ky_mat_nut: 0") + "}")
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5), "phải đồng bộ chủ động"
    assert phien.ky == 1 and phien.ky_mat_nut == 1
    doi_gui(page)
    page.evaluate("() => {" + _TRANG_THAI_KY_1.replace("ky_mat_nut: 0", "ky_mat_nut: 1") + "}")
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text(), 3), \
        page.locator("#gc-note").inner_text()
    page.unroute("**/giai/chuot")


def test_lo_ky_cu_bi_400_toi_muon_khong_giet_cu_keo_ky_moi(mo_trang, db, monkeypatch):
    """Review #54 S1 (phía popup): lô kỳ 0 treo, kỳ 1 về, người bắt đầu cú kéo MỚI; rồi lô kỳ 0 nhận 400 ⇒ popup KHÔNG bỏ
    cú kéo kỳ 1 (máy chủ không huỷ nó) ⇒ `up` vẫn được gửi, không kẹt nút. ĐỘT BIẾN: mọi 400 đều `boCuChi` ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = []

    def chuot(route):
        if route.request.post_data_json.get("ky") == 0 and not giu:
            giu.append(route)
        else:
            route.continue_()

    page.route("**/giai/chuot", chuot)
    page.mouse.move(r["x"] + 50, r["y"] + 50)
    assert cho_trang(page, lambda: len(giu) == 1, 5)
    _doi_ky(phien, 1)
    _hoc_ky_moi(page, ghi, r, 1)
    n = len(ghi.chuot)
    page.mouse.move(r["x"] + 300, r["y"] + 300)
    page.mouse.down()
    page.mouse.move(r["x"] + 320, r["y"] + 305)
    assert cho_trang(page, lambda: any(e["k"] == "down" for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), 5)
    giu[0].fulfill(status=400, content_type="application/json", body='{"detail": "Điểm ngoài khung."}')
    assert cho_trang(page, lambda: 400 in ghi.mat_chuot, 5)
    page.mouse.up()
    assert cho_trang(page, lambda: any(e["k"] == "up" for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), 5), \
        "400 của lô kỳ cũ không được bỏ cú kéo kỳ mới"
    page.unroute("**/giai/chuot")


def test_trang_thai_ky_cu_toi_sau_phan_hoi_huy_khong_lui_ky(mo_trang, db, monkeypatch):
    """Kỳ chỉ tăng: popup đã học kỳ 1 từ phản hồi huỷ, rồi một `trang_thai` chụp TRƯỚC lần huỷ (kỳ 0) mới tới (đua SSE với
    HTTP) ⇒ KHÔNG lùi về kỳ 0; cú kéo kế mang kỳ 1, `seq` 0, tới máy chủ (không `ky_cu`). ĐỘT BIẾN: nhận mọi kỳ khác
    (`!==`) ⇒ lô kế mang kỳ 0 ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_loc_trang_thai(mo_trang, db, monkeypatch)
    r = khung_rect(page)
    page.evaluate("() => { window.__boTrangThai = true; }")
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5)
    assert phien.ky == 1
    doi_gui(page)
    page.evaluate("() => {" + _TRANG_THAI_KY_1.replace("ky: 1, ky_mat_nut: 0", "ky: 0, ky_mat_nut: 0") + "}")
    doi_gui(page, 100)
    n = len(ghi.chuot)
    _keo(page, r, 300, 300)
    assert cho_trang(page, lambda: any(e["k"] == "up" for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), 5)
    doi_gui(page)
    moi = sorted(_lo_gui_sau(ghi, n), key=lambda x: x["seq"])
    assert all(lo["ky"] == 1 for lo in moi) and moi[0]["seq"] == 0, moi
    assert 409 not in ghi.mat_chuot[-len(moi):]


def test_hoc_ky_tu_phan_hoi_huy_khi_tu_bo_gesture_khong_bao_chong(mo_trang, db, monkeypatch):
    """Popup tự bỏ gesture (blur ⇒ chữ "mất con trỏ") ⇒ phản hồi huỷ mang kỳ mới (và `ky_mat_nut` mới vì máy chủ bỏ
    `down` chưa phát) ⇒ học kỳ im lặng về chữ: giữ chữ "mất con trỏ", không đổi sang "đồng bộ lại"; lô kế mang kỳ 1,
    `seq` 0 (dù `trang_thai` bị bỏ). ĐỘT BIẾN: `doiKy` ghi đè `biNgat` đã có ⇒ ĐỎ; bỏ học kỳ từ phản hồi (lô kế mang
    kỳ 0) ⇒ ĐỎ; gọi `doiKy` TRƯỚC cổng hiệu lực (cổng thoát sớm, không vẽ lại ⇒ chữ kẹt "đang huỷ") ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_loc_trang_thai(mo_trang, db, monkeypatch)
    r = khung_rect(page)
    page.evaluate("() => { window.__boTrangThai = true; }")
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5)
    assert phien.ky == 1 and phien.ky_mat_nut == 1
    doi_gui(page)
    note = page.locator("#gc-note").inner_text()
    assert "Cửa sổ vừa mất con trỏ" in note and "Đã đồng bộ lại" not in note, note
    n = len(ghi.chuot)
    _keo(page, r, 300, 300)
    assert cho_trang(page, lambda: len(_lo_gui_sau(ghi, n)) >= 1, 5)
    moi = sorted(_lo_gui_sau(ghi, n), key=lambda x: x["seq"])
    assert moi[0]["ky"] == 1 and moi[0]["seq"] == 0, moi[0]


def test_doi_ky_bo_su_kien_dang_gom_cua_ky_cu(mo_trang, db, monkeypatch):
    """Cú nhấn còn trong bộ gom (chưa xả — 40 ms) đúng lúc `trang_thai` mang kỳ mới tới ⇒ `down` đó thuộc kỳ đã
    bỏ, phải bị BỎ cùng gesture: gửi nó ở kỳ mới là `down` không bao giờ có `up` (gesture đã bỏ ⇒ thả chuột không
    gửi gì) ⇒ nút trên trang KẸT nhấn. `trang_thai` được bắn trong CÙNG lượt JS với cú nhấn (bắt EventSource của
    popup) để thứ tự xác định. ĐỘT BIẾN: `doiKy` không xoá `buf` ⇒ ĐỎ."""
    page, ghi, phien = _mo_popup_bat_es(mo_trang, db, monkeypatch)
    n = len(ghi.chuot)
    page.evaluate("() => {" + _con_tro(page, "pointerdown", 300, 300, 1) + _TRANG_THAI_KY_1 + "}")
    page.evaluate("() => {" + _con_tro(page, "pointerup", 300, 300, 0) + "}")
    doi_gui(page)
    _keo(page, khung_rect(page), 400, 300)
    assert cho_trang(page, lambda: any(e["k"] == "up" for lo in _lo_gui_sau(ghi, n) for e in lo["su_kien"]), 5)
    doi_gui(page)
    moi = sorted(_lo_gui_sau(ghi, n), key=lambda x: x["seq"])
    assert all(lo["ky"] == 1 for lo in moi)
    assert [e["k"] for lo in moi for e in lo["su_kien"] if e["k"] != "move"] == ["down", "up"], moi


def test_ky_doi_giua_luc_thu_lai_huy_thi_thoi_gui(mo_trang, db, monkeypatch):
    """Lệnh huỷ kỳ 0 trượt (500) đúng lúc kỳ 1 đã về ⇒ máy chủ đã tự huỷ khi đổi kỳ: KHÔNG thử lại (lần thử lại
    chỉ là một POST mang kỳ cũ, chắc chắn bị 409). Lần trượt được thả SAU khi popup học kỳ 1 nên thứ tự xác định.
    ĐỘT BIẾN: bỏ `return "ky_cu"` khi kỳ đổi giữa các lần thử ⇒ có lệnh huỷ thứ 2 ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 600.0)
    _gia_ky(monkeypatch)
    page, ghi, _, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = chan_lenh_huy(page, 1, treo=True)
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: len(giu) == 1, 5)
    _doi_ky(phien, 1)
    assert cho_trang(page, lambda: "Cửa sổ vừa mất con trỏ" in page.locator("#gc-note").inner_text(), 5)
    _hoc_ky_moi(page, ghi, r, 1)
    giu[0].fulfill(status=500, content_type="application/json", body='{"detail": "giả lập lỗi"}')
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5)
    doi_gui(page, 600)                       # > THU_LAI_CHO_MS: lần thử lại (nếu có) đã kịp gửi
    assert [l["lenh"] for l in ghi.lenh].count("huy_gesture") == 1
    assert page.locator(".gc-frame.dieu-khien").count() == 1



# ---------------------------------------------------------------------------
# Kỳ (`ky`) với MÁY CHỦ THẬT (không giả): request treo thả muộn, đứt SSE thật, lộn xộn, không kẹt chặn
# ---------------------------------------------------------------------------

def _phat_ra(phien):
    """Các loại sự kiện máy chủ sẽ phát lên trang (lấy hết hàng đợi)."""
    return [e.k for e in phien.den_han(gc.dong_ho() + 100)]


def test_lo_cu_treo_tha_muon_sau_doi_tay_khoa_khong_phat(mo_trang, db):
    """Mạng giả lập THẬT: lô `down` của A bị TREO (đã lên dây, chưa tới); trong lúc đó khoá qua tay B rồi về A
    (máy chủ huỷ ⇒ kỳ mới); rồi lô treo được THẢ. Máy chủ phải trả 409 `ky_cu` và KHÔNG phát `down` cũ (main:
    lô cũ có thể thành "đúng thứ tự" và được phát = nộp nhầm). Cú kéo kế tiếp mang kỳ mới, `seq` 0.
    ĐỘT BIẾN: bỏ kiểm `ky` trong `nhan_lo` ⇒ `down` cũ được nhận ⇒ ĐỎ."""
    page, ghi, jid, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    tk = ghi.token_sse[-1]
    giu = []

    def chan(route):
        if '"down"' in (route.request.post_data or "") and not giu:
            giu.append(route)                      # treo: request đã lên dây, chưa tới máy chủ
        else:
            route.continue_()

    page.route("**/giai/chuot", chan)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    assert cho_trang(page, lambda: len(giu) == 1, 5)
    ky_truoc = phien.ky
    with phien.khoa:                               # khoá qua tay B rồi về A (như A đứt SSE, B chen vào)
        phien.nha_khoa(tk, NGUOI)
        assert phien.nhan_khoa("token-bbbbbbbb", NGUOI)
        phien.nha_khoa("token-bbbbbbbb", NGUOI)
        assert phien.nhan_khoa(tk, NGUOI)
    assert phien.ky > ky_truoc
    _phat_ra(phien)
    giu[0].continue_()                             # lô cũ tới SAU khi máy chủ đã sang kỳ mới
    assert cho_trang(page, lambda: 409 in ghi.mat_chuot, 5), ghi.mat_chuot
    page.mouse.up()
    doi_gui(page)
    assert "down" not in _phat_ra(phien), "lô tạo trước lần huỷ không được phát"
    page.unroute("**/giai/chuot")
    assert cho_trang(page, lambda: "Đã đồng bộ lại với máy chủ" in page.locator("#gc-note").inner_text()
                     or page.locator(".gc-frame.dieu-khien").count() == 1, 5)
    n = len(ghi.chuot)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 1, 6)
    _keo(page, r, 300, 300)
    assert cho_trang(page, lambda: any(lo.get("ky") == phien.ky for lo in ghi.chuot[n:]), 5)
    moi = [lo for lo in ghi.chuot[n:] if lo.get("ky") == phien.ky]
    assert moi[0]["seq"] == 0, moi[0]
    assert cho_trang(page, lambda: "up" in [e.k for e in phien.den_han(gc.dong_ho() + 100)] or
                     phien.expected_seq >= 1, 5)


def test_sse_dut_that_giua_cu_keo_cung_token_van_phat_du(mo_trang, db):
    """K2 với SSE đứt THẬT (luồng máy chủ dừng ⇒ `onerror`, nối lại CÙNG token): nối lại không huỷ ⇒ kỳ KHÔNG
    đổi ⇒ cú kéo đang dở vẫn tới đủ `down … up` (như main). ĐỘT BIẾN: đổi kỳ mỗi lần cấp khoá (id kết nối) ⇒
    phần sau của cú kéo bị `ky_cu`, không có `up` ⇒ ĐỎ."""
    page, ghi, jid, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    n_sse = len(ghi.token_sse)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.mouse.move(r["x"] + 120, r["y"] + 102)
    assert cho_trang(page, lambda: any(e["k"] == "down" for lo in ghi.chuot for e in lo["su_kien"]), 5)
    ky_truoc = phien.ky
    with models._connect(db) as conn:              # luồng SSE kiểm quyền mỗi giây ⇒ tự dừng
        conn.execute("UPDATE jobs SET nguoi_tao = ? WHERE id = ?", ("khac@x.vn", jid))
    try:
        assert cho_trang(page, lambda: "Mất kết nối tới máy chủ" in page.locator("#gc-note").inner_text(), 8)
    finally:
        with models._connect(db) as conn:
            conn.execute("UPDATE jobs SET nguoi_tao = ? WHERE id = ?", (NGUOI, jid))
    assert cho_trang(page, lambda: len(ghi.token_sse) > n_sse and phien.co_nguoi_giu(), 10), "phải nối lại"
    page.mouse.move(r["x"] + 140, r["y"] + 104)
    page.mouse.up()
    doi_gui(page, 500)
    assert phien.ky == ky_truoc, "nối lại cùng token không được đổi kỳ"
    loai = _phat_ra(phien)
    assert "down" in loai and "up" in loai, loai


def test_lo_toi_lech_thu_tu_van_phat_du_dung_thu_tu(mo_trang, db):
    """Lộn xộn thật: lô `down` bị giữ lại, các lô sau (move, up) tới trước; thả lô `down` ⇒ máy chủ sắp lại và
    phát đủ `down … up` đúng thứ tự, KHÔNG đổi kỳ (lộn xộn không phải sự cố). ĐỘT BIẾN: đổi kỳ khi nhận lô
    không liền kề ⇒ ĐỎ."""
    page, ghi, jid, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = []

    def chan(route):
        if '"down"' in (route.request.post_data or "") and not giu:
            giu.append(route)
        else:
            route.continue_()

    page.route("**/giai/chuot", chan)
    page.mouse.move(r["x"] + 100, r["y"] + 100)
    page.mouse.down()
    page.wait_for_timeout(60)
    page.mouse.move(r["x"] + 120, r["y"] + 102)
    page.wait_for_timeout(60)
    page.mouse.up()
    assert cho_trang(page, lambda: len(giu) == 1 and
                     any(e["k"] == "up" for lo in ghi.chuot for e in lo["su_kien"]), 5)
    assert cho_trang(page, lambda: len(phien._cho_lo) >= 1, 5), "lô sau phải đang đợi lô `down`"
    ky_truoc = phien.ky
    giu[0].continue_()
    assert cho_trang(page, lambda: not phien._cho_lo, 5)
    loai = _phat_ra(phien)
    assert loai.index("down") < loai.index("up") and phien.ky == ky_truoc, loai
    page.unroute("**/giai/chuot")


def test_cho_ky_khong_ket_trang_thai_nhac_lai_go_chan(mo_trang, db, monkeypatch):
    """B2 — không đường nào chặn kéo vĩnh viễn: một lô nhận 409 `ky_cu` (giả) trong khi kỳ máy chủ KHÔNG đổi
    ⇒ popup tạm chặn; `trang_thai` nhắc lại (cùng kỳ) ⇒ gỡ chặn. ĐỘT BIẾN: chỉ gỡ `choKy` khi kỳ đổi ⇒ kẹt ⇒ ĐỎ."""
    import web.giai_captcha_api as api_mod
    monkeypatch.setattr(api_mod, "SSE_NHAC_LAI_GIAY", 1.0)
    page, ghi, jid, phien = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.route("**/giai/chuot", lambda route: route.fulfill(
        status=409, content_type="application/json",
        body='{"detail": {"ma": "ky_cu", "ky": %d, "thong_diep": "x"}}' % phien.ky))
    page.mouse.move(r["x"] + 60, r["y"] + 60)
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 0, 5), "phải tạm chặn"
    page.unroute("**/giai/chuot")
    assert cho_trang(page, lambda: page.locator(".gc-frame.dieu-khien").count() == 1, 5), "nhắc lại phải gỡ"


def test_lenh_huy_treo_het_gio_thi_thu_lai_roi_mo_chan(mo_trang, db):
    """`fetch` treo ⇒ timeout 8 s ⇒ lệnh thử lại được nhận ⇒ mở chặn; cú nhấn sau đó tới máy chủ.
    Lệnh huỷ có timeout RIÊNG 3 s (ĐP-729) ⇒ mở chặn trong vài giây, không phải 8 s.
    ĐỘT BIẾN: bỏ `signal` ⇒ ĐỎ (kẹt chặn tới hết lượt); lệnh huỷ dùng timeout 8 s chung ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    giu = chan_lenh_huy(page, 1, treo=True)
    _keo_roi_blur(page, r)
    page.mouse.up()
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 6)
    page.mouse.move(r["x"] + 300, r["y"] + 300)
    page.mouse.down()
    page.mouse.up()
    doi_gui(page)
    assert len(giu) == 1 and [l["lenh"] for l in ghi.lenh].count("huy_gesture") == 2
    assert _so(ghi, "down") == 2


def test_mo_chan_bo_ca_su_kien_bo_gom_vua_nhat_luc_dang_chan(mo_trang, db):
    """ĐP-729 NIT-3: sự kiện bộ gom nhặt trong lúc chặn mà chưa tới lượt `xaLo` xoá thì cũng phải bỏ khi
    mở chặn. Bắn một hover NGAY trước khi popup nhận phản hồi 200 của `huy_gesture`. ĐỘT BIẾN: không
    xoá `buf` lúc mở chặn ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    page.evaluate("""() => { const f = window.fetch;
        window.fetch = async (u, o) => {
            const res = await f(u, o);
            if (String((o && o.body) || "").includes("huy_gesture")) {
                const a = document.querySelector('#gc-anh').getBoundingClientRect();
                document.querySelector('#gc-khung').dispatchEvent(new PointerEvent('pointermove', {
                    pointerId: 1, pointerType: 'mouse', bubbles: true, buttons: 0,
                    clientX: a.x + a.width / 2, clientY: a.y + a.height / 2 }));
            }
            return res; }; }""")
    _keo_roi_blur(page, r)
    page.mouse.up()
    truoc = len(ghi.su_kien())
    assert cho_trang(page, lambda: ("lenh_ve", "huy_gesture") in ghi.thu_tu, 5)
    doi_gui(page)
    assert len(ghi.su_kien()) == truoc, "hover nhặt trong lúc chặn không được gửi sau khi mở chặn"


def test_da_giai_khi_dang_huy_di_sau_lenh_huy(mo_trang, db):
    """Bấm "Đã giải xong" khi lệnh huỷ còn treo ⇒ `da_giai` gửi SAU khi `huy_gesture` được trả lời.
    ĐỘT BIẾN: `guiLenh` không chờ lệnh huỷ ⇒ ĐỎ."""
    page, ghi, _, _ = mo_popup_dang_giai(mo_trang, db)
    r = khung_rect(page)
    tre_truoc_khi_gui(page, "/giai/lenh", 600, chua="huy_gesture")
    _keo_roi_blur(page, r)
    page.mouse.up()
    page.click("#gc-actions button:has-text('Đã giải xong')")
    assert cho_trang(page, lambda: [l["lenh"] for l in ghi.lenh] == ["huy_gesture", "da_giai"], 5)
    assert ghi.thu_tu.index(("lenh_ve", "huy_gesture")) < ghi.thu_tu.index(("lenh_gui", "da_giai"))


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
