"""Màn duyệt nháp "tự chia cụm" (phase 3+4) — luồng thật trên TRÌNH DUYỆT.

App thật (uvicorn, DB tạm, worker tắt, danh tính giả) — cùng khuôn
`test_cum_browser_and_js.py`. Fixture dựng qua CÁC HÀM MODEL THẬT
(`models.create_job`/`record_video`, `models_chia.nhap_de_xuat`), không SQL
tay, để nháp đi qua đúng luật lọc/ghi mà server thật áp dụng.

Không có node / Playwright / Chromium thì test tương ứng SKIP — suite xanh
không phải bằng chứng đã kiểm; đọc dòng skip trước khi tin bất cứ gì.
"""
from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from web import app as app_mod
from web import models, models_chia

NGUOI = "chiacum@dev.local"


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-chiacum-"))
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/", tmp / "jobs.db"
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)
    # KHÔNG xoá `tmp` — cùng lý do `test_cum_browser_and_js.py::may_chu`.


def _job_voi_video(db: Path, so_video: int) -> int:
    job = models.create_job(db, "https://www.tiktok.com/tag/chia-cum", so_video, NGUOI)
    for i in range(so_video):
        models.record_video(db, job_id=job, video_id=f"77{job:03d}{i:04d}", url=f"https://t/{i}",
                            title=f"Video {i + 1}", drive_file_id=f"drive_{job:03d}{i:04d}",
                            tao_luc=f"2026-09-27T00:{i // 60:02d}:{i % 60:02d}+00:00")
    return job


def _job_full(db: Path) -> tuple[int, dict]:
    """10 video: 2 nhóm (3 kiểu) + 2 hướng dẫn + 2 nghi."""
    job = _job_voi_video(db, 10)
    ids = [f"77{job:03d}{i:04d}" for i in range(10)]
    nhoms = [
        {"nhom": "Âu phục", "kieu": [{"kieu": "Mặc vest", "video_ids": ids[0:3]}]},
        {"nhom": "Đồng phục", "kieu": [
            {"kieu": "Học sinh", "video_ids": ids[3:5]},
            {"kieu": "Thể thao", "video_ids": ids[5:6]},
        ]},
    ]
    ket = models_chia.nhap_de_xuat(db, job, "vision:v1", "trang_phuc_dam_dong", nhoms,
                                   ids[6:8], ids[8:10], [])
    assert ket is not None and not ket["bo_vi_loc"]
    return job, {"ids": ids}


@pytest.fixture
def dulieu(may_chu):
    url, db = may_chu
    models.init_db(db)
    with models._connect(db) as conn:
        conn.execute("DELETE FROM cum")
        conn.execute("DELETE FROM cum_nhap")
        conn.execute("DELETE FROM video_cum_nhap")
        conn.execute("DELETE FROM chia_lan")
        conn.execute("DELETE FROM thao_tac_duyet")
        conn.execute("DELETE FROM video_cum")
        conn.execute("DELETE FROM videos")
        conn.execute("DELETE FROM jobs")
        for t in ("cum", "chia_lan", "jobs"):
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (t,))
    job_full, info = _job_full(db)
    job_empty = _job_voi_video(db, 3)   # chưa nhap_de_xuat ⇒ GET /chia trả 404
    return {"url": url, "db": db, "job_full": job_full, "job_empty": job_empty, **info}


@pytest.fixture
def page(dulieu):
    pw_api = pytest.importorskip("playwright.sync_api")
    with pw_api.sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
            pytest.skip(f"không mở được Chromium: {exc}")
        ctx = br.new_context(viewport={"width": 1300, "height": 900})
        p = ctx.new_page()
        p.goto(dulieu["url"])
        p.wait_for_selector("#queue-list li")
        yield p
        br.close()


def _mo_chia(p, job_id: int) -> None:
    p.click(f'[data-chia="{job_id}"]')
    p.wait_for_function("!document.getElementById('chia-view').hidden")
    p.wait_for_function("document.getElementById('cc-tieude').textContent.length > 0")


# ---------------------------------------------------------------------------

def test_dom_dem_khop_tieu_de_va_khong_trung_video(page, dulieu):
    _mo_chia(page, dulieu["job_full"])
    tieude = page.inner_text("#cc-tieude")
    assert "2 nhóm" in tieude and "3 kiểu" in tieude
    assert "thẻ chữ 2" in tieude and "nghi 2" in tieude

    the = page.locator("#cc-main .cc-t[data-cc-video]")
    assert the.count() == 10
    ids = [the.nth(i).get_attribute("data-cc-video") for i in range(the.count())]
    assert len(ids) == len(set(ids)), "một video xuất hiện ở hơn một chỗ"


def test_insight_trong_khoa_nut_va_hien_ly_do_roi_dien_thi_mo(page, dulieu):
    _mo_chia(page, dulieu["job_full"])
    assert page.locator('[data-cc-action="duyet-het"]').is_disabled()
    assert page.locator('[data-cc-action="duyet-kieu"]').first.is_disabled()
    assert page.locator('[data-cc-action="toggle-gop"]').first.is_disabled()
    assert page.locator(".cc-why").count() == 1

    truoc = _so_thao_tac(page)
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="usecase"]', "Motion")
        page.locator('[data-cc-field="usecase"]').blur()
    page.wait_for_timeout(150)
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="insight_goc"]', "Strom Ai")
        page.locator('[data-cc-field="insight_goc"]').blur()
    page.wait_for_function("!document.querySelector('[data-cc-action=\"duyet-het\"]').disabled")
    assert _so_thao_tac(page) == truoc + 2, "mỗi ô gõ phải ghi đúng MỘT dòng doi_insight"
    assert not page.locator('[data-cc-action="duyet-kieu"]').first.is_disabled()
    assert not page.locator('[data-cc-action="toggle-gop"]').first.is_disabled()
    assert page.locator(".cc-why").count() == 0

    with page.expect_response(lambda r: "/duyet" in r.url):
        page.locator('[data-cc-action="duyet-kieu"]').first.click()
    page.wait_for_function("document.querySelectorAll('.cc-kieu').length < 3")


def _so_thao_tac(page) -> int:
    txt = page.inner_text("#cc-nut")
    import re
    m = re.search(r"(\d+) thao tác sửa", txt)
    assert m, txt
    return int(m.group(1))


def test_tao_bo_tu_tim_khoa_o_nhap(page, dulieu):
    _mo_chia(page, dulieu["job_full"])
    nut = page.locator('#cc-main button:has-text("Tạo bộ tự tìm")')
    assert nut.count() == 3
    for i in range(nut.count()):
        assert nut.nth(i).is_disabled()


def test_khong_co_nhap_hien_lenh_khong_nut_chay(page, dulieu):
    _mo_chia(page, dulieu["job_empty"])
    assert page.locator(".cc-kieu").count() == 0
    cmd = page.inner_text("#cc-main .cc-cmd code")
    assert f"--luot {dulieu['job_empty']}" in cmd.replace("\n", " ")
    # Không nút nào ngoài "Chép" trong khối trạng thái rỗng.
    buttons = page.locator("#cc-main .cc-empty button")
    assert buttons.count() == 1
    assert "Chép" in buttons.first.inner_text()


def test_tach_tao_kieu_moi_tang_bo_dem_hoan_tac_xoa(page, dulieu):
    _mo_chia(page, dulieu["job_full"])
    assert page.locator(".cc-kieu").count() == 3
    truoc = _so_thao_tac(page)
    assert page.locator('[data-cc-action="hoan-tac"]').is_disabled()

    page.locator('.cc-t[data-cc-video]').first.click()
    page.locator('.cc-t[data-cc-video]').nth(1).click()
    page.click('[data-cc-action="dock-tach"]')
    page.wait_for_selector(".cc-modal")
    page.fill('[data-cc-tach-kieu]', "Vest trắng")
    page.locator('[data-cc-tach-kieu]').dispatch_event("change")
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.click('[data-cc-action="confirm-tach"]')
    page.wait_for_function("document.querySelectorAll('.cc-kieu').length === 4")
    assert _so_thao_tac(page) == truoc + 1
    assert page.locator('[data-cc-action="hoan-tac"]').is_enabled()

    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.click('[data-cc-action="hoan-tac"]')
    page.wait_for_function("document.querySelectorAll('.cc-kieu').length === 3")
    assert page.locator('[data-cc-action="hoan-tac"]').is_disabled()


def test_huy_lenh_moi_token_khong_ngat_dong_390(page, dulieu):
    page.set_viewport_size({"width": 390, "height": 800})
    _mo_chia(page, dulieu["job_full"])
    page.click('[data-cc-action="mo-huy"]')
    page.wait_for_selector(".cc-modal")
    spans = page.locator(".cc-cmd code span")
    n = spans.count()
    assert n >= 5
    for i in range(n):
        assert spans.nth(i).evaluate("el => el.getClientRects().length") == 1, \
            f"token {i} bị ngắt giữa chừng ở 390px"
