"""Phiên trình duyệt thật cho Facebook page: patchright + Chrome thật, KHÔNG cookie (Đường A).

Cài đặt `TrangFB` (xem `fb_quet_cuon.py`): mở URL, cuộn, bắt XHR `/api/graphql` thuộc whitelist
(`fb_xhr_phan_tich.ten_xhr_dich`), đọc thẻ `<script type="application/json">`, đọc/bấm hộp thoại đăng nhập. Khuôn của
`ig_trinh_duyet.PhienIG`; dùng chung `khoi_dong_patchright`.

`cookies_path=None` ⇒ ẩn danh (Đường A, mặc định và là cách duy nhất `nguon_facebook_trang` gọi); có đường dẫn ⇒ nạp cookie
vào profile (chỗ dành cho Đường B có cookie tài khoản phụ — chưa nối). Profile là thư mục TẠM (mkdtemp 0700), xoá ở mọi lối ra.

KHÔNG có test nào mở facebook.com thật: test tiêm đối tượng giả vào `PhienFB(khoi_dong=…)` và vào `_ghi_phan_hoi`.
Phần chưa smoke thật: bộ chọn DOM `_CHON_HOP_THOAI` / `_CHON_NUT_DONG` (lane smoke trực tiếp kiểm).

Headless mặc định (đo bước 0: 12/12 lượt headless ra số mã như mong đợi); `VIDEODL_FB_HEADFUL=1` bật headful.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from tiktok_music_downloader import fb_xhr_phan_tich as ph
from tiktok_music_downloader.fb_quet_cuon import DauDomFB
from tiktok_music_downloader.ig_trinh_duyet import khoi_dong_patchright
from tiktok_music_downloader.scraper import _load_cookies

log = logging.getLogger("ttmd")

ENV_FB_HEADFUL = "VIDEODL_FB_HEADFUL"
_CUON_PIXEL = 2200              # đo bước 0: wheel 1800–2600 px
_TIMEOUT_DIEU_HUONG_MS = 60_000
_TIMEOUT_BAM_MS = 3_000
# Hộp thoại đăng nhập = dialog có ô mật khẩu. Nút đóng: aria-label "Close" / "Đóng" bên trong CHÍNH hộp thoại đó.
_CHON_HOP_THOAI = "div[role=dialog]:has(input[name=pass])"
_CHON_NUT_DONG = f"{_CHON_HOP_THOAI} :is([aria-label='Close'], [aria-label='Đóng'])"


def headless_dang_bat() -> bool:
    """Mặc định headless; `VIDEODL_FB_HEADFUL=1` ⇒ headful."""
    return os.environ.get(ENV_FB_HEADFUL, "").strip().lower() not in ("1", "true", "yes", "on")


class PhienFB:
    """Context manager: `with PhienFB(None) as trang: …`. Đóng context + xoá profile tạm ở mọi lối ra."""

    def __init__(self, cookies_path: str | None = None, *, headless: bool | None = None, proxy: str | None = None,
                 khoi_dong: Callable[..., tuple] = khoi_dong_patchright):
        self._cookies_path = cookies_path
        self._headless = headless_dang_bat() if headless is None else headless
        self._proxy = proxy
        self._khoi_dong = khoi_dong
        self._pw = self._ctx = self._page = None
        self._thu_muc: str | None = None
        self._xhr: list[ph.XhrFB] = []

    def __enter__(self) -> "PhienFB":
        self._thu_muc = tempfile.mkdtemp(prefix="fbprof-")          # mkdtemp tạo 0700
        try:
            # Lỗi đọc cookie nổ TRƯỚC khi mở Chrome. Không cookie ⇒ ẩn danh, không đọc tệp nào.
            cookies = _load_cookies(Path(self._cookies_path)) if self._cookies_path else None
            self._pw, self._ctx = self._khoi_dong(self._thu_muc, headless=self._headless, proxy=self._proxy)
            if cookies is not None:
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
                log.warning("đóng phiên FB lỗi (%s)", type(exc).__name__)
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
            try:
                ten_header = (req.headers or {}).get("x-fb-friendly-name")
            except Exception:  # noqa: BLE001
                ten_header = None
            if ph.ten_xhr_dich(r.url, post, ten_header) is None:
                return
            try:
                body = r.body()
            except Exception:  # noqa: BLE001 — trang đóng giữa chừng / 429 không có thân
                body = b""
            self._xhr.append(ph.XhrFB(status=int(r.status), body=body.decode("utf-8", "replace")))
        except Exception as exc:  # noqa: BLE001
            log.warning("không đọc được một phản hồi FB (%s)", type(exc).__name__)

    # ---- TrangFB
    def mo(self, url: str) -> int | None:
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT_DIEU_HUONG_MS)
        return resp.status if resp else None

    def cuon(self) -> None:
        self._page.mouse.wheel(0, _CUON_PIXEL)

    def lay_xhr(self) -> list[ph.XhrFB]:
        ra, self._xhr = self._xhr, []
        return ra

    def lay_script_json(self) -> list[str]:
        try:
            ra = self._page.eval_on_selector_all(
                "script[type='application/json']", "els => els.map(e => e.textContent || '')")
            return [t for t in ra if isinstance(t, str)]
        except Exception as exc:  # noqa: BLE001 — trang đang chuyển hướng: không đọc được ≠ trang rỗng
            log.warning("không đọc được script JSON FB (%s)", type(exc).__name__)
            return []

    def dau_dom(self) -> DauDomFB:
        p = self._page
        try:
            if p.locator(_CHON_HOP_THOAI).count() == 0:
                return DauDomFB()
            return DauDomFB(co_hop_thoai_dang_nhap=True, co_nut_dong=p.locator(_CHON_NUT_DONG).count() > 0)
        except Exception as exc:  # noqa: BLE001 — trang đang chuyển hướng: không đo được ≠ có tường
            log.warning("không đọc được DOM FB (%s)", type(exc).__name__)
            return DauDomFB()

    def bam_dong(self) -> bool:
        try:
            self._page.locator(_CHON_NUT_DONG).first.click(timeout=_TIMEOUT_BAM_MS)
            return True
        except Exception as exc:  # noqa: BLE001 — nút biến mất / bị che: lượt sau đọc lại DOM
            log.warning("không bấm được nút đóng hộp thoại FB (%s)", type(exc).__name__)
            return False
