"""Chụp ảnh CODE THẬT của "Cụm của tôi" (không chèn DOM): app thật + DB tạm.

Chạy lại (từ gốc worktree):
  PYTHONPATH=$PWD/src:$PWD /Users/macos/Projects/video-download/.venv/bin/python \
      plans/260923-1558-tai-theo-cum/sau-thi-cong/chup-anh.py

Dữ liệu giả: 86 video của một người; 4 cụm — "Badaboum couple" 40 video (>30 ⇒ 2 bộ,
bộ 1 đã mở), "Badaboum Cartoon" 12 (đã mở), "Badaboum nhóm" 9, "Birthday Virgo chibi"
7; còn 18 chưa vào cụm. Chưa có ảnh bìa nên thẻ hiện "Chưa cắt được ảnh" (đường
thật của app khi thiếu ảnh).
"""
from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

import web.app as app_mod
from web import models, models_cum
from web.auth import require_user

RA = Path(__file__).resolve().parent
NGUOI = "anh@dev.local"


def mo_du_lieu(db: Path) -> int:
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/badaboum", 86, NGUOI)
    tieu_de = ["Nhảy đôi Badaboum 💃", "Couple prank", "Solo mirror dance", "Hoạt hình 3D nhảy",
               "Nhảy nhóm Kpop", "Vẽ tay nhảy", "Trend nhảy văn phòng", "Cặp đôi nhảy biển"]
    ids = []
    for i in range(86):
        vid = f"76877{i:05d}"
        models.record_video(db, job_id=job, video_id=vid, url=f"https://www.tiktok.com/@a/video/{vid}",
                            title=f"{tieu_de[i % len(tieu_de)]} #{i + 1}", author=f"@creator{i}",
                            region="VN" if i % 3 else "US", duration=12 + i % 40,
                            play_count=1000 * (i * 7 % 90 + 3), drive_file_id=f"drv{i}",
                            tao_luc=f"2026-09-23T0{i // 60}:{i % 60:02d}:00+00:00")
        ids.append(vid)
    lon, _ = models_cum.tao_cum(db, NGUOI, "Dance", "Badaboum", "couple")
    cartoon, _ = models_cum.tao_cum(db, NGUOI, "Dance", "Badaboum", "Cartoon")
    nhom, _ = models_cum.tao_cum(db, NGUOI, "Dance", "Badaboum", "nhóm")
    chibi, _ = models_cum.tao_cum(db, NGUOI, "Portrait", "Birthday Virgo", "chibi")
    models_cum.gan_video(db, lon, NGUOI, NGUOI, ids[:40])
    models_cum.gan_video(db, cartoon, NGUOI, NGUOI, ids[40:52])
    models_cum.gan_video(db, nhom, NGUOI, NGUOI, ids[52:61])
    models_cum.gan_video(db, chibi, NGUOI, NGUOI, ids[61:68])
    models_cum.ghi_lo_da_mo(db, lon, NGUOI, 1)
    models_cum.ghi_lo_da_mo(db, cartoon, NGUOI, 1)
    return lon


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="videodl-anh-cum-"))
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    lon = mo_du_lieu(app_mod.DB_PATH)
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/"

    def chup(pw, ten, rong, cao, theme, popover=True, cum=True, mobile=False):
        br = pw.chromium.launch()
        p = br.new_page(viewport={"width": rong, "height": cao}, is_mobile=mobile,
                        device_scale_factor=2 if mobile else 1)
        p.add_init_script(f"localStorage.setItem('videodl-theme', '{theme}')")
        p.goto(url)
        p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
        if cum:
            p.click(f"#cum-rail [data-cum-loc='{lon}']")
        if popover:
            for i in range(3):
                p.locator("#card-grid .card").nth(i).click()
            p.click('[data-action="cum"]')
            f = p.locator("#cum-popover .cum-form")
            f.locator('[data-cum-o="kieu"]').fill("3D")
        p.evaluate("document.querySelector('.library-head').scrollIntoView()")
        p.wait_for_timeout(500)
        dich = RA / ten
        p.screenshot(path=str(dich))
        br.close()
        print(dich)

    with sync_playwright() as pw:
        chup(pw, "sang-cum-lon-popover.png", 1400, 1100, "light")
        chup(pw, "toi-cum-lon-popover.png", 1400, 1100, "dark")
        chup(pw, "dien-thoai-390-popover.png", 390, 844, "light", mobile=True)
        chup(pw, "dien-thoai-390-dau-cum.png", 390, 844, "light", popover=False, mobile=True)
        chup(pw, "sang-tat-ca.png", 1400, 1100, "light", popover=False, cum=False)
    server.should_exit = True


if __name__ == "__main__":
    main()
