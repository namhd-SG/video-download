"""Gắn `?v=<băm nội dung>` vào mọi `.css`/`.js` NỘI BỘ mà một trang HTML trỏ tới, lúc phục vụ trang.

Vì sao: `Cache-Control: no-cache` ở origin (`add_revalidate_header`) KHÔNG đủ. Đo 09/10 sau deploy #72: trình duyệt
member tải lại `thay-logo.html` (200) và file JS MỚI chưa từng có (200), nhưng KHÔNG một request nào cho
`thay-logo.css` / `thay-logo-khoi-nhap.js` tới origin — bản cũ nằm ở một tầng cache phía trước (edge Cloudflare hoặc
trình duyệt, lưu từ trước khi origin gửi no-cache). HTML mới + CSS cũ ⇒ tab "Dán link Drive" mất toàn bộ kiểu.
Đổi URL theo NỘI DUNG thì tầng cache nào cũng phải lấy bản mới, không phụ thuộc ai purge được Cloudflare.

Làm ở tầng `StaticFiles` (không thêm route): trang tĩnh giữ nguyên tư thế xác thực như trước (Access ở edge, không
`require_user`), và bất biến "mọi APIRoute đòi người dùng" trong tests/test_web_app.py không phải nới.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from starlette.responses import HTMLResponse
from starlette.staticfiles import StaticFiles

# Danh sách CỐ ĐỊNH các trang được viết lại; tên khác đi đường tĩnh thường.
TRANG_GAN_PHIEN_BAN = ("index.html", "thay-logo.html", "settings.html", "huong-dan.html")
DO_DAI_BAM = 10

# href/src trỏ tới .css/.js nội bộ: tương đối (`a.css`) hoặc từ gốc (`/a.css`); KHÔNG nhận scheme (`https:`),
# `//cdn…`, hay URL đã có `?`/`#`.
_MAU_TAI_NGUYEN = re.compile(r'\b(href|src)="(/?[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:css|js))"')


def bam_tep(duong_dan: Path) -> str | None:
    """sha256 rút gọn của nội dung file; không đọc được ⇒ None."""
    try:
        return hashlib.sha256(duong_dan.read_bytes()).hexdigest()[:DO_DAI_BAM]
    except OSError:
        return None


def gan_phien_ban(html: str, thu_muc_tinh: Path) -> str:
    """Trả HTML với `?v=<băm>` gắn sau mỗi `.css`/`.js` nội bộ có thật trong `thu_muc_tinh`; còn lại giữ nguyên chữ."""
    goc = Path(thu_muc_tinh).resolve()

    def thay(m: re.Match) -> str:
        thuoc_tinh, url = m.group(1), m.group(2)
        tep = (goc / url.lstrip("/")).resolve()
        if goc not in tep.parents:  # "../" ra ngoài thư mục tĩnh ⇒ không đụng
            return m.group(0)
        bam = bam_tep(tep)
        return m.group(0) if bam is None else f'{thuoc_tinh}="{url}?v={bam}"'

    return _MAU_TAI_NGUYEN.sub(thay, html)


class StaticCoPhienBan(StaticFiles):
    """`StaticFiles` mà các trang trong `TRANG_GAN_PHIEN_BAN` được phục vụ qua `gan_phien_ban`.

    Trang luôn trả 200 nội dung MỚI viết lại, KHÔNG qua nhánh 304 của `StaticFiles`: trình duyệt còn giữ HTML cũ
    (không `?v`) gửi `If-None-Match` khớp ETag của file trên đĩa ⇒ 304 ⇒ nó tiếp tục dùng HTML cũ trỏ tới CSS cũ —
    đúng lỗi cần chữa.
    """

    async def get_response(self, path: str, scope) -> object:
        ten = "index.html" if path in ("", ".") else path
        if ten in TRANG_GAN_PHIEN_BAN:
            tep = Path(self.directory) / ten
            if tep.is_file():
                return HTMLResponse(gan_phien_ban(tep.read_text(encoding="utf-8"), Path(self.directory)))
        return await super().get_response(path, scope)
