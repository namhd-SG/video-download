"""Dựng mock "Chọn tất cả trang này + phân trang" TRÊN APP THẬT.

Chạy: `.venv/bin/python plans/260923-1444-chon-tat-ca-phan-trang/dung-mock.py`

index.html + app.css + app.js THẬT, thư mục tạm, danh tính giả; `/videos` trả 86
video GIẢ qua `page.route` (thư viện lớn nhất trên mini hôm 23/09 là 86). Control
mới được CHÈN vào DOM — mock, chưa phải code. Chụp 3 trạng thái × sáng/tối/điện
thoại, và lưu DOM trạng thái 2 ra `mock-chon-tat-ca-phan-trang.html` để mở tay.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import web.app as app_mod  # noqa: E402
from web.auth import require_user  # noqa: E402

OUT = Path(__file__).resolve().parent
PORT = 7896
TONG = 86

VIDEOS = [{"video_id": f"76870{i:05d}", "title": f"Video mẫu số {i + 1} #dance #trend",
           "author": f"tac_gia_{i % 7}", "duration": 12 + i % 40, "play_count": 1000 * (i + 3),
           "region": "VN", "url": "https://www.tiktok.com/", "nguon": []} for i in range(TONG)]

CSS_MOI = """
.lib-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px;
  flex-wrap:wrap; margin:10px 0 12px; }
.lib-toolbar .chon-trang { border:1px solid var(--border-strong); background:var(--surface);
  color:var(--text); border-radius:8px; padding:.4rem .8rem; font-size:.82rem; cursor:pointer; }
.lib-toolbar .chon-trang.on { background:var(--accent-soft); border-color:var(--accent); }
.per-page { display:flex; align-items:center; gap:6px; font-size:.8rem; color:var(--text-muted); }
.per-page .seg { display:inline-flex; border:1px solid var(--border); border-radius:8px; overflow:hidden; }
.per-page .seg button { border:0; background:var(--surface); color:var(--text); padding:.35rem .6rem;
  font:inherit; font-family:var(--mono); cursor:pointer; }
.per-page .seg button + button { border-left:1px solid var(--border); }
.per-page .seg button.on { background:var(--accent); color:var(--accent-ink); }
.pager { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap;
  margin:16px 0 4px; font-size:.82rem; color:var(--text-muted); }
.pager .trang { display:inline-flex; gap:4px; }
.pager .trang button { min-width:34px; border:1px solid var(--border); background:var(--surface);
  color:var(--text); border-radius:7px; padding:.3rem .55rem; font-family:var(--mono); cursor:pointer; }
.pager .trang button.on { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.pager .trang button:disabled { opacity:.45; cursor:default; }
"""


def js_chen(trang: int, so: int, da_chon: int, toast: str | None) -> str:
    """Dựng control mock; `trang` 1-based, chỉ hiện đúng thẻ của trang đó."""
    return f"""() => {{
      const st = document.createElement('style'); st.textContent = {json.dumps(CSS_MOI)};
      document.head.append(st);
      const grid = document.getElementById('card-grid');
      const cards = [...grid.children];
      const dau = ({trang} - 1) * {so}, cuoi = Math.min(dau + {so}, cards.length);
      cards.forEach((c, i) => {{ c.style.display = (i >= dau && i < cuoi) ? '' : 'none';
        const chon = i >= dau && i < dau + {da_chon};
        c.classList.toggle('selected', chon); c.setAttribute('aria-checked', String(chon)); }});
      const soTrang = Math.ceil(cards.length / {so});
      const nTrang = cuoi - dau;
      const tb = document.createElement('div'); tb.className = 'lib-toolbar';
      tb.innerHTML = `<button type="button" class="chon-trang${{{da_chon} ? ' on' : ''}}">` +
        ({da_chon} ? `☑ Bỏ chọn trang này` : `☐ Chọn tất cả trang này (${{nTrang}})`) + `</button>` +
        `<div class="per-page">Mỗi trang <span class="seg">` +
        [10, 20, 40, 100].map(n => `<button type="button" class="${{n === {so} ? 'on' : ''}}">${{n}}</button>`).join('') +
        `</span></div>`;
      grid.before(tb);
      const pg = document.createElement('div'); pg.className = 'pager';
      const nut = [...Array(soTrang)].map((_, i) =>
        `<button type="button" class="${{i + 1 === {trang} ? 'on' : ''}}">${{i + 1}}</button>`).join('');
      pg.innerHTML = `<span>Hiện ${{dau + 1}}–${{cuoi}} / ${{cards.length}} video</span>` +
        `<span class="trang"><button type="button" ${{{trang} === 1 ? 'disabled' : ''}}>‹ Trước</button>${{nut}}` +
        `<button type="button" ${{{trang} === soTrang ? 'disabled' : ''}}>Sau ›</button></span>`;
      grid.after(pg);
      const bar = document.getElementById('selection-bar');
      bar.hidden = {da_chon} === 0;
      document.getElementById('selection-count').textContent = `{da_chon} đã chọn`;
      const t = document.getElementById('toast');
      if ({json.dumps(toast)}) {{ t.textContent = {json.dumps(toast)}; t.hidden = false; }}
    }}"""


CA = [
    ("1-trang-1-chua-chon", 1, 40, 0, None),
    ("2-chon-tat-ca-trang-1", 1, 40, 40, None),
    ("3-sang-trang-3-da-bo-chon", 3, 40, 0,
     "Đã bỏ chọn 40 video vì chuyển trang — “Chọn tất cả” chỉ áp cho trang đang xem."),
]


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="videodl-mock-trang-"))
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    app_mod.worker.start = lambda: None
    app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: "mock@dev.local"
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=PORT,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.1)
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for che_do, vp, scheme in [("sang", 1200, "light"), ("toi", 1200, "dark"),
                                       ("dt", 390, "light")]:
                for ten, trang, so, chon, toast in CA:
                    page = br.new_page(viewport={"width": vp, "height": 1000}, color_scheme=scheme)
                    page.route("**/videos?*", lambda r: r.fulfill(
                        json={"tong": TONG, "videos": VIDEOS}))
                    page.goto(f"http://127.0.0.1:{PORT}/")
                    page.wait_for_function(
                        f"document.getElementById('card-grid').children.length === {TONG}")
                    page.evaluate(js_chen(trang, so, chon, toast))
                    page.screenshot(path=str(OUT / f"{che_do}-{ten}.png"), full_page=True)
                    if che_do == "sang" and ten.startswith("2-"):
                        (OUT / "mock-chon-tat-ca-phan-trang.html").write_text(
                            page.content().replace('href="/app.css"', 'href="../../web/static/app.css"'),
                            encoding="utf-8")
                    print(che_do, ten, "tràn ngang:",
                          page.evaluate("document.documentElement.scrollWidth > innerWidth"))
                    page.close()
            br.close()
    finally:
        server.should_exit = True
        t.join(timeout=5)


if __name__ == "__main__":
    main()
