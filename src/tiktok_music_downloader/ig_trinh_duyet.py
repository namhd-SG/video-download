"""Phiên trình duyệt thật cho Instagram: patchright + Chrome thật + cookie IG của người tạo job.

Cài đặt `TrangIG` (xem `ig_quet_cuon.py`): mở URL, cuộn, bắt XHR đích (`ig_xhr_phan_tich.la_xhr_dich`), đọc dấu DOM.
KHÔNG có test nào mở instagram.com thật (không có cookie test trong máy): test tiêm đối tượng giả vào
`PhienIG(khoi_dong=…)` và vào `_ghi_phan_hoi`. Phần chưa smoke thật: bộ chọn DOM `_CHON_NUT_DANG_NHAP`.

Chọn headless (mặc định) vì: bước 0 đo ở 3/4 loại trang headless ra cùng số XHR/mã như headful; riêng profile headless ra
ÍT XHR hơn cùng số lần cuộn (10 vs 16) — nhưng vòng cuộn dừng theo "đủ N mới / hết trang", không theo số lần cuộn cố
định, nên chỉ cuộn nhiều hơn. Máy chạy dịch vụ cũng không cần cửa sổ. `VIDEODL_IG_HEADFUL=1` bật lại headful nếu smoke
thật thấy headless bị IG chặn.

Cookie nằm trong profile Chrome TẠM (thư mục mkdtemp 0700) và bị xoá ngay khi đóng phiên. Không in/log giá trị cookie.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from tiktok_music_downloader import ig_xhr_phan_tich as ph
from tiktok_music_downloader.scraper import _load_cookies
from tiktok_music_downloader.trinh_duyet_patchright import sync_playwright_patchright

log = logging.getLogger("ttmd")

ENV_IG_HEADFUL = "VIDEODL_IG_HEADFUL"
_VIEWPORT = {"width": 1280, "height": 900}
_CUON_PIXEL = 2500
_TIMEOUT_DIEU_HUONG_MS = 60_000
# Nút "Log in"/"Đăng nhập" đúng chữ, chỉ trên thẻ có thể bấm: bài đăng/caption có chữ "log in" không khớp.
_CHON_NUT_DANG_NHAP = ", ".join(f'{t}:text-is("{c}")' for t in ("a", "button", "[role=button]")
                               for c in ("Log in", "Đăng nhập"))
# Liên kết tới trang đăng nhập: smoke 18/11 trang audio thiếu `sessionid` ⇒ 1 liên kết, đủ phiên ⇒ 0; khi đó nút
# chữ "Log in" KHÔNG khớp bộ chọn trên (chữ nằm trong thẻ con) — trang audio vẫn trả dữ liệu ẩn danh nên đây
# là dấu duy nhất bắt được mất phiên ở audio.
_CHON_LIEN_KET_DANG_NHAP = "a[href*='/accounts/login']"


def headless_dang_bat() -> bool:
    """Mặc định headless; `VIDEODL_IG_HEADFUL=1` ⇒ headful."""
    return os.environ.get(ENV_IG_HEADFUL, "").strip().lower() not in ("1", "true", "yes", "on")


def khoi_dong_patchright(thu_muc_profile: str, *, headless: bool, proxy: str | None):
    """`(playwright, context)` thật. Tách ra để test tiêm bản giả; thiếu gói patchright ⇒ lỗi rõ (đường IG không
    chạy được bằng Playwright thường: bước 0 chỉ đo patchright)."""
    try:
        pw = sync_playwright_patchright().start()
    except ImportError as exc:
        raise RuntimeError("thiếu gói patchright — cần cho nguồn Instagram hàng loạt") from exc
    try:
        kw = {"channel": "chrome", "headless": headless, "viewport": _VIEWPORT}
        if proxy:
            kw["proxy"] = {"server": proxy}
        return pw, pw.chromium.launch_persistent_context(thu_muc_profile, **kw)
    except BaseException:
        pw.stop()
        raise


class PhienIG:
    """Context manager: `with PhienIG(jar) as trang: …`. Đóng context + xoá profile tạm ở mọi lối ra."""

    def __init__(self, cookies_path: str, *, headless: bool | None = None, proxy: str | None = None,
                 khoi_dong: Callable[..., tuple] = khoi_dong_patchright):
        self._cookies_path = cookies_path
        self._headless = headless_dang_bat() if headless is None else headless
        self._proxy = proxy
        self._khoi_dong = khoi_dong
        self._pw = self._ctx = self._page = None
        self._thu_muc: str | None = None
        self._xhr: list[ph.XhrDich] = []

    def __enter__(self) -> "PhienIG":
        self._thu_muc = tempfile.mkdtemp(prefix="igprof-")          # mkdtemp tạo 0700
        try:
            cookies = _load_cookies(Path(self._cookies_path))       # lỗi đọc nổ TRƯỚC khi mở Chrome
            self._pw, self._ctx = self._khoi_dong(self._thu_muc, headless=self._headless, proxy=self._proxy)
            self._ctx.add_cookies(cookies)
            self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
            self._page.on("response", self._ghi_phan_hoi)
        except BaseException:
            self._dong()
            raise
        return self

    def __exit__(self, *_exc) -> None:
        self._dong()

    def _dong(self) -> None:
        for dong in (lambda: self._ctx and self._ctx.close(), lambda: self._pw and self._pw.stop()):
            try:
                dong()
            except Exception as exc:  # noqa: BLE001 — đóng lỗi không được đè lỗi gốc; chỉ tên lớp vào log
                log.warning("đóng phiên IG lỗi (%s)", type(exc).__name__)
        self._ctx = self._pw = self._page = None
        if self._thu_muc:
            shutil.rmtree(self._thu_muc, ignore_errors=True)
            self._thu_muc = None

    def _ghi_phan_hoi(self, r) -> None:
        """Bắt phản hồi đích. Không ném (chạy trong luồng sự kiện của trình duyệt)."""
        try:
            req = r.request
            try:
                post = req.post_data or ""
            except Exception:  # noqa: BLE001 — thân nhị phân
                post = ""
            if ph.la_xhr_dich(r.url, post) is None:
                return
            try:
                body = r.body()
            except Exception:  # noqa: BLE001 — trang đóng giữa chừng / 429 không có thân
                body = b""
            self._xhr.append(ph.XhrDich(status=int(r.status), size=len(body),
                                        body=body.decode("utf-8", "replace")))
        except Exception as exc:  # noqa: BLE001
            log.warning("không đọc được một phản hồi IG (%s)", type(exc).__name__)

    # ---- TrangIG
    def mo(self, url: str) -> int | None:
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT_DIEU_HUONG_MS)
        return resp.status if resp else None

    def cuon(self) -> None:
        self._page.mouse.wheel(0, _CUON_PIXEL)

    def url_cuoi(self) -> str:
        return self._page.url

    def lay_xhr(self) -> list[ph.XhrDich]:
        ra, self._xhr = self._xhr, []
        return ra

    def dau_dom(self) -> ph.DauDom:
        p = self._page
        try:
            tieu_de = (p.title() or "").lower()
            chu = p.inner_text("body")[:20000]
            return ph.DauDom(
                co_o_ten_dang_nhap=p.locator("input[name=username]").count() > 0,
                co_nut_dang_nhap=(p.locator(_CHON_NUT_DANG_NHAP).count() > 0
                                  or p.locator(_CHON_LIEN_KET_DANG_NHAP).count() > 0),
                tieu_de_loi="page couldn't load" in tieu_de or "page couldn’t load" in tieu_de,
                chu_loi="Something went wrong" in chu,
            )
        except Exception as exc:  # noqa: BLE001 — trang đang chuyển hướng: không đo được ≠ mất phiên
            log.warning("không đọc được DOM IG (%s)", type(exc).__name__)
            return ph.DauDom()
