"""Đợt 1b trên trình duyệt THẬT (Chromium, chặn mạng ngoài): hộp duyệt có vạch kéo so trước/sau + 2 ô phóng to vùng logo + fallback ảnh soi,
và tab "Đã vào bộ" (nhóm theo mã bộ, chọn cả bộ, tên bộ tự điền, POST gửi `vao_bo`, người khác không thấy). Test TẠO lượt đặt CUỐI file.

Ảnh chụp ghi vào `$VIDEODL_ANH_THAY_LOGO` nếu có đặt (1b-duyet-1280.png, 1b-da-vao-bo-1280.png)."""
from __future__ import annotations

import json
import os
import re
import socket
import tempfile
import threading
import time
import types
from pathlib import Path

import pytest
from drive_gia_thay_logo import DriveGiaTL

from tiktok_music_downloader.thay_logo import hang_doi, nhat_ky
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang
from web import app as app_mod

NGUOI, NGUOI_KHAC = "thaylogo@dev.local", "nguoikhac@dev.local"
F1, F2, F3 = "FOLDERBO1" + "f" * 12, "FOLDERBO2" + "g" * 12, "FOLDERBO9" + "h" * 12
BAN = {i: f"BANCOPY{i:04d}" + "q" * 10 for i in range(1, 6)}
BOX = {"x": 0.55, "y": 0.7, "w": 0.3, "h": 0.06}
VID = lambda i: f"7000000000000000{i}"  # noqa: E731 — id số như video thật (route /thumbs chỉ nhận id số)
TEN = {1: "Máy hút bụi cầm tay", 2: "Chảo chống dính 28cm", 3: "Kệ để giày gấp gọn", 4: "Nồi chiên không dầu", 5: "Video của người khác"}


def _anh(duong: Path, mau_o, rong=360, cao=640):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (rong, cao), (70, 90, 110))
    ImageDraw.Draw(im).rectangle([BOX["x"] * rong, BOX["y"] * cao, (BOX["x"] + BOX["w"]) * rong, (BOX["y"] + BOX["h"]) * cao], fill=mau_o)
    im.save(duong, "JPEG")


def _seed(data: Path) -> DriveGiaTL:
    from PIL import Image

    from web import models, models_vao_bo

    db = data / "jobs.db"
    models.init_db(db)
    (data / "thumbs").mkdir(exist_ok=True)
    j = models.create_job(db, "https://x/a", 4, NGUOI, nen_tang="tiktok")
    jk = models.create_job(db, "https://x/k", 1, NGUOI_KHAC, nen_tang="tiktok")
    for i in range(1, 6):
        models.record_video(db, j if i < 5 else jk, VID(i), f"https://x/{i}", title=TEN[i], drive_file_id=f"SRC{i}" + "x" * 12)
        Image.new("RGB", (90, 160), (60 + 30 * i, 120, 200 - 20 * i)).save(data / "thumbs" / f"{VID(i)}.webp", "WEBP")
    ban = lambda i, f, ma: dict(ban_copy_id=BAN[i], folder_id=f, ma_bo=ma, bang_chung="properties")  # noqa: E731
    luc = {"N.1AAAA": "2026-10-01T09:00:00+00:00", "N.2BBBB": "2026-09-28T09:00:00+00:00", "N.9OTHER": "2026-09-20T09:00:00+00:00"}
    for i, f, ma in ((1, F1, "N.1AAAA"), (2, F1, "N.1AAAA"), (3, F1, "N.1AAAA"), (4, F2, "N.2BBBB"), (5, F3, "N.9OTHER")):
        models_vao_bo.ghi_da_vao_bo(db, VID(i), None, [ban(i, f, ma)], luc=luc[ma])
    for k in (1, 2):  # hai video thư viện đã thay xong (nguồn của 2 video chờ duyệt bên dưới)
        models.record_video(db, j, f"LIB{k}", f"https://x/lib{k}", title=f"Video thư viện {k}", drive_file_id=f"LIB{k}" + "x" * 12)
    drive = DriveGiaTL()
    for f in (F1, F2, F3):
        drive.them_thu_muc(f, "bo")
    for i, f in ((1, F1), (2, F1), (3, F1), (4, F2), (5, F3)):
        drive.them_file(BAN[i], f"v{i}.mp4", f, md5=f"MD5-{i}", size=str(100 * i))
    # nhật ký: 2 video xong chờ duyệt — video "co_cap" có cặp trước/sau + box, video "chi_sheet" chỉ có ảnh soi — và VID4 đã nằm trong một lượt.
    conn = nhat_ky.mo(data / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    sheet = data / "sheet.jpg"
    _anh(sheet, (200, 200, 60), 400, 480)
    jt = hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": "LIB1" + "x" * 12}, {"kieu": "drive", "file_id": "LIB2" + "x" * 12}], ten_bo="Bộ thử")
    ids = [r[0] for r in conn.execute("SELECT id FROM tl_job_video WHERE job_id=? ORDER BY id", (jt,))]
    for k, vid in enumerate(ids):
        log_id = nhat_ky.bat_dau_video(conn, nguon_video="x")
        extra = {}
        if k == 1:  # video id lớn hơn ⇒ đứng đầu hàng duyệt
            _anh(data / "truoc.jpg", (220, 40, 40)); _anh(data / "sau.jpg", (40, 200, 90))
            extra = dict(duong_dan_truoc=str(data / "truoc.jpg"), duong_dan_sau=str(data / "sau.jpg"), box_logo=json.dumps(BOX))
        nhat_ky.cap_nhat_video(conn, log_id, duong_dan_sheet=str(sheet), **extra)
        conn.execute("INSERT INTO tl_vet (video_id, vet, trang_thai, pct_render) VALUES (?,?,?,?)", (log_id, 0, "render", 66.0))
        conn.commit()
        hang_doi.dat(conn, vid, "xong", video_log_id=log_id)
    hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": "SRC4" + "x" * 12}], ten_bo="Đang làm")
    # video máy không chắc (cho_nguoi): chỉ có ảnh TRƯỚC + box máy thấy
    jn = hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": "LIB1" + "x" * 12}], ten_bo="Không chắc")
    vn = conn.execute("SELECT id FROM tl_job_video WHERE job_id=?", (jn,)).fetchone()[0]
    ln = nhat_ky.bat_dau_video(conn, nguon_video="x")
    _anh(data / "truoc-n.jpg", (220, 40, 40))
    nhat_ky.cap_nhat_video(conn, ln, duong_dan_truoc=str(data / "truoc-n.jpg"), box_logo=json.dumps(BOX))
    hang_doi.dat(conn, vn, "cho_nguoi", video_log_id=ln)
    conn.close()
    return drive


_DRIVE: list = []


@pytest.fixture(autouse=True)
def tinh_nang_bat(may_chu, monkeypatch):
    """Tính năng BẬT: lifespan của app đặt `worker_thay_logo` = None lúc khởi động (không có THAY_LOGO_BAT) ⇒ gán lại SAU khi server đã chạy."""
    monkeypatch.setattr(app_mod, "worker_thay_logo", types.SimpleNamespace(drive_tl=_DRIVE[0], ly_do_khong_nhan=None))


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-thaylogo1b-"))
    drive = _seed(tmp)
    cu = {k: getattr(app_mod, k) for k in ("DATA_DIR", "DB_PATH", "COOKIES_DIR", "worker_thay_logo")}
    app_mod.DATA_DIR, app_mod.DB_PATH, app_mod.COOKIES_DIR = tmp, tmp / "jobs.db", tmp / "cookies"
    _DRIVE.append(drive)
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
    except Exception as exc:  # noqa: BLE001
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    yield br
    br.close()
    pw.stop()


def _mo(br, goc, rong=1280, truoc=None):
    ctx = br.new_context(viewport={"width": rong, "height": 900})
    if truoc:
        truoc(ctx)
    p = ctx.new_page()
    loi_js: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    mo_trang(p, f"{goc}/thay-logo.html", dem_mang_ngoai(ctx))
    p.wait_for_function("document.querySelector('#tl-duyet .tl-chi-tiet') && document.querySelectorAll('#tl-duyet .tl-phim-o').length === 2")
    return p, loi_js


def _chup(p, ten):
    p.wait_for_function("[...document.images].every(i => i.complete)")
    d = os.environ.get("VIDEODL_ANH_THAY_LOGO")
    if d:
        Path(d).mkdir(parents=True, exist_ok=True)
        p.screenshot(path=str(Path(d) / ten), full_page=True)


def _ti_le_vach(p) -> float:
    return p.evaluate("(() => { const c = document.querySelector('#tl-cmp').getBoundingClientRect(), v = document.querySelector('.tl-cmp-vach').getBoundingClientRect(); return (v.left + v.width / 2 - c.left) / c.width; })()")


# ---------------------------------------------------------------- hộp duyệt
def test_hop_duyet_co_vach_keo_doi_ti_le_hien_thi(may_chu, trinh_duyet):
    p, loi_js = _mo(trinh_duyet, may_chu)
    p.wait_for_selector("#tl-cmp")
    p.wait_for_function("[...document.querySelectorAll('#tl-cmp img')].every(i => i.complete && i.naturalWidth > 0)")
    assert p.locator("#tl-cmp img").count() == 2 and "TRƯỚC" in p.locator("#tl-cmp").inner_text() and "SAU" in p.locator("#tl-cmp").inner_text()
    assert abs(_ti_le_vach(p) - 0.5) < 0.01
    p.locator("#tl-truot").evaluate("r => { r.value = 25; r.dispatchEvent(new Event('input', { bubbles: true })); }")
    assert abs(_ti_le_vach(p) - 0.25) < 0.01
    p.keyboard.press("]")
    assert abs(_ti_le_vach(p) - 0.30) < 0.01
    p.keyboard.press("[")
    p.keyboard.press("[")
    assert abs(_ti_le_vach(p) - 0.20) < 0.01
    p.keyboard.down(" ")  # giữ Space = xem bản gốc (ảnh SAU bị che hết)
    assert abs(_ti_le_vach(p) - 1.0) < 0.01
    p.keyboard.up(" ")
    assert abs(_ti_le_vach(p) - 0.20) < 0.01
    # thật sự là hai ảnh KHÁC nhau: ảnh trước đỏ, ảnh sau xanh ở đúng vùng logo
    mau = p.evaluate("""async () => { const lay = async (u) => { const b = await (await fetch(u)).blob(), im = await createImageBitmap(b), c = document.createElement('canvas');
        c.width = im.width; c.height = im.height; const g = c.getContext('2d'); g.drawImage(im, 0, 0); return [...g.getImageData(Math.floor(im.width * 0.7), Math.floor(im.height * 0.73), 1, 1).data]; };
        const id = document.querySelector('#tl-cmp img').src.match(/videos\\/(\\d+)\\//)[1];
        return [await lay(`/api/thay-logo/videos/${id}/khung/truoc.jpg`), await lay(`/api/thay-logo/videos/${id}/khung/sau.jpg`)]; }""")
    assert mau[0][0] > 150 > mau[1][0] and mau[1][1] > 150 > mau[0][1]
    assert loi_js == []


def test_hai_o_phong_to_cat_dung_vung_logo(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    p.wait_for_function("document.querySelectorAll('.tl-zoom-o img:not([hidden])').length === 2")
    kq = p.evaluate("""(box) => [...document.querySelectorAll('.tl-zoom-o')].map(o => {
        const c = o.getBoundingClientRect(), r = o.querySelector('img').getBoundingClientRect();
        const cx = r.left - c.left + (box.x + box.w / 2) * r.width, cy = r.top - c.top + (box.y + box.h / 2) * r.height;
        return { cx: cx / c.width, cy: cy / c.height, bw: box.w * r.width / c.width, rong: c.width / c.height }; })""", BOX)
    for o in kq:  # tâm logo nằm giữa ô, logo chiếm phần đáng kể (phóng to thật), ô tỉ lệ 2:1
        assert 0.3 < o["cx"] < 0.7 and 0.3 < o["cy"] < 0.7 and 0.25 < o["bw"] < 0.8 and abs(o["rong"] - 2) < 0.05, o
    chu = p.locator(".tl-zoom-hop").inner_text()
    assert "Trước — logo cũ" in chu and "Sau — logo của bạn" in chu
    _chup(p, "1b-duyet-1280.png")


def test_khong_co_cap_anh_thi_roi_ve_anh_soi(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    p.locator(".tl-duyet-head .tl-nav").nth(1).click()  # › sang video chỉ có ảnh soi
    p.wait_for_function("!document.querySelector('#tl-cmp')")
    assert p.locator("#tl-duyet .tl-so-sanh img").get_attribute("src").endswith("/sheet.jpg") and p.locator(".tl-zoom-o").count() == 0
    assert "sắp có" not in p.locator("#tl-duyet").inner_text().lower()


def test_chu_member_thay_khong_co_chu_ky_su(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    chu = p.evaluate("document.body.innerText")
    assert not re.search(r"\b(agy|khung|box)\b", chu, re.I), re.findall(r"\b(?:agy|khung|box)\b", chu, re.I)
    p.locator("#tl-tabs [role=tab]").nth(1).click()
    p.wait_for_selector("#tl-tab-bo .tl-vb-nhom")
    chu = p.evaluate("document.body.innerText")
    assert not re.search(r"\b(agy|khung|box)\b", chu, re.I) and "đã được dọn" not in chu


# ---------------------------------------------------------------- tab Đã vào bộ
def _chon_ca(p, ma):
    return p.locator("#tl-tab-bo .tl-vb-nhom", has_text=ma).locator(".tl-vb-chon-ca")


def _tab_bo(p):
    p.locator("#tl-tabs [role=tab]").nth(1).click()
    p.wait_for_selector("#tl-tab-bo .tl-vb-nhom")


def test_tab_da_vao_bo_nhom_theo_ma_bo_chi_video_cua_minh(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    _tab_bo(p)
    nhom = " | ".join(t.replace("\n", " ") for t in p.locator("#tl-tab-bo .tl-vb-nhom").all_inner_texts())
    assert p.locator("#tl-tab-bo .tl-vb-nhom").count() == 2 and "Chọn cả bộ N.1AAAA (3 video)" in nhom and "Chọn cả bộ N.2BBBB (1 video)" in nhom
    chu = p.locator("#tl-tab-bo").inner_text()
    assert "Máy dùng bản trong bộ." in chu and TEN[1] in chu and TEN[5] not in chu and "N.9OTHER" not in chu  # video của người khác: không thấy
    mo = p.locator("#tl-tab-bo .tl-the-v.mo")  # VID4 đã nằm trong một lượt ⇒ mờ + không chọn được
    assert mo.count() == 1 and TEN[4] in mo.inner_text() and mo.locator("input").is_disabled()
    assert _chon_ca(p, "N.2BBBB").is_disabled()  # cả bộ đã nằm trong lượt ⇒ không còn gì để chọn
    _chon_ca(p, "N.1AAAA").click()  # ảnh nghiệm thu: đã chọn cả bộ ⇒ tên bộ tự điền
    p.locator("#tl-vung").evaluate("e => { e.scrollTop = 70; }")  # thẻ đầu hiện trọn, không bị cắt mép dưới
    _chup(p, "1b-da-vao-bo-1280.png")


def test_chon_cung_bo_tu_dien_ten_bo_va_dem(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    _tab_bo(p)
    _chon_ca(p, "N.1AAAA").click()
    assert p.locator("#tl-dem").inner_text() == "Đã chọn 3 video" and p.locator("#tl-ten-bo").input_value() == "N.1AAAA"
    assert _chon_ca(p, "N.1AAAA").get_attribute("aria-checked") == "true"
    p.locator("#tl-tab-bo .tl-the-v:not(.mo) input").first.uncheck()
    assert p.locator("#tl-dem").inner_text() == "Đã chọn 2 video" and _chon_ca(p, "N.1AAAA").get_attribute("aria-checked") == "mixed"
    _chon_ca(p, "N.1AAAA").click()  # từ trạng thái nửa chọn ⇒ chọn hết
    assert p.locator("#tl-dem").inner_text() == "Đã chọn 3 video"
    _chon_ca(p, "N.1AAAA").click()  # bấm lại ⇒ bỏ hết
    assert p.locator("#tl-dem").inner_text() == "Chưa chọn video nào" and p.locator("#tl-tao").is_disabled()


def _chon_bo_1(p):
    _tab_bo(p)
    _chon_ca(p, "N.1AAAA").click()


def _tra_loi_post(status, body):
    def xu(route):
        if route.request.method == "POST":
            route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
        else:
            route.continue_()
    return xu


@pytest.mark.parametrize("ma,body,mong", [
    (503, {"detail": "x"}, "Chưa hỏi được Drive lúc này — thử lại sau ít phút."),
    (422, {"detail": [{"loc": ["body"], "msg": "kỹ thuật"}]}, "Lượt quá lớn hoặc dữ liệu không hợp lệ."),
    (400, {"detail": "kỹ thuật"}, "Một số video trong bộ đã đổi hoặc không còn — tải lại danh sách."),
    (409, {"detail": "Một số video đã nằm trong một lượt thay logo khác — chọn video khác hoặc đợi lượt đó xong."},
     "Một số video đã nằm trong một lượt thay logo khác — chọn video khác hoặc đợi lượt đó xong."),
    (500, {}, "Chưa gửi được lượt này. Thử lại sau ít phút."),
])
def test_cau_loi_tao_luot_doc_detail_khong_hien_so_loi(may_chu, trinh_duyet, ma, body, mong):
    p, _ = _mo(trinh_duyet, may_chu)
    p.route("**/api/thay-logo/jobs", _tra_loi_post(ma, body))
    _chon_bo_1(p)
    p.locator("#tl-tao").click()
    p.wait_for_function("document.getElementById('tl-loi').innerText.length > 0")
    chu = p.locator("#tl-loi").inner_text()
    assert chu == mong and not re.search(r"\d{3}|lỗi \d", chu)


def test_400_vao_bo_xoa_lua_chon_va_tai_lai_tab(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    p.route("**/api/thay-logo/jobs", _tra_loi_post(400, {"detail": "x"}))
    _chon_bo_1(p)
    with p.expect_request(lambda r: r.url.endswith("/api/thay-logo/da-vao-bo")):
        p.locator("#tl-tao").click()
    p.wait_for_function("document.getElementById('tl-dem').innerText === 'Chưa chọn video nào'")
    p.wait_for_selector("#tl-tab-bo .tl-vb-nhom")  # danh sách tải lại xong


def test_hook_nem_loi_thi_bao_cau_thuong_va_khong_gui(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    goi = []
    p.on("request", lambda r: goi.append(r.url) if r.method == "POST" else None)
    _chon_bo_1(p)
    p.evaluate("window.TL_THAN_POST.push(() => { throw new Error('hook hỏng'); })")
    p.locator("#tl-tao").click()
    p.wait_for_function("document.getElementById('tl-loi').innerText.includes('Không gửi được lượt này')")
    assert "tải lại trang" in p.locator("#tl-loi").inner_text() and not [u for u in goi if u.endswith("/api/thay-logo/jobs")]
    assert p.locator("#tl-tao").is_enabled()  # không kẹt ở trạng thái đang gửi


def test_hook_khac_chay_truoc_thi_vao_bo_duoc_noi_them_khong_ghi_de(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    p.route("**/api/thay-logo/jobs", _tra_loi_post(201, {"job_id": 1}))
    _chon_bo_1(p)
    p.evaluate("window.TL_THAN_POST.unshift((than) => { than.vao_bo = [{ video_id: 'MODULE-KHAC', ban_copy_id: 'KHACKHACKHAC123' }]; })")
    with p.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/thay-logo/jobs")) as rq:
        p.locator("#tl-tao").click()
    vb = json.loads(rq.value.post_data)["vao_bo"]
    assert vb[0]["video_id"] == "MODULE-KHAC" and len(vb) == 4


def test_nhan_tab_da_vao_bo_dem_so_da_chon(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    _chon_bo_1(p)
    nhan = p.locator("#tl-tabs [role=tab]").nth(1)
    assert nhan.inner_text().split() == ["Đã", "vào", "bộ", "3"]
    p.locator("#tl-tab-bo .tl-the-v:not(.mo) input").first.uncheck()
    assert nhan.inner_text().split()[-1] == "2"


def test_space_va_ngoac_vuong_khong_bi_cuop_khi_focus_ngoai_hop_duyet(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    p.wait_for_selector("#tl-cmp")
    p.locator("#tl-vung").focus()  # vùng cuộn của khối nhập (tabindex=0): Space ở đây là của nó
    p.keyboard.down(" ")
    assert abs(_ti_le_vach(p) - 0.5) < 0.01
    p.keyboard.up(" ")
    p.keyboard.press("]")
    assert abs(_ti_le_vach(p) - 0.5) < 0.01
    p.evaluate("document.activeElement.blur()")  # không focus ở đâu ⇒ hộp duyệt nhận phím
    p.keyboard.press("BracketRight")
    assert abs(_ti_le_vach(p) - 0.55) < 0.01


def test_anh_cho_nguoi_hien_anh_truoc_don_o_cot_phai(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu)
    p.wait_for_selector("#tl-khong-chac img.tl-truoc-nho")
    p.wait_for_function("document.querySelector('#tl-khong-chac img.tl-truoc-nho').naturalWidth > 0")
    assert p.locator("#tl-khong-chac .tl-cmp").count() == 0  # ảnh đơn, không vạch


def test_anh_sau_khong_tai_duoc_thi_roi_ve_anh_soi(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, truoc=lambda ctx: ctx.route("**/khung/sau.jpg", lambda r: r.abort()))
    p.wait_for_function("!document.querySelector('#tl-cmp') && document.querySelector('#tl-duyet .tl-so-sanh img')")
    assert p.locator("#tl-duyet .tl-so-sanh img").get_attribute("src").endswith("/sheet.jpg") and p.locator(".tl-zoom-o").count() == 0


def test_danh_sach_da_vao_bo_bi_cat_thi_bao(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, truoc=lambda ctx: ctx.route("**/api/thay-logo/da-vao-bo", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps({"bo": [], "bi_cat": True}))))
    _tab_bo_trong = p.locator("#tl-tabs [role=tab]").nth(1)
    _tab_bo_trong.click()
    p.wait_for_function("document.getElementById('tl-tab-bo').innerText.includes('chỉ hiện các video vào bộ gần đây')")


def test_zzz_tao_luot_tu_tab_gui_dung_vao_bo(may_chu, trinh_duyet):
    """CUỐI file: tạo một lượt thật (bản giả của Drive) — kiểm thân POST và ảnh chụp nguồn trong nhật ký."""
    p, _ = _mo(trinh_duyet, may_chu)
    _tab_bo(p)
    _chon_ca(p, "N.1AAAA").click()
    with p.expect_request(lambda r: r.method == "POST" and r.url.endswith("/api/thay-logo/jobs")) as rq:
        p.locator("#tl-tao").click()
    body = json.loads(rq.value.post_data)
    assert body["drive_file_ids"] == [] and body["ten_bo"] == "N.1AAAA"
    assert sorted(body["vao_bo"], key=lambda m: m["ban_copy_id"]) == [{"video_id": VID(i), "ban_copy_id": BAN[i]} for i in (1, 2, 3)]
    p.wait_for_function("document.getElementById('tl-dem').innerText === 'Chưa chọn video nào'")
    conn = nhat_ky.mo(app_mod.DATA_DIR / "thay_logo_log.db")
    nguon = [json.loads(r[0]) for r in conn.execute("SELECT v.nguon FROM tl_job_video v JOIN tl_job j ON j.id=v.job_id WHERE j.ten_bo='N.1AAAA' ORDER BY v.id")]
    assert sorted((n["kieu"], n["file_id"], n["folder_id"], n["ma_bo"], n["md5"], n["size"]) for n in nguon) == \
        [("vao_bo", BAN[i], F1, "N.1AAAA", f"MD5-{i}", str(100 * i)) for i in (1, 2, 3)]
    # tab mở lại: 3 video vừa tạo lượt giờ mờ (đã trong lượt), không chọn lại được
    _tab_bo(p)
    p.wait_for_function("document.querySelectorAll('#tl-tab-bo .tl-the-v.mo').length === 4")
    assert _chon_ca(p, "N.1AAAA").is_disabled()


def test_khong_con_cho_nao_boc_window_fetch():
    """Thân POST do hook chính thức `TL_THAN_POST` sửa, không bọc `fetch` toàn trang."""
    for f in Path(app_mod.STATIC_DIR).glob("thay-logo*.js"):
        assert not re.search(r"window\.fetch\s*=|fetch\s*=\s*function", f.read_text()), f.name
