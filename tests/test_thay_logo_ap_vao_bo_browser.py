"""Đợt 2A trên trình duyệt THẬT (Chromium, chặn mạng ngoài): bấm một bộ "Đã vào bộ" đã duyệt xong ⇒ thẻ mở rộng có nút "Áp N video Đạt
vào bộ" ⇒ bấm ⇒ thread `tl-ap` thật chạy trên Drive giả ⇒ thẻ đổi sang "Đã áp … · Hoàn tác" ⇒ bấm Hoàn tác ⇒ về như cũ. Cờ tắt ⇒ không nút.

Ảnh chụp ghi vào `$VIDEODL_ANH_THAY_LOGO` nếu có đặt (2a-truoc-ap-1280.png, 2a-da-ap-1280.png, 2a-mot-xong-mot-lui-1280.png)."""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import types
from pathlib import Path

import pytest
from drive_gia_thay_logo import DriveGiaTL

from tiktok_music_downloader.thay_logo import ap_vao_bo, hang_doi, nhat_ky
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang
from web import app as app_mod

NGUOI = "thaylogo@dev.local"
F1, DAU_RA = "FOLDERBO1" + "f" * 12, "DAURAFOLD0" + "o" * 10
BAN = {i: f"BANCOPY{i:04d}" + "q" * 10 for i in range(1, 7)}
RA = {i: f"RAFILE{i:04d}" + "r" * 10 for i in range(1, 7)}
F2 = "FOLDERBO2" + "g" * 12
VID = lambda i: f"7100000000000000{i}"  # noqa: E731 — id số (route /thumbs chỉ nhận id số)
DG = {1: "dat", 2: "dat", 3: "dat", 4: "hong"}


def _seed(data: Path):
    from PIL import Image

    from web import models, models_vao_bo

    db = data / "jobs.db"
    models.init_db(db)
    (data / "thumbs").mkdir(exist_ok=True)
    j = models.create_job(db, "https://x/a", 4, NGUOI, nen_tang="tiktok")
    drive = DriveGiaTL()
    drive.them_thu_muc(F1, "N.2809C - bộ thử")
    drive.them_thu_muc(DAU_RA, "Thay logo - đầu ra")
    nguon = []
    for i in range(1, 5):
        models.record_video(db, j, VID(i), f"https://x/{i}", title=f"Video {i}", drive_file_id=f"SRC{i}" + "x" * 12)
        Image.new("RGB", (90, 160), (60 + 30 * i, 120, 200 - 20 * i)).save(data / "thumbs" / f"{VID(i)}.webp", "WEBP")
        models_vao_bo.ghi_da_vao_bo(db, VID(i), NGUOI, [dict(ban_copy_id=BAN[i], folder_id=F1, ma_bo="N.2809C", bang_chung="properties")])
        drive.them_file(BAN[i], f"v{i}.mp4", F1, md5=f"MD5-{i}", size=str(100 * i))
        drive.them_file(RA[i], f"thay-logo-{i}.mp4", DAU_RA, md5=f"MD5-RA{i}", size=str(90 * i))
        nguon.append({"kieu": "vao_bo", "video_id": VID(i), "file_id": BAN[i], "folder_id": F1, "ma_bo": "N.2809C", "md5": f"MD5-{i}",
                      "size": str(100 * i), "ten": f"v{i}.mp4", "chu_video": NGUOI, "file_id_nguon": f"SRC{i}" + "x" * 12})
    # Bộ thứ hai (N.3010D, 2 video Đạt) cho ca "1 xong + 1 lùi": dựng trạng thái bằng hàm lõi thật trong test.
    drive.them_thu_muc(F2, "N.3010D - bộ thử 2")
    nguon2 = []
    for i in (5, 6):
        models.record_video(db, j, VID(i), f"https://x/{i}", title=f"Video {i}", drive_file_id=f"SRC{i}" + "x" * 12)
        Image.new("RGB", (90, 160), (40 * i % 255, 160, 90)).save(data / "thumbs" / f"{VID(i)}.webp", "WEBP")
        models_vao_bo.ghi_da_vao_bo(db, VID(i), NGUOI, [dict(ban_copy_id=BAN[i], folder_id=F2, ma_bo="N.3010D", bang_chung="properties")])
        drive.them_file(BAN[i], f"v{i}.mp4", F2, md5=f"MD5-{i}", size=str(100 * i))
        drive.them_file(RA[i], f"thay-logo-{i}.mp4", DAU_RA, md5=f"MD5-RA{i}", size=str(90 * i))
        nguon2.append({"kieu": "vao_bo", "video_id": VID(i), "file_id": BAN[i], "folder_id": F2, "ma_bo": "N.3010D", "md5": f"MD5-{i}",
                       "size": str(100 * i), "ten": f"v{i}.mp4", "chu_video": NGUOI, "file_id_nguon": f"SRC{i}" + "x" * 12})
    conn = nhat_ky.mo(data / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    j2 = hang_doi.tao_job(conn, NGUOI, nguon2, ten_bo="N.3010D")
    conn.execute("UPDATE tl_job SET thu_muc_ra_id=? WHERE id=?", (DAU_RA, j2))
    for i, (vid,) in zip((5, 6), conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (j2,)).fetchall()):
        log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
        nhat_ky.ghi_danh_gia(conn, log_id, NGUOI, "dat")
        hang_doi.dat(conn, vid, "xong", video_log_id=log_id, drive_file_id_ra=RA[i])
    _SAN["job2"] = j2
    jt = hang_doi.tao_job(conn, NGUOI, nguon, ten_bo="N.2809C")
    conn.execute("UPDATE tl_job SET thu_muc_ra_id=? WHERE id=?", (DAU_RA, jt))
    conn.commit()
    for i, (vid,) in enumerate(conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (jt,)).fetchall(), 1):
        log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
        nhat_ky.ghi_danh_gia(conn, log_id, NGUOI, DG[i], "khac" if DG[i] == "hong" else None)
        hang_doi.dat(conn, vid, "xong", video_log_id=log_id, drive_file_id_ra=RA[i])
    conn.close()
    return drive, jt


_SAN: dict = {}


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-thaylogo2a-"))
    drive, jt = _seed(tmp)
    _SAN.update(drive=drive, job=jt, tmp=tmp)
    cu = {k: getattr(app_mod, k) for k in ("DATA_DIR", "DB_PATH", "COOKIES_DIR", "worker_thay_logo")}
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


@pytest.fixture(autouse=True)
def tinh_nang_bat(may_chu, monkeypatch):
    log_db = _SAN["tmp"] / "thay_logo_log.db"

    def mo():
        conn = nhat_ky.mo(log_db)
        hang_doi.khoi_tao(conn)
        return conn
    monkeypatch.setenv(ap_vao_bo.ENV_BAT, "1")
    monkeypatch.setattr(app_mod, "worker_thay_logo", types.SimpleNamespace(
        drive_tl=_SAN["drive"], ly_do_khong_nhan=None, bat_dau_ap=lambda job_id: ap_vao_bo.chay_nen(mo, _SAN["drive"], job_id)))


@pytest.fixture
def trinh_duyet():
    pw_api = pytest.importorskip("playwright.sync_api")
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch(args=ARGS_CHAN_MANG)
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    yield br
    br.close()
    pw.stop()


def _mo(br, goc):
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    loi_js: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    mo_trang(p, f"{goc}/thay-logo.html", dem_mang_ngoai(ctx))
    p.wait_for_selector(f'.tl-bo-chon[data-job="{_SAN["job"]}"]')
    return p, loi_js


def _chup(p, ten):
    p.wait_for_function("[...document.images].every(i => i.complete)")
    d = os.environ.get("VIDEODL_ANH_THAY_LOGO")
    if d:
        Path(d).mkdir(parents=True, exist_ok=True)
        p.screenshot(path=str(Path(d) / ten), full_page=True)


def test_co_tat_thi_the_bo_khong_co_nut_ap(may_chu, trinh_duyet, monkeypatch):
    monkeypatch.delenv(ap_vao_bo.ENV_BAT)
    p, loi_js = _mo(trinh_duyet, may_chu)
    p.click(f'.tl-bo-chon[data-job="{_SAN["job"]}"]')
    p.wait_for_function(f"(async () => (await fetch('/api/thay-logo/bo/{_SAN['job']}/ap')).status === 404)()")
    p.wait_for_timeout(600)
    assert p.locator(".tl-bx-ap").count() == 0 and p.locator(".tl-bx").count() == 0
    assert loi_js == []


def test_lan_tai_dau_502_khong_ket_the_tu_thu_lai(may_chu, trinh_duyet):
    """Lần tải tiến độ ĐẦU trả 502 ⇒ không dựng khoá rỗng (từng làm thẻ kẹt + lỗi JS), tự thử lại và hiện nút.
    ĐỘT BIẾN: bỏ `delete apCua[jid]` / bỏ `if (!ap) return` ⇒ lỗi JS hoặc thẻ không bao giờ hiện ⇒ ĐỎ."""
    p, loi_js = _mo(trinh_duyet, may_chu)
    dem = {"502": 0}

    def chan(route):
        if route.request.method == "GET" and dem["502"] == 0:
            dem["502"] += 1
            route.fulfill(status=502, body="bad gateway")
        else:
            route.continue_()
    p.route("**/api/thay-logo/bo/*/ap", chan)
    p.click(f'.tl-bo-chon[data-job="{_SAN["job"]}"]')
    p.locator(".tl-bx-ap").wait_for(timeout=10000)
    assert dem["502"] == 1 and loi_js == []


def test_ap_roi_hoan_tac_tren_the_bo(may_chu, trinh_duyet):
    p, loi_js = _mo(trinh_duyet, may_chu)
    p.click(f'.tl-bo-chon[data-job="{_SAN["job"]}"]')
    nut = p.locator(".tl-bx-ap")
    nut.wait_for()
    assert nut.inner_text() == "Áp 3 video Đạt vào bộ N.2809C"
    chu = p.locator(".tl-bx").inner_text()
    assert "Hoàn tác KHÔNG lùi camp đã lên Meta." in chu and "Thay logo - bản gốc/N.2809C" in chu and "Chỉ video của bạn." in chu
    assert "vừa là người tạo lượt vừa là chủ video" in chu and "chủ video tự áp" not in chu
    p.wait_for_function("document.querySelectorAll('.tl-bx-thumbs img').length === 4")
    _chup(p, "2a-truoc-ap-1280.png")
    nut.click()
    p.locator(".tl-bx-da-ap").wait_for(timeout=15000)
    chu = p.locator(".tl-bx").inner_text()
    assert "Đã áp 3 video vào bộ" in chu and "Creative Desk vẫn dùng bản cũ tới lượt đồng bộ." in chu
    assert "Hoàn tác KHÔNG lùi camp đã lên Meta." in chu
    d = _SAN["drive"]
    assert all(F1 not in d.muc[BAN[i]]["parents"] for i in (1, 2, 3)) and F1 in d.muc[BAN[4]]["parents"]  # Hỏng ⇒ không thay
    assert "✓ Đã áp vào bộ" in p.locator(f'.tl-bo-chon[data-job="{_SAN["job"]}"]').inner_text()
    _chup(p, "2a-da-ap-1280.png")
    p.click(".tl-bx-da-ap .tl-bx-link")
    p.locator(".tl-bx-ap").wait_for(timeout=15000)
    assert all(d.muc[BAN[i]]["parents"] == [F1] for i in (1, 2, 3, 4))
    assert "đã hoàn tác một lần" in p.locator(".tl-bx").inner_text()
    assert loi_js == []


def test_bo_mot_xong_mot_lui_hien_nut_ap_lai(may_chu, trinh_duyet):
    """Bộ N.3010D: video 5 lùi (bản copy mang dấu nguồn), video 6 áp xong ⇒ thẻ có "Áp lại 1 video chưa vào bộ"; bấm ⇒ POST /ap ⇒ video 5
    vào bộ. ĐỘT BIẾN: bỏ nút "Áp lại" trong JS ⇒ ĐỎ."""
    d, j2 = _SAN["drive"], _SAN["job2"]
    log_db = _SAN["tmp"] / "thay_logo_log.db"
    d.copy_mang_properties = True
    d.muc[RA[5]]["properties"] = {"videodesk_src": "SRCX" + "x" * 12}
    conn = nhat_ky.mo(log_db)
    hang_doi.khoi_tao(conn)
    ap_vao_bo.dat_lich_ap(conn, j2, NGUOI, lambda ids: {i: (NGUOI, NGUOI) for i in ids})
    ap_vao_bo.chay_luot(conn, d, j2)
    ap_vao_bo.nha_khoa(conn, j2)
    assert [(r["chieu"], r["buoc"]) for r in conn.execute("SELECT chieu, buoc FROM tl_ap_bo WHERE job_id=? ORDER BY id", (j2,))] == \
        [("lui", "loi"), ("ap", "xong")]
    conn.close()
    del d.muc[RA[5]]["properties"]
    d.copy_mang_properties = False
    p, loi_js = _mo(trinh_duyet, may_chu)
    p.click(f'.tl-bo-chon[data-job="{j2}"]')
    nut = p.locator(".tl-bx-ap-lai")
    nut.wait_for()
    assert nut.inner_text() == "Áp lại 1 video chưa vào bộ" and "Đã áp 1 video vào bộ" in p.locator(".tl-bx").inner_text()
    p.wait_for_function("document.querySelectorAll('.tl-bx-thumbs img').length === 2")
    p.wait_for_function("[...document.images].every(i => i.complete)")
    thu_muc_anh = os.environ.get("VIDEODL_ANH_THAY_LOGO")  # cùng luật `_chup`: chỉ chụp khi có đặt thư mục, không ghi đường dẫn cứng
    if thu_muc_anh:
        Path(thu_muc_anh).mkdir(parents=True, exist_ok=True)
        p.locator(".tl-bx").screenshot(path=str(Path(thu_muc_anh) / "2a-mot-xong-mot-lui-1280.png"))
    with p.expect_request(lambda r: r.method == "POST" and r.url.endswith(f"/api/thay-logo/bo/{j2}/ap")):
        nut.click()
    p.wait_for_function("document.querySelector('.tl-bx-da-ap') && document.querySelector('.tl-bx-da-ap').textContent.includes('Đã áp 2 video')",
                        timeout=15000)
    assert F2 not in d.muc[BAN[5]]["parents"] and p.locator(".tl-bx-ap-lai").count() == 0 and loi_js == []
