"""Playwright GIẢ thuần Python + đồng hồ giả cho test lượt giải captcha (worker/queue/models thật).

`TrangGia.wait_for_timeout` là nơi DUY NHẤT thời gian trôi (giống thật: callback CDP chỉ chạy trong
một lời gọi Playwright) và nơi chạy "kịch bản người" theo giờ giả. Không trình duyệt, không mạng.
"""
from __future__ import annotations

import itertools
from contextlib import contextmanager
from types import SimpleNamespace

from tiktok_music_downloader import scraper as scraper_mod
from web import giai_captcha as gc
from web import giai_captcha_worker as worker

KHUNG_META = {"offsetTop": 0, "pageScaleFactor": 1, "deviceWidth": 1280, "deviceHeight": 900,
              "scrollOffsetX": 0, "scrollOffsetY": 0, "timestamp": 1.0}
TOKEN = "token-aaaaaaaa"


class DongHoGia:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def troi(self, giay: float) -> None:
        self.t += giay


class CdpGia:
    def __init__(self, trang: "TrangGia"):
        self.trang = trang
        self.cb: dict[str, list] = {}
        self.goi: list[tuple[str, dict | None]] = []
        self.dang_chieu = False
        self.loi_khi_gui: dict[str, Exception] = {}

    def on(self, ev, cb):
        self.cb.setdefault(ev, []).append(cb)

    def send(self, method, params=None):
        self.goi.append((method, params))
        if method in self.loi_khi_gui:
            raise self.loi_khi_gui[method]
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "F1"}}}
        if method == "Page.startScreencast":
            self.dang_chieu = True
        elif method == "Page.stopScreencast":
            self.dang_chieu = False
        return {}

    def detach(self):
        self.goi.append(("detach", None))

    def phat(self, ev, params):
        for cb in self.cb.get(ev, []):
            cb(params)

    def cac_goi(self, ten):
        return [p for m, p in self.goi if m == ten]

    def da_goi(self, ten) -> bool:
        return any(m == ten for m, _ in self.goi)


class TrangGia:
    """`kich_ban`: [(giay_ke_tu_luc_dang_giai, ham)] chạy trong `wait_for_timeout` theo giờ giả."""

    def __init__(self, dong: DongHoGia, url: str, *, phat_khung: bool = True):
        self.dong = dong
        self.url = url
        self.cdp = CdpGia(self)
        self.phat_khung = phat_khung
        self.da_phat_khung = False
        self.kich_ban: list = []
        self.moc: float | None = None
        self.phien_fn = None
        self.so_reload = 0
        self.so_goto = 0
        self.goto_loi: Exception | None = None
        self.wait_loi: Exception | None = None
        self.lich_su: list[str] = []
        self.dong_roi = False
        self.bo_nghe_phan_hoi = None
        # `reload` lần thứ n bắn các phản hồi feed trong phan_hoi_khi_tai[n] (đã gắn bộ nghe mới có hiệu lực)
        self.phan_hoi_khi_tai: list[list] = []
        self.mouse_cua_tool: list[tuple] = []
        self.mouse = self
        self.moi_tick = None  # hàm chạy MỖI lần thời gian trôi (mô phỏng thứ chạy song song ở luồng web)

    # --- API Playwright dùng bởi scraper ---
    def on(self, ev, cb):
        if ev == "response":
            self.bo_nghe_phan_hoi = cb

    def goto(self, url, **_kw):
        self.so_goto += 1
        self.lich_su.append("goto")
        if self.goto_loi is not None:
            raise self.goto_loi
        self.url = url

    def reload(self, **_kw):
        self.so_reload += 1
        self.lich_su.append("reload")
        if self.phan_hoi_khi_tai and self.bo_nghe_phan_hoi is not None:
            for r in self.phan_hoi_khi_tai.pop(0):
                self.bo_nghe_phan_hoi(r)

    def wait_for_selector(self, *_a, **_k):
        return object()

    def eval_on_selector_all(self, *_a, **_k):
        return []

    def evaluate(self, *_a, **_k):
        return {"kind": "window"}

    def move(self, *a):          # page.mouse.move — sự kiện của TOOL
        self.mouse_cua_tool.append(("move", a))

    def wheel(self, *a):         # page.mouse.wheel — sự kiện của TOOL
        self.mouse_cua_tool.append(("wheel", a))

    def is_closed(self):
        return self.dong_roi

    def close(self):
        self.dong_roi = True

    # --- thời gian ---
    def wait_for_timeout(self, ms):
        if self.wait_loi is not None:
            raise self.wait_loi
        self.dong.troi(ms / 1000.0)
        if self.moi_tick is not None:
            self.moi_tick()
        if self.cdp.dang_chieu and self.phat_khung and not self.da_phat_khung:
            self.da_phat_khung = True
            self.cdp.phat("Page.screencastFrame", {"data": "QUJD", "sessionId": 1,
                                                   "metadata": dict(KHUNG_META)})
        phien = self.phien_fn() if self.phien_fn else None
        if phien is not None and phien.trang_thai == "dang_giai":
            if self.moc is None:
                self.moc = self.dong.t
            while self.kich_ban and self.kich_ban[0][0] <= self.dong.t - self.moc:
                _, fn = self.kich_ban.pop(0)
                fn()


class CtxGia:
    def __init__(self, trang: TrangGia, hong_cookies: bool = False):
        self.pages = [trang]
        self.trang = trang
        self.closed = False
        self.cb: dict[str, list] = {}
        self.hong_cookies = hong_cookies

    def add_init_script(self, *_a):
        pass

    def add_cookies(self, *_a):
        if self.hong_cookies:
            raise RuntimeError("cookie hỏng")

    def on(self, ev, cb):
        self.cb.setdefault(ev, []).append(cb)

    def new_page(self):
        return self.trang

    def new_cdp_session(self, _page):
        return self.trang.cdp

    def mo_trang_moi(self, url="https://other.example/x?q=1"):
        p = TrangGia(self.trang.dong, url)
        self.pages.append(p)
        for cb in self.cb.get("page", []):
            cb(p)
        return p

    def close(self):
        self.closed = True


class PwGia:
    def __init__(self, ctx: CtxGia | None = None, hong_mo: bool = False):
        self.chromium = self
        self.ctx = ctx
        self.hong_mo = hong_mo
        self.so_lan_mo = 0
        self.kwargs: list[dict] = []

    def launch_persistent_context(self, **kw):
        self.so_lan_mo += 1
        self.kwargs.append(kw)
        if self.hong_mo:
            raise OSError("không mở được Chromium")
        return self.ctx


class RespFeed:
    """Phản hồi feed của trang profile: `rong=True` ⇒ Content-Length 0 (đếm `rong`), ngược lại có dữ liệu."""

    def __init__(self, rong: bool = True, path: str = "/api/post/item_list/"):
        self.url = "https://www.tiktok.com" + path + "?x=1"
        self.status = 200
        self.request = SimpleNamespace(method="GET")
        self._cl = "0" if rong else "1234"

    def header_value(self, name: str):
        return self._cl if name == "content-length" else None


def dung_pw(monkeypatch, pw: PwGia) -> None:
    @contextmanager
    def sp():
        yield pw

    monkeypatch.setattr(scraper_mod, "sync_playwright", sp)
    monkeypatch.setattr(scraper_mod, "_load_cookies", lambda p: [])
    scraper_mod._PROFILE_DANG_MO.clear()


def dung_dong_ho(monkeypatch) -> DongHoGia:
    dong = DongHoGia()
    monkeypatch.setattr(gc, "dong_ho", dong)
    monkeypatch.setattr(worker, "ngu", dong.troi)
    return dong


class Nguoi:
    """Người dùng popup: gửi lô chuột qua ĐÚNG đường `kiem_su_kien` + `PhienGiai.nhan_lo` mà route dùng.
    Ghi lại MỌI sự kiện người đã tạo (đã đổi đơn vị) để so với thứ tool phát (bất biến ĐP-606)."""

    def __init__(self, phien: gc.PhienGiai, dong: DongHoGia, token: str = TOKEN,
                 email: str = "a@x.vn", khung_w: float = 800.0):
        self.phien, self.dong, self.token, self.email, self.khung_w = phien, dong, token, email, khung_w
        self.seq = 0
        self.da_tao: list[gc.SuKien] = []

    def gui(self, *su_kien: tuple, seq: int | None = None) -> str:
        """su_kien: (k, x, y, buttons[, dx, dy]); `t` = giờ giả hiện tại (ms)."""
        events = []
        for sk in su_kien:
            k, x, y, b, *rest = sk
            raw = {"k": k, "x": x, "y": y, "t": self.dong.t * 1000.0, "buttons": b}
            if k == "wheel":
                raw["dx"], raw["dy"] = (rest + [0, 0])[:2]
            ev = gc.kiem_su_kien(raw, self.khung_w, self.khung_w * 900 / 1280, 1280.0)
            if ev is not None:
                events.append(ev)
        self.da_tao.extend(events)
        # Như popup: gắn KỲ đang biết (kỳ hiện tại ⇔ `trang_thai` mới nhất); kỳ đổi ⇒ đánh số lô lại từ 0.
        ky = self.phien.ky
        if ky != getattr(self, "ky_biet", 0):
            self.ky_biet = ky
            self.seq = 0
        so = self.seq if seq is None else seq
        self.seq = so + 1
        return self.phien.nhan_lo(self.token, self.email, so, events, ky=ky)

    def tham_so_nguoi(self) -> list[dict]:
        return [gc.tham_so_cdp(e) for e in self.da_tao]


def la_day_con(day_con: list, day: list) -> bool:
    """`day_con` là dãy con (giữ thứ tự) của `day`."""
    it = iter(day)
    return all(any(x == y for y in it) for x in day_con)


_dem = itertools.count(1)
