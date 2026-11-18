"""Nguồn JS của trang chính sau khi tách `app.js` (R-03).

`web/static/app.js` từng là MỘT IIFE ~2500 dòng; giờ là các tệp `app-*.js` + `app.js` (INIT) nạp tuần tự
trong `index.html`, chia sẻ phạm vi toàn cục. Test trích hàm/hằng THẬT bằng chuỗi (`indexOf`, regex) nên
đọc bản GỘP theo đúng thứ tự thẻ <script> — một hàm chuyển tệp không làm test mù.
"""
from __future__ import annotations

import re
import tempfile
from functools import lru_cache
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"
_MAU_THE_APP = re.compile(r'<script src="(app(?:-[a-z0-9-]+)?\.js)"></script>')


def cac_tep_app() -> list[Path]:
    """Các tệp `app-*.js` + `app.js` theo ĐÚNG thứ tự thẻ <script> trong index.html (`app.js` cuối)."""
    ten = _MAU_THE_APP.findall((STATIC / "index.html").read_text(encoding="utf-8"))
    assert ten and ten[-1] == "app.js", f"index.html phải nạp app-*.js rồi app.js cuối cùng: {ten}"
    return [STATIC / t for t in ten]


def nguon_app() -> str:
    """Nguồn gộp của chương trình trang chính (thay cho đọc `app.js` cũ)."""
    return "\n".join(p.read_text(encoding="utf-8") for p in cac_tep_app())


@lru_cache(maxsize=1)
def tep_app_gop() -> Path:
    """Đường tới MỘT tệp chứa `nguon_app()` — cho harness node nhận một đường dẫn (`process.argv`)."""
    p = Path(tempfile.mkdtemp(prefix="app-js-gop-")) / "app-gop.js"
    p.write_text(nguon_app(), encoding="utf-8")
    return p
