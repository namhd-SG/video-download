"""Giải captcha — bất biến TÍCH HỢP với Chromium THẬT, đi hết đường: uvicorn thật + worker thật
(`process_job`) + Playwright thật + trang tĩnh trên 127.0.0.1 (KHÔNG TikTok, không mạng ngoài).

"Người" là test: nó nối SSE lấy khung, POST lô chuột/lệnh qua HTTP y như popup. Phía TRANG ghi lại
mọi sự kiện nó nhận (sendBeacon về máy chủ tĩnh) để so với những gì người đã gửi — đó là phép đo
bất biến phát lại: cùng thứ tự, `floor(x_người × hệ số) == clientX`, tổng thời lượng lệch ≤ 3 %,
và không có sự kiện nào người không tạo (ĐP-606).

Viewport 1280×900, khung 800 ⇒ hệ số 1,6 tự sinh phần lẻ ≥ 0,5 (toạ độ nguyên không phân định được
đột biến "làm tròn").
"""
from __future__ import annotations

import http.server
import json
import math
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi import HTTPException, Request

from giai_captcha_http import Sse, cho, goi
from tiktok_music_downloader import scraper as scraper_mod
from web import giai_captcha as gc
from web import giai_captcha_worker as worker
from web import models, profile_theo_job
from web import models_giai_captcha as mgc
from web.queue import process_job

CHU = "chu@x.vn"
TOKEN = "token-aaaaaaaa"
HE_SO = 1280.0 / 800.0
KHUNG_W = 800.0

TRANG_HTML = """<!doctype html><html><body style="margin:0;height:3000px">
<a id=a1 href="/other" style="position:absolute;left:20px;top:20px;width:100px;height:30px;background:#ccc">noi bo</a>
<a id=a3 href="http://localhost:%(port)d/@u" style="position:absolute;left:20px;top:100px;width:100px;height:30px;background:#ccc">khac mien</a>
<a id=a2 href="http://localhost:%(port)d/blank" target=_blank style="position:absolute;left:20px;top:180px;width:100px;height:30px;background:#ccc">blank</a>
<script>
const T0 = performance.timeOrigin; let n = 0;
function lg(a) { navigator.sendBeacon('/log', JSON.stringify([T0, n++].concat(a))); }
for (const t of ['mousedown', 'mousemove', 'mouseup'])
  addEventListener(t, e => lg([t, e.clientX, e.clientY, e.buttons, e.pageY, performance.now(), e.isTrusted]), true);
addEventListener('wheel', e => lg(['wheel', e.clientX, e.clientY, e.buttons, e.pageY, performance.now(), e.deltaY, e.isTrusted]),
                 {capture: true, passive: true});
fetch('/api/post/item_list/').then(r => r.text()).then(t => lg(['feed', t.length]));
</script></body></html>"""


class SuKienTrang(NamedTuple):
    tai: float        # `performance.timeOrigin` của lần tải trang
    n: int            # số thứ tự phía trang trong lần tải đó
    loai: str
    cx: int           # clientX
    cy: int           # clientY
    buttons: int
    py: float         # pageY
    t: float          # performance.now()
    dy: float         # deltaY (wheel)
    tin: bool         # isTrusted


class MayChuTrang:
    """Trang tĩnh + điểm nhận log. Ghi lại cả HOST header của mọi GET để biết có request nào lọt ra ngoài."""

    def __init__(self):
        self.log: list[list] = []
        self.hits: list[tuple[str, str]] = []
        self.khoa = threading.Lock()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                with outer.khoa:
                    outer.hits.append((self.headers.get("Host", ""), self.path))
                if self.path.startswith("/@u"):
                    b = (TRANG_HTML % {"port": outer.port}).encode()
                    ct = "text/html"
                elif self.path.startswith("/api/post/item_list"):
                    b, ct = b'{"itemList": [1, 2, 3]}', "application/json"
                else:
                    b, ct = b"<html>trang khac</html>", "text/html"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                bd = self.rfile.read(n)
                with outer.khoa:
                    outer.log.append(json.loads(bd))
                self.send_response(204)
                self.end_headers()

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def dong(self):
        self.srv.shutdown()

    def reset(self):
        with self.khoa:
            self.log.clear()
            self.hits.clear()

    def su_kien(self, loai=None):
        """Sự kiện chuột của trang theo THỨ TỰ THẬT (lần tải, rồi số thứ tự phía trang), không theo thứ tự tới."""
        with self.khoa:
            ds = [list(x) for x in self.log]
        ds.sort(key=lambda x: (x[0], x[1]))
        ra = []
        for x in ds:
            if x[2] == "wheel":
                ra.append(SuKienTrang(x[0], x[1], "wheel", x[3], x[4], x[5], x[6], x[7], x[8], x[9]))
            elif x[2] in ("mousedown", "mousemove", "mouseup"):
                ra.append(SuKienTrang(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], 0, x[8]))
        return [e for e in ra if loai is None or e.loai in loai]

    def so_lan_tai(self, path="/@u"):
        with self.khoa:
            return sum(1 for h, p in self.hits if p.startswith(path))

    def so_request_host_khac(self):
        with self.khoa:
            return sum(1 for h, _ in self.hits if h.startswith("localhost"))


@pytest.fixture(scope="module")
def trang():
    t = MayChuTrang()
    yield t
    t.dong()


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    import web.app as app_mod
    from web.auth import require_user

    tmp_ctx = tempfile.TemporaryDirectory(prefix="videodl-cr-")
    tmp = Path(tmp_ctx.name)
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    models.init_db(app_mod.DB_PATH)
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None

    def nguoi(request: Request) -> str:
        u = request.headers.get("x-test-user")
        if not u:
            raise HTTPException(status_code=401, detail="chưa đăng nhập")
        return u

    app_mod.app.dependency_overrides[require_user] = nguoi
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    han = time.monotonic() + 10
    while not server.started:
        assert th.is_alive() and time.monotonic() < han, "uvicorn không khởi động được"
        time.sleep(0.05)
    yield port, app_mod.DB_PATH, tmp
    server.should_exit = True
    th.join(timeout=8)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)
    tmp_ctx.cleanup()


@pytest.fixture(autouse=True)
def _moi_truong(monkeypatch, trang):
    monkeypatch.setenv(profile_theo_job.ENV_PROFILE_CAPTCHA, "1")
    monkeypatch.delenv(gc.ENV_DIEU_HUONG, raising=False)
    monkeypatch.setenv(gc.ENV_D_MS, "300")      # dư sức phủ jitter máy chủ tải cao ⇒ không có "tới trễ hơn D"
    gc._PHIEN.clear()
    scraper_mod._PROFILE_DANG_MO.clear()
    trang.reset()
    yield
    gc._PHIEN.clear()
    scraper_mod._PROFILE_DANG_MO.clear()


# ---------------------------------------------------------------------------
# "Người" + lượt giải thật
# ---------------------------------------------------------------------------

class LuotGiai:
    """Một lượt giải chạy thật: job `cho_giai` → worker thật nhặt → Chromium thật → `dang_giai`."""

    def __init__(self, monkeypatch, may_chu, trang, *, token=TOKEN):
        self.port, self.db, self.tmp = may_chu
        self.trang, self.token = trang, token
        self.da_dong_trang_moi: list = []
        self.pages_sau_dong: list[int] = []
        luu = self

        class DongTrangMoiGhi(worker._DongTrangMoi):
            def __call__(self, p):
                super().__call__(p)
                try:
                    luu.pages_sau_dong.append(len(p.context.pages))
                except Exception:  # noqa: BLE001
                    luu.pages_sau_dong.append(-1)
                luu.da_dong_trang_moi.append(self.so_dong)

        monkeypatch.setattr(worker, "_DongTrangMoi", DongTrangMoiGhi)
        self.jid = models.create_job(self.db, f"http://127.0.0.1:{trang.port}/@u", 5, CHU)
        assert mgc.chuyen_trang_thai(self.db, self.jid, "pending", "cho_xac_minh", ly_do="feed_rong")
        st, _ = goi(self.port, "POST", f"/jobs/{self.jid}/giai")
        assert st == 200
        self.sse = Sse(self.port, self.jid, token, timeout=40)
        assert self.sse.status == 200
        job = models.claim_next_pending_job(self.db, uu_tien_cho_giai=True)
        assert job["id"] == self.jid
        self.loi_thread: list = []

        def chay():
            try:
                process_job(self.db, self.tmp / "dl", self.tmp / "ck", job)
            except BaseException as exc:  # noqa: BLE001
                self.loi_thread.append(exc)

        self.thread = threading.Thread(target=chay, daemon=True)
        self.thread.start()
        self.t0 = time.monotonic()
        self.seq = 0
        self.da_tao: list[tuple] = []        # (k, x, y, buttons, t_ms) người đã gửi
        self.khung_dau = self.cho_khung()
        assert self.cho_trang_thai("dang_giai"), "khung đầu về ⇒ worker ghi `dang_giai`"

    def cho_khung(self):
        ev, d = self.sse.doc("khung")
        assert d is not None and d["deviceWidth"] == 1280, "khung đầu phải về từ Chromium thật"
        return d

    def cho_trang_thai(self, ten):
        han = time.monotonic() + 30
        while time.monotonic() < han:
            if models.get_job(self.db, self.jid)["trang_thai"] == ten:
                return True
            time.sleep(0.05)
        return False

    def t_ms(self):
        return (time.monotonic() - self.t0) * 1000.0

    def tao(self, k, x, y, buttons=0, **them):
        sk = {"k": k, "x": x, "y": y, "t": self.t_ms(), "buttons": buttons, **them}
        self.da_tao.append((k, x, y, buttons, sk["t"], them))
        return sk

    def gui_lo(self, su_kien, seq=None, token=None):
        # Như popup: gắn KỲ đang biết (đọc kỳ hiện tại của phiên ⇔ `trang_thai` mới nhất); kỳ đổi ⇒ đánh số lô
        # lại từ 0 (máy chủ đặt `expected_seq = 0` mỗi kỳ).
        ky = gc.lay_phien(self.jid).ky
        if ky != getattr(self, "ky_biet", 0):
            self.ky_biet = ky
            self.seq = 0
        if seq is None:
            seq = self.seq
            self.seq += 1
        so = seq
        return goi(self.port, "POST", f"/jobs/{self.jid}/giai/chuot",
                   body={"token": token or self.token, "ky": ky, "seq": so, "khung_w": KHUNG_W,
                         "su_kien": su_kien})

    def gui_ok(self, su_kien, **kw):
        st, ra = self.gui_lo(su_kien, **kw)
        assert st == 200, (st, ra)

    def phien_tre_qua_d(self) -> int:
        return gc.lay_phien(self.jid).tre_qua_d_tong()

    def lenh(self, lenh, token=None):
        return goi(self.port, "POST", f"/jobs/{self.jid}/giai/lenh", body={"token": token or self.token, "lenh": lenh})

    def keo_thoi_gian_thuc(self, ke_hoach):
        """`ke_hoach` = [(k, x, y, buttons, nghi_truoc_ms)]: tạo đúng nhịp thật, gom lô bằng đồng hồ 40 ms
        như popup (setTimeout từ sự kiện đầu của lô), mỗi lô bắn bằng MỘT luồng riêng (không chờ nhau ⇒ lô có
        thể tới lệch thứ tự ⇒ máy chủ phải sắp lại)."""
        luong: list = []
        ket_qua: list = []
        khoa = threading.Lock()
        tt = {"lo": [], "timer": None}

        def bay(l, so):
            ket_qua.append(self.gui_lo(l, seq=so)[0])

        def xa():
            with khoa:
                l, tt["lo"], tt["timer"] = tt["lo"], [], None
                if not l:
                    return
                so = self.seq
                self.seq += 1
                th = threading.Thread(target=bay, args=(l, so))
                luong.append(th)
                th.start()

        for k, x, y, b, nghi in ke_hoach:
            time.sleep(nghi / 1000.0)
            with khoa:
                tt["lo"].append(self.tao(k, x, y, b))
                if tt["timer"] is None:
                    tt["timer"] = threading.Timer(0.040, xa)
                    tt["timer"].start()
        time.sleep(0.15)
        xa()
        for th in list(luong):
            th.join(10)
        assert ket_qua and all(m == 200 for m in ket_qua), ket_qua

    def ket_thuc(self):
        job = models.get_job(self.db, self.jid)
        if job["trang_thai"] == "dang_giai":
            self.lenh("dung")
        self.thread.join(40)
        self.sse.dong_ket_noi()
        assert not self.thread.is_alive(), "luồng worker phải thoát"
        assert not self.loi_thread, self.loi_thread
        assert not scraper_mod.profile_dir_dang_mo(profile_theo_job.thu_muc_profile_job(self.db, self.jid))
        return models.get_job(self.db, self.jid)


@pytest.fixture
def luot(monkeypatch, may_chu, trang):
    lg = LuotGiai(monkeypatch, may_chu, trang)
    yield lg
    lg.ket_thuc()


def _doi_trang(trang, so_su_kien, giay=8.0):
    """Chờ tới khi trang đã ghi ≥ `so_su_kien` sự kiện chuột."""
    assert cho(lambda: len(trang.su_kien()) >= so_su_kien, giay), \
        f"trang mới nhận {len(trang.su_kien())}/{so_su_kien} sự kiện: {_thuc_te(trang.su_kien())}"


# ---------------------------------------------------------------------------
# Bất biến phát lại (tích hợp)
# ---------------------------------------------------------------------------

# Toạ độ kéo nằm NGOÀI mọi link của trang tĩnh: nhấn-kéo trên `<a>` làm Chromium bắt đầu kéo-thả liên kết
# (nuốt mousemove/mouseup) — không phải thứ cần đo ở đây.
KE_HOACH = [  # (k, x_khung, y_khung, buttons, nghỉ trước ms) — toạ độ để ×1,6 sinh phần lẻ ≥ 0,5
    ("move", 3, 107, 0, 0), ("move", 11, 109.3, 0, 16),
    ("down", 29.7, 150, 1, 60), ("move", 41.3, 150.7, 1, 16), ("move", 77.7, 151.3, 1, 16),
    ("move", 101.3, 152.9, 1, 250), ("move", 140.1, 153.7, 1, 16), ("move", 199.9, 155.1, 1, 400),
    ("move", 260.7, 156.9, 1, 16), ("move", 301.3, 157.3, 1, 150), ("move", 333.7, 158.1, 1, 150),
    ("up", 333.7, 158.1, 0, 16), ("move", 340.9, 170.3, 0, 400), ("move", 351.1, 171.7, 0, 16),
]
TEN_SU_KIEN = {"down": "mousedown", "move": "mousemove", "up": "mouseup"}


def _ky_vong(da_tao):
    return [(TEN_SU_KIEN[k], math.floor(x * HE_SO), math.floor(y * HE_SO), b) for k, x, y, b, _t, _ in da_tao]


def _thuc_te(su_kien_trang):
    return [(e.loai, e.cx, e.cy, e.buttons) for e in su_kien_trang]


def test_phat_lai_dung_thu_tu_toa_do_va_thoi_luong_khong_qua_3_phan_tram(luot, trang):
    """Phía TRANG: cùng thứ tự, `floor(x_người × 1,6) == clientX`, tổng thời lượng lệch ≤ 3 %.
    ĐỘT BIẾN: làm tròn toạ độ / nội suy thêm điểm / nén-giãn nhịp / bỏ sắp lại theo seq ⇒ ĐỎ."""
    luot.keo_thoi_gian_thuc(KE_HOACH)
    _doi_trang(trang, len(KE_HOACH))
    time.sleep(0.6)  # chờ xem có sự kiện THỪA nào lọt tới trang không
    tren_trang = trang.su_kien(("mousedown", "mousemove", "mouseup"))
    assert _thuc_te(tren_trang) == _ky_vong(luot.da_tao), \
        "đúng thứ tự, đúng toạ độ (floor), đúng `buttons`, KHÔNG thừa/thiếu điểm"
    assert all(e.tin for e in tren_trang), "isTrusted"
    # Tổng thời lượng: từ sự kiện đầu tới sự kiện cuối, đo ở trang (performance.now cùng một lần tải).
    goc = luot.da_tao[-1][4] - luot.da_tao[0][4]
    that = tren_trang[-1].t - tren_trang[0].t
    assert goc > 1500, f"chuỗi phải đủ dài để 3% có nghĩa (gốc {goc:.0f} ms)"
    assert abs(that - goc) / goc <= 0.03, f"gốc {goc:.1f} ms vs trang {that:.1f} ms"
    assert luot.phien_tre_qua_d() == 0
    # Hover phát với `buttons:0` (đột biến gán buttons:1 cho mọi move ⇒ ĐỎ): hai move đầu.
    assert [e.buttons for e in tren_trang[:2]] == [0, 0]


def test_cuon_cua_nguoi_lan_dung_delta_va_khong_cong_scroll_offset(luot, trang):
    """Cuộn 400 rồi nhấn `y=50`: trang nhận `clientY = floor(50×1,6)` (CDP Input tính theo VIEWPORT),
    `pageY = clientY + 400`. ĐỘT BIẾN: cộng `scrollOffsetY` của khung ⇒ clientY lệch ⇒ ĐỎ."""
    luot.gui_ok([luot.tao("wheel", 100, 100, 0, dx=0, dy=400)])
    time.sleep(1.0)    # để khung mới (scrollOffsetY=400) về trước khi nhấn
    luot.gui_ok([luot.tao("down", 50, 50, 1)])
    time.sleep(0.2)
    luot.gui_ok([luot.tao("up", 50, 50, 0)])
    _doi_trang(trang, 3)
    wheel = trang.su_kien(("wheel",))
    down = trang.su_kien(("mousedown",))
    assert len(wheel) == 1 and wheel[0].dy == 400
    assert down[0].cy == math.floor(50 * HE_SO) == 80, "clientY không cộng scrollOffset"
    assert down[0].py - down[0].cy == 400, "pageY = clientY + 400 (trang đã cuộn đúng 400)"


def test_nut_phai_va_delta_mode_khong_toi_trang(luot, trang):
    assert luot.gui_lo([luot.tao("down", 30, 30, 2)])[0] == 200
    assert luot.gui_lo([luot.tao("wheel", 30, 30, 0, dx=0, dy=40, delta_mode=1)])[0] == 400
    time.sleep(0.8)
    assert trang.su_kien() == []


# ---------------------------------------------------------------------------
# Ngăn điều hướng, trang mới
# ---------------------------------------------------------------------------

def _bam_css(luot, x_css, y_css):
    x, y = x_css / HE_SO, y_css / HE_SO
    luot.gui_ok([luot.tao("move", x, y, 0)])
    time.sleep(0.15)
    luot.gui_ok([luot.tao("down", x, y, 1)])
    time.sleep(0.1)
    luot.gui_ok([luot.tao("up", x, y, 0)])


@pytest.fixture
def luot_chan(monkeypatch, may_chu, trang):
    monkeypatch.setenv(gc.ENV_DIEU_HUONG, gc.DIEU_HUONG_CHAN)
    lg = LuotGiai(monkeypatch, may_chu, trang)
    yield lg
    lg.ket_thuc()


def test_che_do_chan_bam_link_khac_duong_dan_va_khac_mien_trang_dung_yen(luot_chan, trang):
    """Chế độ CHẶN: bấm link /other (cùng miền, đường dẫn khác) và link sang `localhost` (khác host) ⇒ trang
    ĐỨNG YÊN, máy chủ tĩnh KHÔNG nhận GET /other nào, trang chỉ tải một lần.
    ĐỘT BIẾN: bỏ `Fetch.enable` ⇒ GET /other tới được máy chủ ⇒ ĐỎ."""
    luot = luot_chan
    _bam_css(luot, 50, 35)     # a1: /other, cùng miền
    _bam_css(luot, 50, 115)    # a3: localhost:… (khác host)
    time.sleep(1.0)
    assert trang.so_lan_tai("/other") == 0, "request điều hướng bị chặn TRƯỚC khi tới máy chủ"
    assert trang.so_request_host_khac() == 0, "không request nào sang host khác"
    assert trang.so_lan_tai("/@u") == 1, "trang không bị tải lại"
    # Trang còn sống và vẫn nhận chuột đúng chỗ.
    luot.gui_ok([luot.tao("move", 200, 200, 0)])
    assert cho(lambda: trang.su_kien(("mousemove",))[-1:] and
               trang.su_kien(("mousemove",))[-1].cx == math.floor(200 * HE_SO), 5)


def test_che_do_log_cho_qua_duong_dan_khac_cung_mien_nhung_chan_khac_mien(luot, trang, caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="videodl.web"):
        _bam_css(luot, 50, 115)    # a3: khác host ⇒ vẫn chặn
        time.sleep(0.8)
        assert trang.so_request_host_khac() == 0
        _bam_css(luot, 50, 35)     # a1: /other cùng miền ⇒ cho qua + log host/path
        assert cho(lambda: trang.so_lan_tai("/other") == 1, 6), "chế độ LOG cho qua đường dẫn cùng miền"
    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert "path=/other" in texto and "host=127.0.0.1" in texto
    assert "CHẶN" in texto and "cho qua (chế độ log)" in texto


def test_target_blank_trang_moi_bi_dong_va_chi_con_mot_trang(luot, trang):
    """ĐỘT BIẾN: bỏ đóng trang mới ⇒ `len(ctx.pages)` ≠ 1 ⇒ ĐỎ."""
    _bam_css(luot, 50, 195)    # a2 target=_blank
    assert cho(lambda: luot.da_dong_trang_moi, 8), "worker phải đóng trang mới"
    assert luot.pages_sau_dong == [1], f"sau khi đóng chỉ còn 1 trang, thực tế {luot.pages_sau_dong}"


# ---------------------------------------------------------------------------
# Gesture dở / popup tải lại / ĐP-606
# ---------------------------------------------------------------------------

def test_gesture_do_khong_co_mouseup_nao_toi_trang_reload_dung_mot_lan_roi_keo_lai_nhan_du(luot, trang):
    """Nhấn + kéo rồi điểm NGOÀI KHUNG (400 ⇒ huỷ gesture) ⇒ trang KHÔNG nhận `mouseup` nào, worker tải lại
    đúng 1 lần; kéo mới sau đó nhận đủ mousedown/move/up. ĐỘT BIẾN: phát `mouseReleased` khi gesture dở ⇒ ĐỎ."""
    luot.gui_ok([luot.tao("move", 100, 100, 0)])
    time.sleep(0.1)
    luot.gui_ok([luot.tao("down", 100, 100, 1)])
    luot.gui_ok([luot.tao("move", 130, 100, 1)])
    _doi_trang(trang, 3)
    st, ra = luot.gui_lo([luot.tao("move", 900, 100, 1)])           # ngoài khung ngang
    assert st == 400
    assert cho(lambda: trang.so_lan_tai("/@u") == 2, 15), "đúng 1 lần tải lại"
    ev, d = luot.sse.doc("bi_ngat")
    assert d["so_lan_tai_lai"] == 1
    assert trang.su_kien(("mouseup",)) == [], "tool KHÔNG tự nhả chuột"
    phien = gc.lay_phien(luot.jid)
    assert phien.so_gesture_bo_do == 1 and phien.so_lan_tai_lai == 1
    time.sleep(1.2)                                                  # cho trang tải xong
    truoc = len(trang.su_kien())
    luot.gui_ok([luot.tao("down", 60, 60, 1)])
    luot.gui_ok([luot.tao("move", 80, 60, 1)])
    luot.gui_ok([luot.tao("up", 80, 60, 0)])
    assert cho(lambda: len(trang.su_kien()) >= truoc + 3, 8)
    lan_tai_cuoi = max(e.tai for e in trang.su_kien())
    sau = [e.loai for e in trang.su_kien() if e.tai == lan_tai_cuoi]
    assert sau == ["mousedown", "mousemove", "mouseup"], "lần kéo mới trên trang đã tải lại nhận ĐỦ bộ"
    # Bất biến ĐP-606: mọi sự kiện trang nhận (mọi lần tải) đều có bản gốc của người, đúng thứ tự.
    goc = _ky_vong([x for x in luot.da_tao if x[1] <= KHUNG_W])
    nhan = _thuc_te(trang.su_kien(("mousedown", "mousemove", "mouseup")))
    it = iter(goc)
    assert all(any(e == g for g in it) for e in nhan), f"sự kiện trang nhận không có bản gốc của người: {nhan}"


def test_popup_tai_lai_token_moi_seq_ve_0_duoc_nhan_khong_ket(luot, trang):
    luot.gui_ok([luot.tao("move", 100, 100, 0)])
    luot.gui_ok([luot.tao("down", 100, 100, 1)])
    luot.gui_ok([luot.tao("move", 110, 100, 1)])
    _doi_trang(trang, 3)
    luot.sse.dong_ket_noi()                               # popup đóng/tải lại
    phien = gc.lay_phien(luot.jid)
    assert cho(lambda: not phien.co_nguoi_giu(), 5)
    moi = "token-cccccccc"
    sse2 = Sse(luot.port, luot.jid, moi, timeout=30)
    assert sse2.doc("trang_thai")[1]["vai"] == "dieu_khien"
    st, _ = luot.gui_lo([luot.tao("move", 200, 200, 0)], seq=0, token=moi)   # seq=0 của token mới được nhận
    assert st == 200
    assert cho(lambda: phien.so_gesture_bo_do == 1, 10), "gesture dở của token cũ bị huỷ ⇒ worker tải lại"
    assert trang.su_kien(("mouseup",)) == []
    luot.token = moi          # từ đây người điều khiển là token mới (để teardown ra lệnh `dung` đúng người)
    sse2.dong_ket_noi_sau = True
    luot.sse = sse2


# ---------------------------------------------------------------------------
# da_giai (đường thật) — ranh giới và kết quả
# ---------------------------------------------------------------------------

def test_da_giai_trang_co_feed_di_tiep_va_nhan_su_kien_tool_chi_SAU_khi_dong_khung(monkeypatch, luot, trang):
    sk_truoc = {}
    that = scraper_mod._auto_scroll

    def auto_scroll_nhanh(page, mv, sp, ir):
        sk_truoc["so_su_kien_nguoi"] = len(trang.su_kien())
        return that(page, mv, 0.05, 2)

    monkeypatch.setattr(scraper_mod, "_auto_scroll", auto_scroll_nhanh)
    luot.gui_ok([luot.tao("move", 120, 120, 0)])
    _doi_trang(trang, 1)
    assert luot.lenh("da_giai")[0] == 200
    ev, d = luot.sse.doc("ket_thuc")
    assert d["trang_thai"] == "running", "SSE khung đóng bằng `ket_thuc` TRƯỚC khi quét"
    luot.thread.join(60)
    job = models.get_job(luot.db, luot.jid)
    # Trang local có feed (có dữ liệu) và không có link video ⇒ lượt quét xong, không phải "captcha chưa xong".
    assert job["trang_thai"] == "failed" and job["ly_do_dung"] == "source_empty"
    assert sk_truoc["so_su_kien_nguoi"] == 1
    assert trang.su_kien(("wheel",)), "`_auto_scroll` của tool chạy SAU lệnh của người (ranh giới ĐP-606)"
    assert trang.so_lan_tai("/@u") == 2, "đúng MỘT lần tải lại sau 'Đã giải xong'"


def test_da_giai_trang_khong_co_feed_van_bi_chan_khong_cuon(monkeypatch, may_chu, trang):
    """Không có feed nào sau khi tải lại (0/0) ⇒ KHÔNG `_auto_scroll`, về cho_xac_minh 'captcha chưa xong'."""
    monkeypatch.setattr(scraper_mod, "_auto_scroll",
                        lambda *a, **k: pytest.fail("vẫn bị chặn mà tool cuộn"))
    monkeypatch.setattr(scraper_mod, "_FEED_API_MARKERS", ("/api/khong-co",))
    lg = LuotGiai(monkeypatch, may_chu, trang)
    lg.gui_ok([lg.tao("move", 120, 120, 0)])
    _doi_trang(trang, 1)
    lg.lenh("da_giai")
    lg.thread.join(60)
    job = models.get_job(lg.db, lg.jid)
    assert job["trang_thai"] == "cho_xac_minh" and job["ly_do_dung"] == "captcha_chua_xong"
    assert trang.su_kien(("wheel",)) == [], "tool không sinh wheel nào"
    assert (lg.tmp / "profiles" / str(lg.jid)).is_dir(), "profile còn nguyên cho lần giải sau"
    lg.sse.dong_ket_noi()
