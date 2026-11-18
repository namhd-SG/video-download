"""Cờ `VIDEODL_PATCHRIGHT`: mở trang TikTok bằng patchright + Chrome thật thay vì Playwright + Chromium bundled.

Đo M4 (17/11, máy dev, không cookie, @lynherne, mỗi lượt một profile MỚI):
- Playwright + Chromium bundled + UA giả + STEALTH_INIT_JS (đường prod): 0/4 lượt có feed, đều captcha.
- Playwright + `channel="chrome"`: 0/3 ⇒ chỉ đổi sang Chrome thật KHÔNG đủ.
- patchright + `channel="chrome"`, không UA giả/init script: 6/6 có feed (17–48 link, 0 captcha), kể cả
  với viewport cố định 1280×900 (worker captcha cần viewport cố định để đổi toạ độ chuột).
- patchright dùng LẠI profile vừa chạy: 0/2 ⇒ giữ profile mới theo job như hiện tại, không làm profile bền.
Số đo ở IP nhà, n nhỏ ⇒ giả thuyết mạnh, chưa đo trên ca-n ⇒ cờ MẶC ĐỊNH TẮT.

Khi bật: KHÔNG ghi đè user agent và KHÔNG chèn STEALTH_INIT_JS — patchright tự vá dấu vết tự động hoá ở
tầng driver, còn UA giả lệch với Chrome thật là một tín hiệu bất thường. Chỉ đọc cờ LÚC CHẠY.
patchright (Apache-2.0) import lười: thiếu gói thì log cảnh báo và quay về Playwright, không làm vỡ job.
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("ttmd")

ENV_PATCHRIGHT = "VIDEODL_PATCHRIGHT"
_GIA_TRI_BAT = ("1", "true", "yes", "on")

# Mã cấu hình cho log khởi động và /healthz (`kiem_cau_hinh`).
MA_TAT = "tat"                    # cờ tắt ⇒ đường Playwright như trước
MA_OK = "ok"                      # cờ bật, có gói, có Chrome
MA_THIEU_GOI = "thieu_goi"        # cờ bật, thiếu gói ⇒ lặng lẽ lùi về Playwright (headless = chromium-headless-shell)
MA_THIEU_CHROME = "thieu_chrome"  # cờ bật, có gói, thiếu Chrome thật ⇒ `channel="chrome"` vỡ lúc launch
MA_LOI = (MA_THIEU_GOI, MA_THIEU_CHROME)

# Chỗ Chrome ổn định mà `channel="chrome"` của Playwright/patchright tìm. Nền tảng khác: không kiểm (None).
_DUONG_CHROME = {
    "darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "linux": "/opt/google/chrome/chrome",
}

# Tên đường mở trình duyệt cho dòng log `[trinh-duyet]` (đo M5c v2 18/11: headless-shell dính "Something went wrong").
DUONG_PATCHRIGHT = "patchright+chrome"
DUONG_PW_CHROMIUM = "pw-chromium"
DUONG_PW_HEADLESS_SHELL = "pw-headless-shell"


def _co_bat() -> bool:
    return os.environ.get(ENV_PATCHRIGHT, "").strip().lower() in _GIA_TRI_BAT


def _co_goi() -> bool:
    try:
        import patchright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def patchright_dang_bat() -> bool:
    """Cờ bật VÀ gói patchright import được."""
    if not _co_bat():
        return False
    if not _co_goi():
        log.warning("%s bật nhưng thiếu gói patchright — dùng Playwright", ENV_PATCHRIGHT)
        return False
    return True


def kiem_cau_hinh() -> str:
    """Mã cấu hình (MA_*), KHÔNG ghi log — /healthz gọi mỗi lượt thăm dò. Cờ tắt ⇒ MA_TAT, không kiểm gì thêm."""
    if not _co_bat():
        return MA_TAT
    if not _co_goi():
        return MA_THIEU_GOI
    duong = _DUONG_CHROME.get(sys.platform)
    if duong is not None and not os.path.exists(duong):
        return MA_THIEU_CHROME
    return MA_OK


def ten_duong(dung_patchright: bool, headless: bool) -> str:
    """Đường thật sẽ mở. Không patchright + headless + không channel ⇒ Playwright chọn `chromium-headless-shell`."""
    if dung_patchright:
        return DUONG_PATCHRIGHT
    return DUONG_PW_HEADLESS_SHELL if headless else DUONG_PW_CHROMIUM


def sync_playwright_patchright():
    """`sync_playwright()` của patchright (cùng API với Playwright)."""
    from patchright.sync_api import sync_playwright
    return sync_playwright()


def kwargs_context_patchright(common_kwargs: dict) -> dict:
    """Bộ kwargs mở context khi bật cờ: Chrome thật, giữ viewport/locale, BỎ user_agent."""
    kw = {k: v for k, v in common_kwargs.items() if k != "user_agent"}
    kw["channel"] = "chrome"
    return kw
