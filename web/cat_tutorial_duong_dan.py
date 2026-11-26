"""Đường dẫn của tool Cắt tutorial (ui_server.py của chị Linh) khi chạy dưới tiền tố `/cat-tutorial/` của Video Desk.

THUẦN stdlib, có chủ đích: `deploy/cap-nhat-cat-tutorial.sh` gọi `python3 -m web.cat_tutorial_duong_dan <index.html>` trên
máy dev để kiểm hợp đồng bản mới TRƯỚC khi rsync — không cần venv có fastapi/httpx. Proxy (`web/cat_tutorial_routes.py`)
dùng CÙNG danh sách + CÙNG hàm viết lại ⇒ không có chỗ thứ hai phải nhớ sửa.

Vì sao phải viết lại: `ui/index.html` gọi đường TUYỆT ĐỐI (`"/api/state"`, `` `/api/edge?…` `` ở index.html:672,
`url("/sprite?…")`) ⇒ đặt dưới đường con thì trình duyệt gọi thẳng gốc Video Desk. Chỉ viết lại các tiền tố ĐÃ BIẾT;
đường lạ giữ nguyên để `kiem_hop_dong` bắt — bản sau của chị Linh thêm route mới thì script cập nhật DỪNG, không hỏng âm
thầm. Khi chị chuyển sang đường dẫn tương đối, `viet_lai_index` thành không-làm-gì và hợp đồng vẫn xanh.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TIEN_TO = "/cat-tutorial"

# Đường web của ui_server bản c96edb3 (do_GET + _post_web). "" và "index.html" = trang gốc.
DUONG_GET = frozenset({"", "index.html", "api/ping", "api/state", "video", "output", "preview", "sprite",
                       "api/zip", "api/edge"})
DUONG_POST = frozenset({"api/upload", "api/clear", "api/remove", "api/wm", "api/reanalyze", "api/segs",
                        "api/review", "api/export"})
# Chỉ có nghĩa ở bản chạy trên máy cá nhân (mở thư mục theo đường dẫn máy chủ / hộp chọn Finder / `open`) ⇒ index.html
# vẫn nhắc tới (nhánh không-web) nhưng proxy KHÔNG BAO GIỜ chuyển tiếp.
DUONG_CAM = frozenset({"api/open", "api/pick", "api/reveal"})

KHOA_THEME_GOC = "studio-theme"
KHOA_THEME_VIDEODL = "videodl-theme"  # cùng khoá với chung-tien-ich.js / thay-logo.js ⇒ iframe theo theme Video Desk

# Nháy kép, nháy đơn, backtick + "/" + tiền tố đã biết của ui_server.
_MAU_BIET = re.compile(r"""(["'`])/(?=(?:api/|video\b|output\b|preview\b|sprite\b|index\.html\b))""")
# Hợp đồng: còn chuỗi bắt đầu bằng nháy + "/" + CHỮ mà chưa có tiền tố ⇒ hỏng. `.split("/")` không bị bắt (sau "/" là nháy).
_MAU_CHUA_TIEN_TO = re.compile(r"""(["'`])/(?!cat-tutorial/)([A-Za-z][^"'`\s]{0,60})""")
_MAU_DA_TIEN_TO = re.compile(r"""["'`]/cat-tutorial/([A-Za-z][A-Za-z0-9_./-]*)""")


def viet_lai_index(html: str) -> str:
    """Gắn `/cat-tutorial` trước mọi đường tuyệt đối đã biết + đổi khoá theme. Gọi lại lần hai không đổi gì thêm."""
    html = _MAU_BIET.sub(lambda m: m.group(1) + TIEN_TO + "/", html)
    return html.replace(KHOA_THEME_GOC, KHOA_THEME_VIDEODL)


def kiem_hop_dong(html_da_viet_lai: str) -> list[str]:
    """Danh sách lỗi (rỗng = đạt) của một index.html ĐÃ qua `viet_lai_index`."""
    loi = [f"đường tuyệt đối chưa có tiền tố {TIEN_TO}: {m.group(1)}/{m.group(2)}"
           for m in _MAU_CHUA_TIEN_TO.finditer(html_da_viet_lai)]
    biet = DUONG_GET | DUONG_POST | DUONG_CAM
    loi += [f"đường lạ, chưa có trong danh sách của ui_server: {TIEN_TO}/{m.group(1)}"
            for m in _MAU_DA_TIEN_TO.finditer(html_da_viet_lai) if m.group(1) not in biet]
    if KHOA_THEME_GOC in html_da_viet_lai:
        loi.append(f"còn khoá theme '{KHOA_THEME_GOC}'")
    return loi


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("cách dùng: python3 -m web.cat_tutorial_duong_dan <đường dẫn ui/index.html>", file=sys.stderr)
        return 2
    goc = Path(argv[0]).read_text(encoding="utf-8")
    da_viet = viet_lai_index(goc)
    loi = kiem_hop_dong(da_viet)
    for dong in loi:
        print(f"LỖI hợp đồng đường dẫn: {dong}", file=sys.stderr)
    if loi:
        return 1
    print(f"hợp đồng đường dẫn ĐẠT: {len(_MAU_DA_TIEN_TO.findall(da_viet))} chỗ gọi đều nằm trong danh sách ui_server")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
