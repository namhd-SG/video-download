"""Trang Thay logo trên trình duyệt THẬT (Chromium, chặn mạng ngoài): không cuộn ngang ở 390/1100, thanh trên không gãy dòng, 5 kiểu thẻ
đúng mock M1 + 4 sửa ĐP-1507 (Đạt/Hỏng sát nhau, lý do chỉ hiện SAU khi bấm Hỏng, ô form theo app.css), cờ "Cần soi kỹ" RÕ trên thẻ.

Ảnh chụp sáng/tối ghi vào `$VIDEODL_ANH_THAY_LOGO` nếu có đặt (để người duyệt tự mở).
"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang
from web import app as app_mod

NGUOI = "thaylogo@dev.local"


def _seed(data: Path) -> None:
    conn = nhat_ky.mo(data / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    j = hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": f"FILE{i:02d}" + "x" * 12} for i in range(5)])
    ids = [r[0] for r in conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (j,))]
    sheet = data / "sheet.jpg"
    from PIL import Image
    Image.new("RGB", (400, 480), (90, 110, 100)).save(sheet, "JPEG")
    for k, (vid, tt) in enumerate(zip(ids, ("xong", "xong", "cho_agy", "cho_nguoi", "loi"))):
        log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
        nhat_ky.cap_nhat_video(conn, log_id, duong_dan_sheet=str(sheet) if tt == "xong" else None)
        conn.execute("INSERT INTO tl_vet (video_id, vet, trang_thai, pct_render, net_la_pho_bien) VALUES (?,?,?,?,?)",
                     (log_id, 0, "render", 97.0 if k == 0 else 66.0, 1 if k == 1 else 0))
        conn.commit()
        hang_doi.dat(conn, vid, tt, video_log_id=log_id, drive_file_id_ra="OUT" + "y" * 15 if tt == "xong" else None,
                     cho_agy_tu=time.time() - 14 * 60 if tt == "cho_agy" else None,
                     loi_text="Hết chỗ đĩa khi ghi video ra." if tt == "loi" else None)
    conn.close()


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-thaylogo-"))
    _seed(tmp)
    cu = {k: getattr(app_mod, k) for k in ("DATA_DIR", "DB_PATH", "COOKIES_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH, app_mod.COOKIES_DIR = tmp, tmp / "jobs.db", tmp / "cookies"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)


@pytest.fixture
def trinh_duyet():
    pw_api = pytest.importorskip("playwright.sync_api")
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch(args=ARGS_CHAN_MANG)
    except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    yield br
    br.close()
    pw.stop()


def _mo(br, goc, rong, theme="light"):
    ctx = br.new_context(viewport={"width": rong, "height": 900}, color_scheme=theme)
    chan = dem_mang_ngoai(ctx)
    p = ctx.new_page()
    loi_js: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    mo_trang(p, f"{goc}/thay-logo.html", chan)
    p.wait_for_function("document.querySelectorAll('#tl-list .tl-card').length === 5")
    return p, loi_js


@pytest.mark.parametrize("rong", [1100, 390])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_khong_cuon_ngang_thanh_tren_khong_gay_dong(may_chu, trinh_duyet, rong, theme):
    p, loi_js = _mo(trinh_duyet, may_chu, rong, theme)
    assert loi_js == []
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), f"cuộn ngang ở {rong}px"
    cao = p.evaluate("""[...document.querySelectorAll('.brand, .topbar-nav a')].map(e => {
        const cs = getComputedStyle(e); return e.getBoundingClientRect().height / parseFloat(cs.lineHeight === 'normal'
        ? parseFloat(cs.fontSize) * 1.3 : cs.lineHeight); })""")
    assert max(cao) < 1.6, f"mục thanh trên gãy dòng ở {rong}px: {cao}"
    thu_muc = os.environ.get("VIDEODL_ANH_THAY_LOGO")
    if thu_muc:
        Path(thu_muc).mkdir(parents=True, exist_ok=True)
        p.screenshot(path=str(Path(thu_muc) / f"thay-logo-{rong}-{theme}.png"), full_page=True)


def test_nam_kieu_the_va_co_can_soi_ky_ro_tren_the(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1100)
    the = p.locator("#tl-list .tl-card")
    chu = [the.nth(i).inner_text() for i in range(5)]
    assert sum("Đã thay · chờ duyệt" in c for c in chu) == 2
    assert any("Chờ agy · 14 phút" in c for c in chu)
    assert any("Không thay được" in c for c in chu)
    assert any("Hết chỗ đĩa" in c and "video gốc không bị ảnh hưởng" in c for c in chu)
    soi = p.locator(".tl-card.co-co")
    assert soi.count() == 1 and soi.locator(".tl-co").is_visible() and "Cần soi kỹ" in soi.inner_text()
    assert p.locator("#tat").is_visible()  # worker chưa dựng ⇒ báo tính năng tắt


@pytest.mark.parametrize("rong", [1100, 390])
def test_dat_hong_sat_nhau_ly_do_chi_hien_sau_khi_bam_hong(may_chu, trinh_duyet, rong):
    p, _ = _mo(trinh_duyet, may_chu, rong)
    the = p.locator(".tl-card").filter(has=p.get_by_role("button", name="Đạt")).first
    dat, hong = the.get_by_role("button", name="Đạt"), the.get_by_role("button", name="Hỏng…")
    hd, hh = dat.bounding_box(), hong.bounding_box()
    assert abs(hd["y"] - hh["y"]) < 4 and 0 <= hh["x"] - (hd["x"] + hd["width"]) < 24, "Đạt/Hỏng phải sát nhau"
    assert not the.locator("select").is_visible()
    hong.click()
    assert the.locator("select").is_visible() and the.locator("input[type=text]").is_visible()


def test_bam_dat_ghi_danh_gia(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1100)
    the = p.locator(".tl-card").filter(has=p.get_by_role("button", name="Đạt")).first
    the.get_by_role("button", name="Đạt").click()
    p.wait_for_function("document.body.innerText.includes('Đã đánh giá: Đạt')")
    conn = nhat_ky.mo(app_mod.DATA_DIR / "thay_logo_log.db")
    assert [tuple(r) for r in conn.execute("SELECT member, ket_qua FROM tl_danh_gia")] == [(NGUOI, "dat")]
