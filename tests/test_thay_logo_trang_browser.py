"""Trang Thay logo (khung theo bộ, mock v4a) trên trình duyệt THẬT (Chromium, chặn mạng ngoài): bốn vùng dựng đủ, thu gọn/mở khối nhập,
tính năng tắt, lọc trạng thái, Đạt/Hỏng sát nhau + lý do chỉ hiện sau khi bấm Hỏng, không cuộn ngang, link trên thanh trên.

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
    # 2 video xong chưa đánh giá ⇒ hộp duyệt; 1 máy đang làm; 1 không chắc; 1 lỗi
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 1 && document.querySelector('#tl-duyet .tl-chi-tiet')")
    return p, loi_js


def _anh(p, ten):
    thu_muc = os.environ.get("VIDEODL_ANH_THAY_LOGO")
    if thu_muc:
        Path(thu_muc).mkdir(parents=True, exist_ok=True)
        p.screenshot(path=str(Path(thu_muc) / ten), full_page=True)


@pytest.mark.parametrize("rong", [1280, 390])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_khong_cuon_ngang_thanh_tren_khong_gay_dong(may_chu, trinh_duyet, rong, theme):
    p, loi_js = _mo(trinh_duyet, may_chu, rong, theme)
    assert loi_js == []
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), f"cuộn ngang ở {rong}px"
    cao = p.evaluate("""[...document.querySelectorAll('.brand, .topbar-nav a')].map(e => {
        const cs = getComputedStyle(e); return e.getBoundingClientRect().height / parseFloat(cs.lineHeight === 'normal'
        ? parseFloat(cs.fontSize) * 1.3 : cs.lineHeight); })""")
    assert max(cao) < 1.6, f"mục thanh trên gãy dòng ở {rong}px: {cao}"
    _anh(p, f"thay-logo-{rong}-{theme}.png")


def test_trang_dung_du_bon_vung(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    assert p.locator("#tl-nhap").is_visible() and p.locator("#tl-tabs [role=tab]").count() == 4
    assert p.locator("#tl-nhap").inner_text().count("Tên bộ") == 1 and p.locator("#tl-tao").is_visible()
    assert p.locator("#tl-bo-list").is_visible() and "sắp có" in p.locator("#tl-bo-list").inner_text()  # chưa có API bộ ⇒ báo trung thực
    assert p.locator("#tl-loc").is_visible() and p.locator("#tl-loc [data-tt]").count() == 6
    assert p.locator("#tl-duyet").is_visible() and "Chờ bạn duyệt" in p.locator("#tl-duyet").inner_text()
    chu = p.locator("aside.tl-cot").inner_text()
    assert "Máy đang làm" in chu and "Máy không chắc" in chu and "Không làm được" in chu and "Hết chỗ đĩa" in chu
    # 5 video: 2 xong chờ duyệt (1 cờ soi kỹ), 1 chờ agy, 1 không chắc, 1 lỗi
    assert "2 video chờ duyệt" in p.locator("#tl-tom-tat").inner_text() and "1 cần bạn xem kỹ" in p.locator("#tl-tom-tat").inner_text()
    assert "Chờ agy · 14 phút" in p.locator("#tl-dang-lam").inner_text()
    _anh(p, "khung-1280.png")
    p.locator("#tl-tabs [role=tab]").nth(2).click()  # tab chưa có API ⇒ "sắp có", không dữ liệu giả
    assert "Sắp có" in p.locator("#tl-vung").inner_text()


def test_thu_gon_va_mo_khoi_nhap(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    assert p.locator("#tl-form").is_visible() and not p.locator("#tl-nhap-gon").is_visible()
    p.locator("#tl-thu-gon").click()
    assert not p.locator("#tl-form").is_visible() and p.locator("#tl-nhap-gon").is_visible()
    assert "4 nguồn" in p.locator("#tl-nhap-gon").inner_text()
    p.locator("#tl-nhap-gon").click()
    assert p.locator("#tl-form").is_visible() and not p.locator("#tl-nhap-gon").is_visible()


def test_tinh_nang_tat_bao_tat_va_khoa_nut_tao(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    assert p.locator("#tat").is_visible()  # worker chưa dựng ⇒ báo tính năng tắt
    p.wait_for_function("document.getElementById('tl-tao').disabled")
    assert p.locator("#tl-ten-bo").is_disabled()


def test_loc_trang_thai_thu_hep_cot_phai(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    p.locator("#tl-loc [data-tt=loi]").click()
    assert p.locator("#tl-khong-lam .tl-muc").count() == 1 and p.locator("#tl-dang-lam .tl-muc").count() == 0
    assert "Không có video nào chờ" in p.locator("#tl-duyet").inner_text()


@pytest.mark.parametrize("rong", [1280, 390])
def test_dat_hong_sat_nhau_ly_do_chi_hien_sau_khi_bam_hong(may_chu, trinh_duyet, rong):
    p, _ = _mo(trinh_duyet, may_chu, rong)
    p.wait_for_function("[...document.images].every(i => i.complete)")
    dat, hong = p.locator(".tl-dat"), p.locator(".tl-hong-nut")
    bd, bh = dat.bounding_box(), hong.bounding_box()
    if rong > 600:
        assert abs(bd["y"] - bh["y"]) < 4 and 0 <= bh["x"] - (bd["x"] + bd["width"]) < 24, "Đạt/Hỏng phải sát nhau"
    assert not p.locator(".tl-ly-do").is_visible()
    hong.click()
    assert p.locator(".tl-ly-do select").is_visible() and p.locator(".tl-ly-do input[type=text]").is_visible()


def test_bam_dat_ghi_danh_gia(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    p.locator(".tl-dat").click()
    p.wait_for_function("document.querySelector('#tl-loc [data-tt=da_dat]').innerText.includes('1')")
    conn = nhat_ky.mo(app_mod.DATA_DIR / "thay_logo_log.db")
    assert [tuple(r) for r in conn.execute("SELECT member, ket_qua FROM tl_danh_gia")] == [(NGUOI, "dat")]


# ---------------------------------------------------------------- link trên thanh trên trang Tải video

@pytest.mark.parametrize("bat", [False, True])
@pytest.mark.parametrize("rong", [1100, 390])
def test_link_thay_logo_chi_hien_khi_tinh_nang_bat(may_chu, trinh_duyet, monkeypatch, bat, rong):
    """Tính năng TẮT ⇒ member không thấy link (nợ code-reviewer PR #69). BẬT ⇒ link hiện và thanh trên vẫn không gãy dòng/cuộn ngang."""
    monkeypatch.setattr(app_mod, "worker_thay_logo", object() if bat else None)
    ctx = trinh_duyet.new_context(viewport={"width": rong, "height": 800})
    chan = dem_mang_ngoai(ctx)
    p = ctx.new_page()
    mo_trang(p, f"{may_chu}/", chan)
    p.wait_for_load_state("networkidle")
    link = p.locator("#link-thay-logo")
    assert link.is_visible() is bat
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    cao = p.evaluate("""[...document.querySelectorAll('.brand, .topbar-nav a')].filter(e => e.offsetParent).map(e => {
        const cs = getComputedStyle(e); return e.getBoundingClientRect().height / parseFloat(cs.lineHeight === 'normal'
        ? parseFloat(cs.fontSize) * 1.3 : cs.lineHeight); })""")
    assert max(cao) < 1.6, f"thanh trên gãy dòng ở {rong}px khi link {'hiện' if bat else 'ẩn'}: {cao}"
