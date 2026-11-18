"""R-03: `app.js` tách thành `app-*.js` + `app.js`, `chia-cum.js` tách phần vẽ ra `chia-cum-ve.js`, helper lặp gom
về `chung-tien-ich.js` (`window.VDChung`).

Hai lớp bảo vệ:
- Tĩnh: trang nào dùng `VDChung`/`ChiaCumVe` phải nạp tệp định nghĩa TRƯỚC; không ai định nghĩa lại `escapeHtml`
  (trừ bản `esc` của `giai-captcha-popup.js` — vùng lane A, chưa chuyển).
- Trang thật: index/settings mở không lỗi JS, INIT (tệp cuối) đã chạy, màn chia cụm đăng ký được.
  Đột biến ĐỎ: xoá `<script src="chung-tien-ich.js">` khỏi index.html ⇒ `app-hang-so.js` ném TypeError ngay dòng
  destructure `window.VDChung` ⇒ `test_index_chay_het_cac_tep_khong_loi_js` đỏ (pageerror + thanh lọc rỗng).
"""
from __future__ import annotations

import re

import pytest

from nguon_app_js import STATIC, cac_tep_app
from test_trang_huong_dan import may_chu, trinh_duyet  # noqa: F401 — fixture dùng lại
from trinh_duyet_khong_mang import dem_mang_ngoai, mo_trang

_THE_SCRIPT = re.compile(r'<script src="/?([A-Za-z0-9_.-]+\.js)"></script>')


def _thu_tu_script(trang: str) -> list[str]:
    return _THE_SCRIPT.findall((STATIC / trang).read_text(encoding="utf-8"))


@pytest.mark.parametrize("trang", ["index.html", "settings.html", "thay-logo.html", "huong-dan.html"])
def test_tep_dung_vdchung_nap_sau_chung_tien_ich(trang):
    """Mọi tệp JS trỏ tới `window.VDChung` / `window.ChiaCumVe` phải đứng SAU tệp định nghĩa nó trong cùng trang."""
    ds = _thu_tu_script(trang)
    for i, ten in enumerate(ds):
        nguon = (STATIC / ten).read_text(encoding="utf-8")
        if "window.VDChung" in nguon and ten != "chung-tien-ich.js":
            assert "chung-tien-ich.js" in ds[:i], f"{trang}: {ten} dùng VDChung nhưng nạp trước chung-tien-ich.js"
        if "window.ChiaCumVe" in nguon and ten != "chia-cum-ve.js":
            assert "chia-cum-ve.js" in ds[:i], f"{trang}: {ten} dùng ChiaCumVe nhưng nạp trước chia-cum-ve.js"


def test_index_nap_app_lien_mach_va_init_cuoi():
    """Các tệp app-*.js nằm liền nhau, `app.js` (INIT) cuối; mọi tệp app-*.js trong thư mục đều được nạp."""
    ds = _thu_tu_script("index.html")
    app = [p.name for p in cac_tep_app()]
    i = ds.index(app[0])
    assert ds[i:i + len(app)] == app
    assert sorted(app) == sorted(p.name for p in STATIC.glob("app*.js"))


def test_escape_html_chi_dinh_nghia_o_tep_chung():
    """Gom helper: thân hàm escape (bảng `&amp;`…`&#39;`) chỉ còn ở `chung-tien-ich.js`, cộng bản `esc` của
    `giai-captcha-popup.js` (vùng lane A, chưa chuyển). Tệp khác viết lại thân đó ⇒ đỏ."""
    co = sorted(p.name for p in STATIC.glob("*.js")
                if '"&#39;"' in p.read_text(encoding="utf-8") and "&quot;" in p.read_text(encoding="utf-8"))
    assert co == ["chung-tien-ich.js", "giai-captcha-popup.js"]


def _mo(trinh_duyet, url):
    ctx = trinh_duyet.new_context()
    chan = dem_mang_ngoai(ctx)
    p = ctx.new_page()
    loi_js: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    mo_trang(p, url, chan)
    p.wait_for_load_state("load")
    return p, loi_js


def test_index_chay_het_cac_tep_khong_loi_js(may_chu, trinh_duyet):  # noqa: F811
    p, loi_js = _mo(trinh_duyet, f"{may_chu}/")
    assert loi_js == []
    # INIT (`app.js`, tệp cuối) đã chạy: thanh lọc được vẽ, giải captcha được nối, màn chia cụm đăng ký.
    assert p.evaluate("document.querySelectorAll('#filter-bar [data-group]').length") > 0
    assert p.evaluate("typeof window.chiaCum.open") == "function"
    assert p.evaluate("Object.keys(window.VDChung).sort().join(',')") == \
        "PhienHetHan,THEME_KEY,apiSend,applyTheme,baoPhienHetHan,escapeHtml"


def test_settings_chay_khong_loi_js(may_chu, trinh_duyet):  # noqa: F811
    p, loi_js = _mo(trinh_duyet, f"{may_chu}/settings.html")
    assert loi_js == []
    assert p.evaluate("typeof window.VDChung.escapeHtml") == "function"
