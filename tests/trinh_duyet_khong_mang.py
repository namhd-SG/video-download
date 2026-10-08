"""Test trình duyệt không được chạm mạng ra Internet.

`index.html` tải stylesheet Google Fonts. `page.goto` mặc định chờ sự kiện `load`, mà `load` chờ CSS: request font chậm
hay treo (mạng văn phòng chập chờn, máy nặng) là `goto` treo theo tới hết 30 s ⇒ test ERROR ở setup dù hành vi trang
đúng. Đo 08/10: mạng thật `load` 0,30 s, font bị chặn 0,02 s; 1/4 lượt suite đầy đủ dưới tải nặng ERROR 4 test `cum_*`
đúng lỗi `Page.goto: Timeout 30000ms`.

Chặn ở TẦNG DNS của Chromium (`ARGS_CHAN_MANG` truyền vào `chromium.launch`): host ngoài 127.0.0.1 không phân giải được
⇒ request hỏng NGAY, không chờ ai. KHÔNG dùng `route("**/*")` phía Python: nó bắt MỌI request (cả 127.0.0.1) và bắt
chúng chờ vòng lặp Playwright, mà vòng đó đứng yên khi test chờ bằng `time.sleep` ⇒ chính bộ chặn gây treo (cùng lý do
`test_giai_captcha_popup_browser.py` đã dùng cờ này từ trước). `route` riêng của từng test (giả API, giả Creative Desk)
vẫn chạy: chặn request xảy ra TRƯỚC khi phân giải tên.

Soát 08/10 `web/static/*`: chỉ có hai host ngoài — `fonts.googleapis.com` (`index.html`, giao diện không cần font để
chạy) và `automation.nobidigital.asia` (`app.js`, link mở tab Creative Desk, không phải tài nguyên trang cần); 0 script
ngoài. `dem_mang_ngoai` đếm request ra ngoài đã hỏng theo host (chỉ NGHE sự kiện, không chặn) và in ra: pytest chỉ hiện
stdout của test hỏng, nên lần sau test đỏ là biết nó đã chạm mạng gì.
"""
from __future__ import annotations

from collections import Counter
from urllib.parse import urlsplit

ARGS_CHAN_MANG = ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost"]
_HOST_NOI_BO = frozenset({"127.0.0.1", "localhost"})


class MangChan:
    """Số request ra ngoài đã hỏng (bị chặn), theo host."""

    def __init__(self) -> None:
        self.dem: Counter[str] = Counter()

    def __str__(self) -> str:
        return ", ".join(f"{h}×{n}" for h, n in sorted(self.dem.items())) or "không có"


def dem_mang_ngoai(dich) -> MangChan:
    """`dich`: `BrowserContext` hoặc `Page`. Chỉ nghe `requestfailed`, không đụng tới request."""
    chan = MangChan()

    def ghi(request) -> None:
        host = urlsplit(request.url).hostname or ""
        if host and host not in _HOST_NOI_BO:
            chan.dem[host] += 1
            print(f"[mạng ngoài bị chặn] {host}")

    dich.on("requestfailed", ghi)
    return chan


def mo_trang(page, url: str, chan: MangChan, **kw) -> None:
    """`page.goto` kèm số request ra ngoài bị chặn vào lỗi nếu mở trang hỏng."""
    try:
        page.goto(url, **kw)
    except Exception as exc:
        exc.add_note(f"request ra ngoài bị chặn: {chan}")
        raise
