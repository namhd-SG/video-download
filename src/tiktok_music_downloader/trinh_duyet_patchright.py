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

log = logging.getLogger("ttmd")

ENV_PATCHRIGHT = "VIDEODL_PATCHRIGHT"
_GIA_TRI_BAT = ("1", "true", "yes", "on")


def patchright_dang_bat() -> bool:
    """Cờ bật VÀ gói patchright import được."""
    if os.environ.get(ENV_PATCHRIGHT, "").strip().lower() not in _GIA_TRI_BAT:
        return False
    try:
        import patchright.sync_api  # noqa: F401
    except ImportError:
        log.warning("%s bật nhưng thiếu gói patchright — dùng Playwright", ENV_PATCHRIGHT)
        return False
    return True


def sync_playwright_patchright():
    """`sync_playwright()` của patchright (cùng API với Playwright)."""
    from patchright.sync_api import sync_playwright
    return sync_playwright()


def kwargs_context_patchright(common_kwargs: dict) -> dict:
    """Bộ kwargs mở context khi bật cờ: Chrome thật, giữ viewport/locale, BỎ user_agent."""
    kw = {k: v for k, v in common_kwargs.items() if k != "user_agent"}
    kw["channel"] = "chrome"
    return kw
