"""Đo (i′): HTML trang TikTok có nhúng danh tính NGƯỜI XEM không, và ở trường nào.

Chạy TRÊN MINI, bằng venv của repo, với jar của user tại chỗ (jar không rời mini):
    ./.venv/bin/python do-truong-nguoi-xem.py <đường jar> <URL trang TikTok>
Thử cục bộ, không chạm TikTok (trang giả):
    ./.venv/bin/python do-truong-nguoi-xem.py --gia <tệp jar giả> <file:///…html>

Hai lượt `goto` cùng một URL: CÓ cookie và ẨN DANH (control). In RA CHỈ:
- danh sách khoá dưới `__DEFAULT_SCOPE__` của mỗi lượt;
- mọi ĐƯỜNG KHOÁ dẫn tới trường tên-người-dùng (`uniqueId`, `nickname`, `uid`…),
  chỉ in đường, không in giá trị;
- đường nào CHỈ có ở lượt có cookie ⇒ ứng viên trường người xem.
Không một giá trị nào của trang hay của jar được in ra.

Đi CÙNG ĐƯỜNG với job thật: `_open_context` + `_load_cookies` của scraper, cùng
`wait_until="domcontentloaded"` như `scraper.py:436`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from playwright.sync_api import sync_playwright  # noqa: E402

from tiktok_music_downloader.scraper import (  # noqa: E402
    _load_cookies, _open_context)
from tiktok_music_downloader.utils import random_user_agent  # noqa: E402

# Tên trường thường mang danh tính người dùng. So KHÔNG phân biệt hoa thường.
TEN_DANH_TINH = {"uniqueid", "nickname", "uid", "userid", "secuid", "user_id", "username"}

LAY_KHOI = """() => {
  const el = document.getElementById("__UNIVERSAL_DATA_FOR_REHYDRATION__");
  return el ? el.textContent : null;
}"""


def duong_danh_tinh(obj, duong="", ra=None) -> set[str]:
    """Mọi đường khoá tới một trường danh tính CÓ GIÁ TRỊ KHÁC RỖNG. Chỉ đường."""
    ra = set() if ra is None else ra
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{duong}.{k}" if duong else str(k)
            if str(k).lower() in TEN_DANH_TINH and v not in (None, "", 0, "0"):
                ra.add(p)
            duong_danh_tinh(v, p, ra)
    elif isinstance(obj, list):
        for v in obj[:3]:  # gộp chỉ số: "[]" — đủ để biết hình dạng, không nổ số đường
            duong_danh_tinh(v, f"{duong}[]", ra)
    return ra


def mot_luot(pw, url: str, jar: Path | None) -> dict:
    browser, ctx = _open_context(pw, headless=True, proxy=None, profile_dir=None,
                                 user_agent=random_user_agent())
    try:
        if jar is not None:
            ctx.add_cookies(_load_cookies(jar))
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        tho = page.evaluate(LAY_KHOI)
        if tho is None:
            return {"co_khoi": False}
        scope = (json.loads(tho) or {}).get("__DEFAULT_SCOPE__") or {}
        return {"co_khoi": True, "khoa_scope": sorted(scope),
                "duong_danh_tinh": sorted(duong_danh_tinh(scope))}
    finally:
        ctx.close()
        if browser is not None:
            browser.close()


def main() -> None:
    args = sys.argv[1:]
    gia = args[:1] == ["--gia"]
    if gia:
        args = args[1:]
    if len(args) != 2:
        sys.exit("dùng: do-truong-nguoi-xem.py [--gia] <jar> <url>")
    jar, url = Path(args[0]), args[1]
    if not gia and not url.startswith("https://www.tiktok.com/"):
        sys.exit("chỉ đo trang https://www.tiktok.com/… (thêm --gia để thử trang giả)")
    with sync_playwright() as pw:
        co = mot_luot(pw, url, jar)
        an = mot_luot(pw, url, None)
    print("co_cookie :", json.dumps(co, ensure_ascii=False))
    print("an_danh   :", json.dumps(an, ensure_ascii=False))
    if co.get("co_khoi") and an.get("co_khoi"):
        chi_co = sorted(set(co["duong_danh_tinh"]) - set(an["duong_danh_tinh"]))
        print("CHI_O_LUOT_CO_COOKIE:", json.dumps(chi_co, ensure_ascii=False))
    else:
        print("CHUA KET LUAN: một lượt không có khối __UNIVERSAL_DATA_FOR_REHYDRATION__")


if __name__ == "__main__":
    main()
