"""Chip "Đã vào bộ", huy hiệu mã bộ và lô của cụm sau khi dọn — TRÌNH DUYỆT THẬT.

App thật (uvicorn, DB tạm, worker + bộ kiểm định kỳ tắt, danh tính giả); `/videos`,
`/cum` và payload lô đi qua route + SQL thật. Dữ liệu mồi (70 video):
  · v00..v64 → cụm "Badaboum couple" (65 video ⇒ lô 30/30/5); v04 đã DỌN khỏi Drive;
  · v65, v66, v67 → đã vào bộ, đang ẩn (v66 nằm ở HAI bộ);
  · v68, v69 → video thường.

Đặt `VIDEODL_SHOT_DIR=<thư mục>` để test lưu ảnh chụp màn hình (`shot-*.png`).
Không có Chromium thì test SKIP — đừng đọc suite xanh thành "đã kiểm".
"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from web import app as app_mod
from web import models, models_cum, models_vao_bo

NGUOI = "vaobo@dev.local"
TONG = 70


def _id(i: int) -> str:
    return f"76870{i:05d}"


def _luc(i: int) -> str:
    return f"2026-09-23T00:{i // 60:02d}:{i % 60:02d}+00:00"


def _ban(cid: str, ma: str) -> dict:
    return {"ban_copy_id": cid, "folder_id": "F" + cid, "ma_bo": ma, "bang_chung": "properties"}


def _mo_thumb_gia(tmp: Path) -> None:
    """Ảnh thumb màu trơn cho ảnh chụp màn hình đỡ trống. Không có Pillow thì bỏ qua —
    thẻ hiện ô thay thế, các phép đo bên dưới không phụ thuộc vào ảnh."""
    try:
        from PIL import Image
    except ImportError:
        return
    thu_muc = tmp / "thumbs"
    thu_muc.mkdir(parents=True, exist_ok=True)
    for i in range(TONG):
        r, g, b = ((i * 37) % 160 + 60, (i * 71) % 160 + 60, (i * 113) % 160 + 60)
        Image.new("RGB", (180, 320), (r, g, b)).save(thu_muc / f"{_id(i)}.webp", "WEBP")


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    os.environ["VIDEODL_BAT_DON_NGAY7"] = "1"       # bật để thẻ hiện ngày xoá; test OFF tự tắt
    tmp = Path(tempfile.mkdtemp(prefix="videodl-vaobo-"))
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    db = tmp / "jobs.db"
    models.init_db(db)
    job = models.create_job(db, "https://www.tiktok.com/tag/dance", TONG, NGUOI)
    for i in range(TONG):
        models.record_video(db, job_id=job, video_id=_id(i), url=f"https://t/{i}",
                            title=f"Video {i + 1}", author="dancer", region="VN", duration=15,
                            drive_file_id=f"drive_file_{i:05d}", tao_luc=_luc(i))
    cum_id, _ = models_cum.tao_cum(db, NGUOI, "Dance", "Badaboum", "couple")
    models_cum.gan_video(db, cum_id, NGUOI, NGUOI, [_id(i) for i in range(65)])
    bay_gio = datetime.now(timezone.utc)
    models_vao_bo.ghi_da_vao_bo(db, _id(65), NGUOI, [_ban("a", "N.2809C")],
                                (bay_gio - timedelta(days=1)).isoformat())
    models_vao_bo.ghi_da_vao_bo(db, _id(66), NGUOI, [_ban("b", "N.2809C"), _ban("c", "N.2909B")],
                                (bay_gio - timedelta(days=6)).isoformat())
    models_vao_bo.ghi_da_vao_bo(db, _id(67), NGUOI, [_ban("d", "PN.2209E")],
                                (bay_gio - timedelta(days=3)).isoformat())
    # v04 (ở lô 1 của cụm) đã ẩn đủ 7 ngày và tệp nguồn đã vào Thùng rác.
    models_vao_bo.ghi_da_vao_bo(db, _id(4), NGUOI, [_ban("e", "N.2609D")],
                                (bay_gio - timedelta(days=8)).isoformat())
    models_vao_bo.ghi_don_drive(db, _id(4), "da_don")
    # Người xem là quản trị (thấy badge "Dọn lỗi"); v68 mang một ca nguồn-chết-không-bản-sao
    # (hàng sổ KHÔNG ẩn video: `an_luc` NULL).
    models.moi_admin_tu_env(db, [NGUOI])
    models_vao_bo.ghi_bao_dong(db, _id(68), NGUOI, "nguon_o_thung_rac_khong_ban_sao")
    models_vao_bo.ghi_tap_thu_lai(db, {_id(68): 4, _id(69): 1})     # 2 id đo lỗi lặp, lâu nhất 4
    _mo_thumb_gia(tmp)
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port,
                                           log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/", cum_id
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    os.environ.pop("VIDEODL_BAT_DON_NGAY7", None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)


@pytest.fixture
def page(may_chu):
    url, _ = may_chu
    pw_api = pytest.importorskip("playwright.sync_api")
    with pw_api.sync_playwright() as pw:
        try:
            br = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"không mở được Chromium: {exc}")
        ctx = br.new_context(viewport={"width": 1300, "height": 950})
        p = ctx.new_page()
        p.goto(url)
        p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
        p.click('#so-moi-trang [data-so="100"]')      # cả 66 thẻ trên một trang
        yield p
        br.close()


def _chup(p, ten: str) -> None:
    """Chụp riêng khối "Thư viện creative" (đủ thanh bên, chip, lưới, đầu cụm)."""
    thu_muc = os.environ.get("VIDEODL_SHOT_DIR")
    if thu_muc:
        p.locator("section[aria-label='Thư viện creative']").screenshot(
            path=str(Path(thu_muc) / f"shot-{ten}.png"))


def _ids_tren_luoi(p) -> set[str]:
    return set(p.eval_on_selector_all("#card-grid .card", "els => els.map(e => e.dataset.videoId)"))


def test_luoi_mac_dinh_an_video_da_vao_bo_va_khong_hien_video_da_don(page):
    ids = _ids_tren_luoi(page)
    assert len(ids) == 66
    assert not ids & {_id(65), _id(66), _id(67)}, "video đã vào bộ bị ẩn khỏi lưới mặc định"
    assert _id(4) not in ids, "video đã dọn không hiện ở đâu"
    assert page.inner_text("#library-count") == "66 video"
    assert page.inner_text("#chip-vao-bo") == "Đã vào bộ (3)", "chip đếm đúng 3, không đếm video đã dọn"
    assert page.locator("#card-grid .card-bo").count() == 0
    # Số đếm trong hộp lọc khớp lưới đang nhìn (66), không tính video đang ẩn.
    page.click('[data-toggle="thi_truong"]')
    assert page.inner_text('.filter-panel[data-panel="thi_truong"] .opt-count') == "66"
    page.keyboard.press("Escape")
    page.click('#so-moi-trang [data-so="10"]')       # ảnh chụp gọn: 10 thẻ đầu
    page.wait_for_function("document.querySelectorAll('#card-grid .card').length === 10")
    _chup(page, "01-luoi-mac-dinh")


def test_chip_da_vao_bo_chi_hien_ba_video_do_moi_the_co_ma_bo_va_ngay_xoa(page):
    page.click("#chip-vao-bo")
    assert _ids_tren_luoi(page) == {_id(65), _id(66), _id(67)}
    assert page.inner_text("#library-count") == "3 video đã vào bộ"
    assert page.get_attribute("#chip-vao-bo", "aria-pressed") == "true"
    theo_id = {}
    for the in page.locator("#card-grid .card").all():
        theo_id[the.get_attribute("data-video-id")] = (
            the.locator(".bo-ma").inner_text(), the.locator(".bo-don").inner_text())
    assert theo_id[_id(65)][0] == "N.2809C"
    assert theo_id[_id(66)][0] == "N.2809C · N.2909B", "nhiều bộ ⇒ nối bằng ' · '"
    assert theo_id[_id(67)][0] == "PN.2209E"
    api = page.evaluate("fetch('/videos?limit=500').then(r => r.json())")
    for v in api["videos"]:
        if v["vao_bo"]:
            ngay = page.evaluate("(iso) => new Date(iso).toLocaleDateString('vi-VN')",
                                 v["vao_bo"]["se_don_luc"])
            assert theo_id[v["video_id"]][1] == f"Xoá khỏi Video Desk {ngay}"
    # Ngày xoá = an_luc + 7 ngày: video ẩn 6 ngày trước ⇒ còn 1 ngày.
    v66 = next(v for v in api["videos"] if v["video_id"] == _id(66))
    con_lai = datetime.fromisoformat(v66["vao_bo"]["se_don_luc"]) - datetime.now(timezone.utc)
    assert timedelta(hours=22) < con_lai < timedelta(hours=25)
    _chup(page, "02b-chip-da-vao-bo-don-ngay7-bat")


def test_bam_chip_lan_nua_ve_luoi_mac_dinh(page):
    page.click("#chip-vao-bo")
    page.click("#chip-vao-bo")
    assert len(_ids_tren_luoi(page)) == 66
    assert page.get_attribute("#chip-vao-bo", "aria-pressed") == "false"


def test_xoa_het_bo_loc_thoat_khoi_che_do_da_vao_bo(page):
    page.click("#chip-vao-bo")
    # Chọn cụm "Badaboum couple": không có video đã vào bộ nào trong đó ⇒ không khớp gì
    # ⇒ hiện nút "Xoá hết bộ lọc", và bấm nó phải đưa chip về trạng thái tắt.
    page.click("#cum-rail .cum-sub")
    page.wait_for_selector("#no-match-state:not([hidden])")
    page.click("#clear-filters-btn")
    assert page.get_attribute("#chip-vao-bo", "aria-pressed") == "false"
    assert len(_ids_tren_luoi(page)) == 66


def test_cum_sau_khi_don_lo_1_hut_mot_video_lo_2_lo_3_giu_nguyen(page, may_chu):
    _, cum_id = may_chu
    assert page.inner_text("#cum-rail [data-cum-loc='tat_ca'] .n") == "66"
    page.click("#cum-rail .cum-sub")
    page.wait_for_function("document.getElementById('cum-head') && !document.getElementById('cum-head').hidden")
    head = page.inner_text("#cum-head")
    assert "64 video" in head
    assert page.inner_text("#cum-head [data-mo-het]") == "Tạo 3 bộ tự tìm (29/30 + 30 + 5)"
    hang = [page.inner_text(f"#cum-head .bo-row[data-lo='{i}']") for i in (1, 2, 3)]
    assert hang[0].startswith("Bộ 1/3") and "29/30 video" in hang[0]
    assert hang[1].startswith("Bộ 2/3") and "30 video" in hang[1] and "/" not in hang[1].split("video")[0][6:]
    assert hang[2].startswith("Bộ 3/3") and "5 video" in hang[2]
    # Server: lô 2 và lô 3 giữ ĐÚNG nội dung (video 31..60, 61..65); lô 1 hụt v04.
    p1 = page.evaluate(f"fetch('/cum/{cum_id}/lo/1/payload').then(r => r.json())")
    p2 = page.evaluate(f"fetch('/cum/{cum_id}/lo/2/payload').then(r => r.json())")
    p3 = page.evaluate(f"fetch('/cum/{cum_id}/lo/3/payload').then(r => r.json())")
    assert [i["n"] for i in p2["items"]] == [f"Video {k}" for k in range(31, 61)]
    assert [i["n"] for i in p3["items"]] == [f"Video {k}" for k in range(61, 66)]
    assert (len(p1["items"]), p1["so_video"]) == (29, 30)
    assert "Video 5" not in [i["n"] for i in p1["items"]]
    page.click('#so-moi-trang [data-so="10"]')
    _chup(page, "03-cum-sau-don-lo-1-x-tren-n")


def test_admin_thay_badge_don_loi_va_video_do_van_hien_o_luoi(page):
    page.wait_for_selector("#badge-don-loi:not([hidden])")
    assert page.inner_text("#badge-don-loi") == "Dọn lỗi (1)"
    assert "nguon_o_thung_rac_khong_ban_sao" in page.get_attribute("#badge-don-loi", "title")
    assert _id(68) in _ids_tren_luoi(page), "hàng báo động KHÔNG ẩn video"


def test_khi_don_ngay7_tat_the_khong_hien_ngay_xoa_nhung_van_hien_ma_bo(page):
    os.environ.pop("VIDEODL_BAT_DON_NGAY7", None)
    try:
        page.click("#library-refresh")
        page.wait_for_function("document.getElementById('chip-vao-bo').textContent === 'Đã vào bộ (3)'")
        page.click("#chip-vao-bo")
        assert page.locator("#card-grid .bo-ma").count() == 3
        assert page.locator("#card-grid .bo-don").count() == 0, "tắt ⇒ không hứa ngày xoá"
        _chup(page, "02-chip-da-vao-bo-don-ngay7-tat")
    finally:
        os.environ["VIDEODL_BAT_DON_NGAY7"] = "1"


def test_admin_thay_badge_do_loi_lap_chi_dem_khong_nguong(page):
    page.wait_for_selector("#badge-do-loi-lap:not([hidden])")
    assert page.inner_text("#badge-do-loi-lap") == "2 id đo lỗi lặp, lâu nhất 4 lần"
