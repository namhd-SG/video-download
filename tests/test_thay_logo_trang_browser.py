"""Trang Thay logo (khung theo bộ, mock v4a) trên trình duyệt THẬT (Chromium, chặn mạng ngoài): bốn vùng dựng đủ, thu gọn/mở khối nhập,
tính năng tắt, lọc trạng thái, Đạt/Hỏng sát nhau + lý do chỉ hiện sau khi bấm Hỏng, không cuộn ngang, link trên thanh trên.

Đợt nối API: tên bộ gửi lên khi tạo lượt, thẻ bộ đọc /bo và bấm lọc, lọc nền tảng/ngày, tên video + ảnh bìa, lời lỗi thường, và
KHÔNG còn chữ kỹ sư (agy / khung / box) trong văn bản member thấy. Các test TẠO lượt đặt CUỐI file (chúng thêm một bộ vào DB dùng chung).

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
TEN_BO_A, TEN_BO_B = "Quay T10 - đồ bếp", "Bộ cũ 3 ngày"
TIEU_DE = ["Máy hút bụi cầm tay", "Chảo chống dính 28cm", "Kệ để giày gấp gọn", "Nồi chiên không dầu"]
FILE_THU_VIEN = [f"FILE{i:02d}" + "x" * 12 for i in range(20, 28)]  # video trong thư viện chưa vào lượt nào (để test tạo lượt)


def _seed_thu_vien(data: Path) -> None:
    """jobs.db: thư viện của NGƯỜI (tiktok: FILE00-03 + FILE20-27, douyin: FILE10-11) kèm ảnh bìa; FILE04 CỐ Ý không có (video đã mất)."""
    from PIL import Image

    from web import models

    db = data / "jobs.db"
    models.init_db(db)
    (data / "thumbs").mkdir(exist_ok=True)
    tiktok, douyin = models.create_job(db, "https://x/a", 20, NGUOI, nen_tang="tiktok"), models.create_job(db, "https://x/b", 2, NGUOI, nen_tang="douyin")
    muc = [(tiktok, f"FILE{i:02d}" + "x" * 12, TIEU_DE[i]) for i in range(4)] + [(douyin, f"FILE{i:02d}" + "x" * 12, f"Son kem lì {i}") for i in (10, 11)]
    muc += [(tiktok, f, f"Video thư viện {k}") for k, f in enumerate(FILE_THU_VIEN)]
    for k, (job, fid, tieu_de) in enumerate(muc):
        vid = f"70000000000000{k:05d}"
        models.record_video(db, job, vid, f"https://x/{vid}", title=tieu_de, drive_file_id=fid)
        Image.new("RGB", (90, 160), (60 + 12 * k % 190, 120, 200 - 9 * k % 150)).save(data / "thumbs" / f"{vid}.webp", "WEBP")


def _seed(data: Path) -> None:
    conn = nhat_ky.mo(data / "thay_logo_log.db")
    hang_doi.khoi_tao(conn)
    j = hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": f"FILE{i:02d}" + "x" * 12} for i in range(5)], ten_bo=TEN_BO_A)
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
    # Bộ thứ hai: tạo cách đây 3 ngày, nền tảng douyin, 2 video máy đang xếp hàng, đã có thư mục đầu ra.
    j2 = hang_doi.tao_job(conn, NGUOI, [{"kieu": "drive", "file_id": f"FILE{i:02d}" + "x" * 12} for i in (10, 11)], ten_bo=TEN_BO_B)
    conn.execute("UPDATE tl_job SET tao_luc = ?, thu_muc_ra_id = ? WHERE id = ?", (time.time() - 3 * 86400, "THUMUC" + "z" * 14, j2))
    conn.commit()
    conn.close()
    _seed_thu_vien(data)


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
    # bộ A: 2 video xong chưa đánh giá ⇒ hộp duyệt; 1 máy đang làm; 1 không chắc; 1 lỗi. Bộ B: 2 video xếp hàng (+2 máy đang làm)
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 3 && document.querySelector('#tl-duyet .tl-chi-tiet') && document.querySelectorAll('#tl-bo-list .tl-bo-the').length === 2")
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
    assert p.locator("#tl-bo-list .tl-bo-the").count() == 2 and TEN_BO_A in p.locator("#tl-bo-list").inner_text()
    assert p.locator("#tl-loc").is_visible() and p.locator("#tl-loc [data-tt]").count() == 6
    assert p.locator("#tl-duyet").is_visible() and "Chờ bạn duyệt" in p.locator("#tl-duyet").inner_text()
    chu = p.locator("aside.tl-cot").inner_text()
    assert "Máy đang làm" in chu and "Máy không chắc" in chu and "Không làm được" in chu and "Hết chỗ đĩa" in chu
    # 5 video: 2 xong chờ duyệt (1 cờ soi kỹ), 1 chờ agy, 1 không chắc, 1 lỗi
    assert "2 video chờ duyệt" in p.locator("#tl-tom-tat").inner_text() and "1 cần bạn xem kỹ" in p.locator("#tl-tom-tat").inner_text()
    assert "Máy đang tìm chỗ logo cũ · đã 14 phút" in p.locator("#tl-dang-lam").inner_text()
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
    p.wait_for_function("document.getElementById('tl-ten-bo').disabled")
    assert p.locator("#tl-tao").is_disabled()


def test_loc_trang_thai_thu_hep_cot_phai(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    p.locator("#tl-loc [data-tt=loi]").click()
    assert p.locator("#tl-khong-lam .tl-muc").count() == 1 and p.locator("#tl-dang-lam .tl-muc").count() == 0
    assert "Video không còn trong thư viện" in p.locator("#tl-khong-lam").inner_text()  # FILE04 cố ý không có trong thư viện
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


def test_bam_dat_ghi_danh_gia(may_chu, trinh_duyet, monkeypatch):
    p = _mo_bat(trinh_duyet, may_chu, monkeypatch)  # tính năng tắt thì nút Đạt bị khoá như phím D
    p.wait_for_selector("#tl-duyet .tl-dat:enabled")
    p.locator(".tl-dat").click()
    p.wait_for_function("document.querySelector('#tl-loc [data-tt=da_dat]').innerText.includes('1')")
    conn = nhat_ky.mo(app_mod.DATA_DIR / "thay_logo_log.db")
    assert [tuple(r) for r in conn.execute("SELECT member, ket_qua FROM tl_danh_gia")] == [(NGUOI, "dat")]


# ---------------------------------------------------------------- nối API bộ / lọc / tên video

def _chu_trang(p) -> str:
    return p.evaluate("document.body.innerText + ' ' + [...document.querySelectorAll('[title],[aria-label],[placeholder]')].map(e => (e.title||'') + ' ' + (e.getAttribute('aria-label')||'') + ' ' + (e.placeholder||'')).join(' ')")


def test_the_bo_doc_bo_va_bam_loc_theo_bo(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    the_a = p.locator(".tl-bo-the", has_text=TEN_BO_A)
    chu = the_a.inner_text()
    assert "Thư viện" in chu and "5 video" in chu and "2/5 xong" in chu and __import__("re").search(r"\d cần bạn xem", chu) and "1 máy không chắc" in chu and "1 lỗi" in chu
    assert "Đang xử lý" in chu
    the_b = p.locator(".tl-bo-the", has_text=TEN_BO_B)
    assert "0/2 xong" in the_b.inner_text()
    link = the_b.locator("a.tl-bo-thumuc")  # bộ A chưa có thư mục đầu ra ⇒ không có link; bộ B có
    assert link.get_attribute("href") == "https://drive.google.com/drive/folders/THUMUC" + "z" * 14 and the_a.locator("a").count() == 0
    with p.expect_request(lambda r: "/api/thay-logo/videos" in r.url and "job_id=" in r.url):
        the_b.locator("button.tl-bo-chon").click()
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 2 && document.querySelectorAll('#tl-khong-lam .tl-muc').length === 0")
    assert "Không có video nào chờ" in p.locator("#tl-duyet").inner_text()
    assert p.locator("#tl-loc-bo").input_value() != ""  # ô chọn bộ đi theo thẻ
    p.locator(".tl-bo-the", has_text=TEN_BO_B).locator("button.tl-bo-chon").click()  # bấm lại = bỏ lọc
    p.wait_for_function("document.querySelectorAll('#tl-khong-lam .tl-muc').length === 1")


def test_thu_muc_dau_ra_va_trang_thai_bo_theo_du_lieu_bo(may_chu, trinh_duyet):
    """Ba trạng thái bộ + tiến độ + link thư mục, dựng từ JSON /bo cố định (bộ thật chỉ có ca Đang xử lý)."""
    import json

    def bo(job_id, ten, tong, xong, cho_duyet, thu_muc=None, cho_nguoi=0):
        return {"job_id": job_id, "ten_bo": ten, "nguon_kieu": "drive", "tao_luc": time.time(), "tong": tong, "xong": xong, "cho_duyet": cho_duyet,
                "cho_nguoi": cho_nguoi, "loi": 0, "dat": xong - cho_duyet, "hong": 0, "thu_muc_ra_id": thu_muc}

    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    tra = json.dumps({"bo": [bo(3, "Bộ ba", 6, 6, 0, "ABCDEFGHIJK"), bo(2, "Bộ hai", 6, 6, 5), bo(1, "Bộ một", 30, 12, 2)]})
    p.route("**/api/thay-logo/bo", lambda r: r.fulfill(status=200, content_type="application/json", body=tra))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('.tl-bo-the').length === 3")
    t = {n: p.locator(".tl-bo-the", has_text=n).inner_text() for n in ("Bộ một", "Bộ hai", "Bộ ba")}
    assert "Đang xử lý" in t["Bộ một"] and "12/30 xong" in t["Bộ một"] and "2 cần bạn xem" in t["Bộ một"]
    assert "Chờ bạn duyệt" in t["Bộ hai"] and "5 cần bạn xem" in t["Bộ hai"]
    assert "Xong" in t["Bộ ba"] and "6/6 xong" in t["Bộ ba"] and "cần bạn xem" not in t["Bộ ba"]
    assert p.locator(".tl-bo-the", has_text="Bộ ba").locator("a").get_attribute("href") == "https://drive.google.com/drive/folders/ABCDEFGHIJK"
    assert p.locator(".tl-bo-the a").count() == 1
    assert not p.locator("text=/Áp vào bộ|Đẩy lên bộ/").count()  # nút của đợt sau: không hiện


def test_loc_nen_tang_va_ngay_goi_api_that(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    with p.expect_request(lambda r: "nen_tang=douyin" in r.url):
        p.locator("#tl-loc [data-nen=douyin]").click()
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 2 && document.querySelectorAll('#tl-khong-lam .tl-muc').length === 0")
    assert "Son kem lì 10" in p.locator("#tl-dang-lam").inner_text()
    p.locator("#tl-loc [data-nen=tiktok]").click()
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 1")
    assert "Son kem lì" not in p.locator("#tl-dang-lam").inner_text()
    p.locator("#tl-loc [data-nen='']").click()
    with p.expect_request(lambda r: "tu=" in r.url):
        p.locator("#tl-loc [data-ngay=hom_nay]").click()  # bộ B tạo cách đây 3 ngày ⇒ rơi khỏi "Hôm nay"
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 1")
    p.locator("#tl-loc [data-ngay='']").click()
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 3")


def test_hien_ten_video_chip_bo_va_anh_bia(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    p.wait_for_function("[...document.images].every(i => i.complete)")
    duyet = p.locator("#tl-duyet").inner_text()
    assert any(t in duyet for t in TIEU_DE[:2]) and TEN_BO_A in duyet  # chip bộ trong hộp duyệt
    assert not __import__("re").search(r"FILE0\d", _chu_trang(p)), "không còn mã file thô"
    cot = p.locator("#tl-dang-lam").inner_text()
    assert TIEU_DE[2] in cot and TEN_BO_A in cot and TEN_BO_B in cot
    assert p.locator("#tl-duyet img.tl-bia-nho").evaluate("i => i.naturalWidth > 0")  # ảnh bìa tải được từ /thumbs
    assert p.locator("#tl-dang-lam img.tl-bia-nho").first.evaluate("i => i.naturalWidth > 0")
    assert "Video không còn trong thư viện" in p.locator("#tl-khong-lam").inner_text()


def test_thu_vien_loi_bao_mot_dong_va_an_ten(may_chu, trinh_duyet):
    import json

    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    dong = {"id": 9, "job_id": 1, "nguon": json.dumps({"kieu": "drive", "file_id": "F" * 20}), "trang_thai": "cho_nguoi", "ten_bo": "Bộ lỗi", "ten_video": None,
            "anh_bia": None, "nen_tang": None, "so_box": 0, "danh_gia": None, "co_sheet": 0}
    body = json.dumps({"videos": [dong], "con_nua": False, "truoc_tiep": None, "thu_vien_loi": True})
    p.route("**/api/thay-logo/videos*", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('#tl-khong-chac .tl-muc').length === 1")
    assert "Không đọc được thư viện — tên video tạm ẩn." in p.locator("#tl-loc").inner_text()
    chu = p.locator("#tl-khong-chac").inner_text()
    assert "Tên video tạm ẩn" in chu and "Video không còn trong thư viện" not in chu  # đừng nói dối "đã mất" khi chỉ là không đọc được
    assert "Máy không thấy logo" in chu


def test_con_nua_dung_truoc_tiep(may_chu, trinh_duyet):
    import json

    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    goi: list[str] = []

    def dong(i):
        return {"id": i, "job_id": 1, "nguon": json.dumps({"kieu": "drive", "file_id": "F" * 20}), "trang_thai": "cho", "ten_bo": "Bộ phân trang", "ten_video": f"Video số {i}",
                "anh_bia": None, "nen_tang": "tiktok", "so_box": 0, "danh_gia": None, "co_sheet": 0}

    def tra(r):
        goi.append(r.request.url)
        trang1 = "truoc_id" not in r.request.url
        r.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"videos": [dong(80)] if trang1 else [dong(70)], "con_nua": trang1, "truoc_tiep": 80 if trang1 else None, "thu_vien_loi": False}))

    p.route("**/api/thay-logo/videos*", tra)
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 1")
    p.locator(".tl-xem-them").click()
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 2")
    assert any("truoc_id=80" in u for u in goi) and p.locator(".tl-xem-them").count() == 0


def test_khong_con_chu_ky_su_trong_van_ban_member_thay(may_chu, trinh_duyet):
    import re

    p, _ = _mo(trinh_duyet, may_chu, 1280)
    p.wait_for_function("document.querySelector('#tl-duyet .tl-phu')")
    p.locator(".tl-hong-nut").click()
    for tab in range(4):
        p.locator("#tl-tabs [role=tab]").nth(tab).click()
        bat = re.findall(r"agy|khung|box|%\s*khung", _chu_trang(p).lower())
        assert bat == [], f"chữ kỹ sư còn trên trang (tab {tab}): {bat}"
    phu = p.locator("#tl-duyet .tl-phu").inner_text()  # video nào còn trong hàng tuỳ thứ tự test trước: 97% ⇒ "gần như cả video", 66% ⇒ "khoảng 2/3"
    assert "Logo mới có ở" in phu and ("khoảng" in phu or "gần như cả video" in phu) and "%" not in phu
    assert "Máy không thấy logo" in p.locator("#tl-khong-chac").inner_text()


@pytest.mark.parametrize("pct,mong", [(97, "gần như cả video"), (66, "khoảng 2/3 video"), (50, "khoảng 1/2 video"), (25, "khoảng 1/4 video"), (40, "khoảng 2/5 video"), (3, "rất ít video")])
def test_pct_render_doi_ra_phan_so(may_chu, trinh_duyet, pct, mong):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    assert p.evaluate(f"window.TL.phanSo({pct})") == mong


def test_cho_gan_nguon_nhap_cua_dot_sau(may_chu, trinh_duyet):
    """Module đăng ký vào TL_TAB_NGUON được vẽ vào container riêng của tab; tab chưa có module vẫn 'Sắp có'."""
    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    p.add_init_script("window.TL_TAB_NGUON = [{ id: 'link', giai: 'Giải thích của module', ve(hop, T) { hop.append(T.el('p', 'x', 'MODULE-LINK-DA-VE')); } }];")
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('#tl-tabs [role=tab]').length === 4")
    p.locator("#tl-tabs [role=tab]").nth(3).click()
    assert "MODULE-LINK-DA-VE" in p.locator("#tl-tab-link").inner_text() and p.locator("#tl-tab-thu-vien").is_hidden()
    assert "Giải thích của module" in p.locator("#tl-tab-giai").inner_text()
    p.locator("#tl-tabs [role=tab]").nth(2).click()
    assert "Sắp có" in p.locator("#tl-tab-may").inner_text() and p.locator("#tl-tab-link").is_hidden()


# ---------------------------------------------------------------- sửa gom lượt cuối: đánh giá trùng, lớp chắn lời lỗi, lỗi tải, race lọc, CSS, XSS
# Các test dưới đây dựng JSON /bo và /videos giả bằng `page.route` (không đụng DB dùng chung ⇒ không lệch các test đếm ở trên).

def _dong_mo(i, **kw):
    import json
    d = {"id": i, "job_id": 1, "nguon": json.dumps({"kieu": "drive", "file_id": "F" * 20}), "trang_thai": "xong", "ten_bo": "Bộ thử",
         "ten_video": f"Video số {i}", "anh_bia": None, "nen_tang": "tiktok", "so_box": 0, "danh_gia": None, "co_sheet": 0, "can_soi_ky": 0,
         "drive_file_id_ra": None, "loi_text": None, "pct_render": None, "giay_xu_ly": None}
    d.update(kw)
    return d


def _bo_mo(job_id, ten, tong=2, xong=0, cho_duyet=0):
    return {"job_id": job_id, "ten_bo": ten, "nguon_kieu": "drive", "tao_luc": time.time(), "tong": tong, "xong": xong, "cho_duyet": cho_duyet,
            "cho_nguoi": 0, "loi": 0, "dat": 0, "hong": 0, "thu_muc_ra_id": None}


def _tra_json(r, body, status=200):
    import json
    r.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def _trang_gia(br, goc, monkeypatch, videos, bo=None, bat=True):
    """Trang mở với /bo và /videos do `videos()` (hàm nhận route) trả; tính năng bật (nút Đạt/phím D dùng được)."""
    monkeypatch.setattr(app_mod, "worker_thay_logo", object() if bat else None)
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    p.route("**/api/thay-logo/bo", lambda r: _tra_json(r, {"bo": bo if bo is not None else [_bo_mo(1, "Bộ thử")]}))
    p.route("**/api/thay-logo/videos*", videos)
    return p


def _danh_sach(ds, **thua):
    return {"videos": ds, "con_nua": False, "truoc_tiep": None, "thu_vien_loi": False, **thua}


def test_danh_gia_khong_gui_trung_khi_dang_gui_phim_va_nut(may_chu, trinh_duyet, monkeypatch):
    """Gõ D hai lần nhanh / bấm đúp nút: chỉ MỘT lượt gửi cho video đang hiện, không có hai dòng đánh giá cùng video; xong thì video bị bỏ
    khỏi hàng chờ ngay và phím D kế tiếp chấm video KẾ. ĐỘT BIẾN: bỏ `if (dangDanhGia) return;` ⇒ ĐỎ."""
    import re
    da, posts, giu = {}, [], []
    dong = [_dong_mo(i) for i in (11, 12, 13)]
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach([dict(d, danh_gia=da.get(d["id"])) for d in dong])))

    def danh_gia(r):
        vid = int(re.search(r"/videos/(\d+)/danh-gia", r.request.url).group(1))
        posts.append(vid)
        giu.append((vid, r))  # giữ phản hồi: đang "gửi"
    p.route("**/api/thay-logo/videos/*/danh-gia", danh_gia)
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelector('#tl-duyet .tl-dem') && document.querySelector('#tl-duyet .tl-dem').textContent === '1 / 3' && !document.querySelector('.tl-dat').disabled")
    p.keyboard.press("d")
    p.keyboard.press("d")
    p.wait_for_timeout(400)
    assert posts == [11], f"phím D lặp khi đang gửi phải bị chặn: {posts}"

    def tra_loi_het():
        while giu:
            vid, r = giu.pop(0)
            da[vid] = "dat"
            r.fulfill(status=204)
    tra_loi_het()
    p.wait_for_function("document.querySelector('#tl-duyet .tl-dem').textContent === '1 / 2'")  # 11 đã rời hàng chờ
    assert "Video số 11" not in p.locator("#tl-duyet").inner_text()
    p.keyboard.press("d")
    p.wait_for_timeout(200)
    assert posts == [11, 12]
    p.locator(".tl-dat").dblclick()  # chuột cũng không gửi trùng
    p.wait_for_timeout(300)
    assert posts == [11, 12], posts
    tra_loi_het()
    p.wait_for_function("document.querySelector('#tl-duyet .tl-dem').textContent === '1 / 1'")
    p.keyboard.press("d")
    p.wait_for_timeout(200)
    tra_loi_het()
    p.wait_for_function("document.querySelector('#tl-duyet .tl-rong')")
    assert posts == [11, 12, 13] and len(set(posts)) == len(posts)


def test_video_da_cham_roi_hang_cho_ngay_va_phan_hoi_tai_cu_khong_dua_no_ve(may_chu, trinh_duyet, monkeypatch):
    """(1) Chấm xong video rời hàng chờ NGAY, không đợi lượt tải lại (lượt tải lại bị giữ). (2) Máy chủ (hoặc phản hồi đã bay trước lúc
    chấm) vẫn trả video chưa có đánh giá ⇒ trang giữ kết quả vừa chấm. ĐỘT BIẾN: bỏ đoạn đánh dấu ngay ở `danhGia` ⇒ (1) ĐỎ;
    bỏ dòng ghép `T.daCham` trong `taiLai` ⇒ (2) ĐỎ."""
    dong = [_dong_mo(71), _dong_mo(72)]
    giu = []
    che_do = {"giu": False}

    def videos(r):
        if che_do["giu"]:
            giu.append(r)
        else:
            _tra_json(r, _danh_sach(dong))  # luôn danh_gia = None
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, videos)
    p.route("**/api/thay-logo/videos/*/danh-gia", lambda r: r.fulfill(status=204))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelector('#tl-duyet .tl-dem') && document.querySelector('#tl-duyet .tl-dem').textContent === '1 / 2' && !document.querySelector('.tl-dat').disabled")
    che_do["giu"] = True
    p.locator(".tl-dat").click()
    p.wait_for_function("document.querySelector('#tl-duyet .tl-dem').textContent === '1 / 1'", timeout=3000)  # lượt tải lại đang bị giữ
    while not giu:
        p.wait_for_timeout(50)
    for r in giu:
        _tra_json(r, _danh_sach(dong))  # máy chủ chưa phản ánh đánh giá
    p.wait_for_timeout(500)
    assert p.locator("#tl-duyet .tl-dem").inner_text() == "1 / 1" and "Video số 71" not in p.locator("#tl-duyet").inner_text()


@pytest.mark.parametrize("cach", ["mang", 500, 409])
def test_danh_gia_loi_noi_cau_thuong_va_gui_lai_duoc(may_chu, trinh_duyet, monkeypatch, cach):
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach([_dong_mo(21), _dong_mo(22)])))
    chay = {"loi": True}

    def danh_gia(r):
        if not chay["loi"]:
            r.fulfill(status=204)
        elif cach == "mang":
            r.abort()
        else:
            _tra_json(r, {"detail": "raw detail"}, cach)
    p.route("**/api/thay-logo/videos/*/danh-gia", danh_gia)
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelector('.tl-dat') && !document.querySelector('.tl-dat').disabled")
    p.locator(".tl-dat").click()
    p.wait_for_function("document.getElementById('tl-loi').textContent.length > 0")
    chu = p.locator("#tl-loi").inner_text()
    assert "raw detail" not in chu and "Error" not in chu and str(cach) not in chu
    assert "Video số 21" in p.locator("#tl-duyet").inner_text()  # lỗi ⇒ video vẫn ở hàng chờ
    chay["loi"] = False
    p.locator(".tl-dat").click()  # cờ đang-gửi đã nhả ⇒ gửi lại được
    p.wait_for_function("document.querySelector('#tl-duyet .tl-dem').textContent === '1 / 1'")
    assert p.locator("#tl-loi").inner_text() == ""


def test_hang_cu_co_loi_text_ky_su_hien_cau_thuong(may_chu, trinh_duyet, monkeypatch):
    """Lớp chắn FE cho hàng cũ trong DB. ĐỘT BIẾN: bỏ `T.loiText(...)` ở cột "Không làm được" ⇒ ĐỎ."""
    cu = ["Không đọc được khung nào.", "Không tải được video nguồn (HttpError).", "Quá trần thời gian xử lý (120s).", "Không chạy tiếp được (KeyError)."]
    ds = [_dong_mo(30 + i, trang_thai="loi", loi_text=t) for i, t in enumerate(cu)] + [_dong_mo(40, trang_thai="loi", loi_text="Hết chỗ đĩa khi ghi video ra."),
                                                                                   _dong_mo(41, trang_thai="loi", loi_text=None)]
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach(ds)))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('#tl-khong-lam .tl-muc').length === 6")
    chu = p.locator("#tl-khong-lam").inner_text()
    assert chu.count("Máy gặp lỗi khi xử lý video này.") == 4
    for cam in ("khung", "HttpError", "120s", "KeyError"):
        assert cam not in chu
    assert "Hết chỗ đĩa khi ghi video ra." in chu and "Lỗi không rõ" in chu  # câu thường giữ nguyên
    assert ". —" not in chu  # mỗi thẻ là một câu; "video gốc không bị ảnh hưởng" đã ở tiêu đề khối


def test_hop_duyet_canh_bao_nen_xem_ky_chi_hien_cho_video_can_soi(may_chu, trinh_duyet, monkeypatch):
    """ĐỘT BIẾN: xoá dòng `if (T.soiKy(v)) {…}` ở hộp duyệt ⇒ ĐỎ; luôn hiện ⇒ ĐỎ ở video thứ hai."""
    ds = [_dong_mo(51, can_soi_ky=1, ten_video="Video cần soi"), _dong_mo(52, ten_video="Video thường")]
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach(ds)))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelector('#tl-duyet h3')")
    assert "Video cần soi" in p.locator("#tl-duyet h3").inner_text()
    assert p.locator(".tl-canh-bao").is_visible() and "Nên xem kỹ" in p.locator(".tl-canh-bao").inner_text()
    p.locator(".tl-nav").nth(1).click()  # › video kế
    assert "Video thường" in p.locator("#tl-duyet h3").inner_text()
    assert p.locator(".tl-canh-bao").count() == 0


def test_o_nhap_ban_toi_dung_mau_app(may_chu, trinh_duyet):
    """ĐP-1519: ô nhập bản tối từng hiện nền xám mặc định của trình duyệt. Ô của form/bộ lọc/ghi chú Hỏng = nền app (--bg);
    ô tìm trong thanh công cụ nằm trên nền --bg nên theo mock dùng --surface. ĐỘT BIẾN: bỏ `background: var(--bg)` ở luật ô nhập ⇒ ĐỎ."""
    p, _ = _mo(trinh_duyet, may_chu, 1280, theme="dark")
    p.locator(".tl-hong-nut").click()
    nen = p.evaluate("""() => { const bg = (e) => getComputedStyle(e).backgroundColor;
        return { app: bg(document.body), ten_bo: bg(document.getElementById('tl-ten-bo')), loc: bg(document.getElementById('tl-loc-bo')),
                 ghi_chu: bg(document.querySelector('.tl-ly-do input[type=text]')), ly_do: bg(document.querySelector('.tl-ly-do select')),
                 tim: bg(document.getElementById('tl-tim')), be_mat: bg(document.getElementById('tl-nhap')) }; }""")
    for k in ("ten_bo", "loc", "ghi_chu", "ly_do"):
        assert nen[k] == nen["app"], (k, nen)
    assert nen["tim"] == nen["be_mat"] != nen["app"], nen


def test_font_va_kep_dong_theo_mock(may_chu, trinh_duyet):
    """Tên video không dùng phông mono; lưới thư viện kẹp 2 dòng; cột phải một dòng + dấu …; h3 hộp duyệt 1.2rem. ĐỘT BIẾN: trả `var(--mono)` ⇒ ĐỎ."""
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    p.wait_for_function("document.querySelector('.tl-ten-v')")
    kq = p.evaluate("""() => { const cs = (s) => getComputedStyle(document.querySelector(s));
        return { luoi: [cs('.tl-ten-v').fontFamily, cs('.tl-ten-v').webkitLineClamp], h3: [cs('.tl-chi-tiet h3').fontFamily, cs('.tl-chi-tiet h3').fontSize],
                 cot: [cs('.tl-muc .ten').fontFamily, cs('.tl-muc .ten').whiteSpace, cs('.tl-muc .ten').textOverflow] }; }""")
    for ho in (kq["luoi"][0], kq["h3"][0], kq["cot"][0]):
        assert "mono" not in ho.lower(), kq
    assert kq["luoi"][1] == "2" and kq["h3"][1] == "19.2px" and kq["cot"][1:] == ["nowrap", "ellipsis"], kq


@pytest.mark.parametrize("hong", [500, 503, 404, "mang"])
def test_moc_cap_nhat_chi_nhich_khi_ca_bo_va_videos_ok(may_chu, trinh_duyet, hong):
    """Lỗi tải (mọi non-2xx + lỗi mạng) ⇒ MỘT câu thường, mốc "⟳ x giây trước" không nhích; lần sau ok ⇒ câu lỗi biến mất, mốc nhích.
    ĐỘT BIẾN: đặt `capNhatLuc` vô điều kiện ⇒ ĐỎ."""
    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    tinh = {"hong": True}

    def videos(r):
        if not tinh["hong"]:
            r.continue_()
        elif hong == "mang":
            r.abort()
        else:
            _tra_json(r, {"detail": "raw"}, hong)
    p.route("**/api/thay-logo/videos*", videos)
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.getElementById('tl-loi-tai').textContent.length > 0")
    chu = p.locator("#tl-loi-tai").inner_text()
    assert "Chưa tải được" in chu and str(hong) not in chu and "raw" not in chu
    assert p.locator("#tl-do-tuoi").inner_text() == "⟳ …" and p.evaluate("window.TL.capNhatLuc") == 0
    tinh["hong"] = False
    p.evaluate("window.TL_taiLai()")
    p.wait_for_function("document.getElementById('tl-do-tuoi').textContent.includes('giây trước')")
    assert p.locator("#tl-loi-tai").is_hidden() and p.locator("#tl-loi-tai").inner_text() == ""


def test_moc_khong_nhich_khi_chi_bo_loi(may_chu, trinh_duyet):
    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    p.route("**/api/thay-logo/bo", lambda r: _tra_json(r, {"detail": "x"}, 500))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.getElementById('tl-loi-tai').textContent.length > 0")
    assert p.locator("#tl-do-tuoi").inner_text() == "⟳ …"


def test_het_phien_401_dung_poll(may_chu, trinh_duyet):
    """401 giữa chừng: báo hết phiên và DỪNG vòng poll (không bắn 401 mỗi 15 giây). ĐỘT BIẾN: bỏ `clearInterval` ⇒ ĐỎ."""
    ctx = trinh_duyet.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    p.add_init_script("window.__ci = 0; const ci = window.clearInterval; window.clearInterval = (...a) => { window.__ci++; return ci(...a); };")
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('.tl-bo-the').length >= 2")
    assert p.evaluate("window.__ci") == 0
    p.route("**/api/thay-logo/bo", lambda r: _tra_json(r, {"detail": "x"}, 401))
    p.evaluate("void window.TL_taiLai()")
    p.wait_for_function("!document.getElementById('session-expired').hidden")
    assert p.evaluate("window.__ci") == 1
    assert p.locator("#tl-loi-tai").is_hidden()  # hết phiên đã có thông báo riêng, không chồng thêm câu "chưa tải được"


def test_doi_loc_giua_luc_dang_tai_khong_hien_video_cua_loc_cu(may_chu, trinh_duyet, monkeypatch):
    """Phản hồi thuộc bộ lọc cũ bị bỏ (số thế hệ lọc). ĐỘT BIẾN: bỏ `if (the0 !== the) return;` ⇒ ĐỎ (video cũ nhấp lên trước khi lọc mới về)."""
    import re
    giu = []
    dong = {None: [_dong_mo(61, job_id=1, ten_video="CHI CUA LOC CU"), _dong_mo(62, job_id=2, ten_video="Chung")],
            "1": [_dong_mo(61, job_id=1, ten_video="CHI CUA LOC CU")], "2": [_dong_mo(62, job_id=2, ten_video="CHI CUA LOC MOI")]}

    def videos(r):
        m = re.search(r"job_id=(\d+)", r.request.url)
        if m:
            giu.append((m.group(1), r))
        else:
            _tra_json(r, _danh_sach(dong[None]))
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, videos, bo=[_bo_mo(1, "Bộ một"), _bo_mo(2, "Bộ hai")])
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('.tl-bo-the').length === 2 && document.querySelector('#tl-duyet h3')")
    p.locator("button.tl-bo-chon[data-job='1']").click()  # lượt tải cho bộ 1: đang bay
    while not giu:
        p.wait_for_timeout(50)
    p.locator("button.tl-bo-chon[data-job='2']").click()  # đổi lọc sang bộ 2 khi bộ 1 chưa về
    assert "Đang tải" in p.locator("#tl-duyet").inner_text()
    ma, r = giu.pop(0)
    assert ma == "1"
    _tra_json(r, _danh_sach(dong["1"]))  # phản hồi của lọc CŨ về muộn
    p.wait_for_timeout(400)
    assert "CHI CUA LOC CU" not in p.locator("#tl-duyet").inner_text() + p.locator("aside.tl-cot").inner_text()
    while not giu:
        p.wait_for_timeout(50)
    ma, r = giu.pop(0)
    assert ma == "2"
    _tra_json(r, _danh_sach(dong["2"]))
    p.wait_for_function("document.querySelector('#tl-duyet h3') && document.querySelector('#tl-duyet h3').textContent === 'CHI CUA LOC MOI'")


def test_xem_them_bam_giua_luc_dang_tai_khong_bi_mat(may_chu, trinh_duyet, monkeypatch):
    """`xemThem` tăng số trang ngay; vòng tải đang bay không ghi đè. ĐỘT BIẾN: bỏ `soTrang += 1` ⇒ ĐỎ (trang 2 không bao giờ về)."""
    giu, goi = [], []

    def videos(r):
        goi.append(r.request.url)
        trang1 = "truoc_id" not in r.request.url
        if trang1 and len(goi) > 1 and not giu:
            giu.append(r)  # lượt tải lại (poll) đang bay, giữ phản hồi
            return
        _tra_json(r, _danh_sach([_dong_mo(80, trang_thai="cho", ten_video="Video 80")] if trang1 else [_dong_mo(70, trang_thai="cho", ten_video="Video 70")],
                                con_nua=trang1, truoc_tiep=80 if trang1 else None))
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, videos)
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_selector(".tl-xem-them")
    p.evaluate("void window.TL_taiLai()")
    while not giu:
        p.wait_for_timeout(50)
    p.locator(".tl-xem-them").click()  # bấm khi vòng tải trang 1 còn bay
    giu[0].fulfill(status=200, content_type="application/json",
                   body='{"videos": [], "con_nua": true, "truoc_tiep": 80, "thu_vien_loi": false}')
    p.wait_for_function("document.querySelectorAll('#tl-dang-lam .tl-muc').length === 2 && document.querySelector('#tl-dang-lam').innerText.includes('Video 70')", timeout=8000)
    assert p.locator(".tl-xem-them").count() == 0
    assert any("truoc_id=80" in u for u in goi)


def test_link_drive_chung_khuon_id_va_nut_dat_bi_khoa_khi_tinh_nang_tat(may_chu, trinh_duyet):
    p, _ = _mo(trinh_duyet, may_chu, 1280)
    ket = p.evaluate("""() => { const T = window.TL; return [T.linkDrive('../etc/passwd', 'x').tagName, T.linkDrive('a b', 'x').tagName,
        T.linkDrive('FILE20xxxxxxxxxxxx', 'x').tagName, T.IDRE.test('FILE20xxxxxxxxxxxx')]; }""")
    assert ket == ["SPAN", "SPAN", "A", True]
    goi = []
    p.on("request", lambda rq: goi.append(rq.url) if "danh-gia" in rq.url else None)
    p.wait_for_function("window.TL.tat === true")
    assert p.locator(".tl-dat").is_disabled()
    p.locator(".tl-dat").click(force=True)
    p.locator(".tl-dat").dispatch_event("click")
    p.keyboard.press("d")
    p.wait_for_timeout(300)
    assert goi == []  # chuột và phím cùng bị chặn


def test_ten_bo_la_html_hien_nguyen_van_khong_chay(may_chu, trinh_duyet, monkeypatch):
    xau = "<img src=x onerror=alert(1)>"
    ds = [_dong_mo(91, ten_bo=xau, ten_video=xau, trang_thai="cho"), _dong_mo(92, ten_bo=xau, ten_video=xau)]
    p = _trang_gia(trinh_duyet, may_chu, monkeypatch, lambda r: _tra_json(r, _danh_sach(ds)), bo=[_bo_mo(1, xau)])
    hop = []
    p.on("dialog", lambda d: (hop.append(d.message), d.dismiss()))
    p.goto(f"{may_chu}/thay-logo.html")
    p.wait_for_function("document.querySelectorAll('.tl-bo-the').length === 1 && document.querySelector('#tl-duyet h3')")
    p.wait_for_timeout(500)
    assert p.locator(".tl-bo-ten").inner_text() == xau and p.locator("#tl-duyet h3").inner_text() == xau
    assert xau in p.locator("#tl-dang-lam").inner_text()
    assert p.locator("img[src='x']").count() == 0 and p.locator("#tl-loc-bo option", has_text=xau).count() == 1
    assert hop == [], "mã trong tên bộ đã chạy"


# ---------------------------------------------------------------- tạo lượt (CUỐI file: thêm một bộ vào DB dùng chung)

def _chon_mot_video(p):
    p.wait_for_function("document.querySelectorAll('#tl-tab-thu-vien input[type=checkbox]').length >= 8")
    p.locator(f"#tl-tab-thu-vien input[value={FILE_THU_VIEN[0]}]").check()


def _mo_bat(br, goc, monkeypatch):
    monkeypatch.setattr(app_mod, "worker_thay_logo", object())  # tính năng BẬT ⇒ trang mở khoá ô nhập và nút tạo
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    mo_trang(p, f"{goc}/thay-logo.html", dem_mang_ngoai(ctx))
    p.wait_for_function("document.querySelectorAll('.tl-bo-the').length >= 2")
    return p


def test_anh_nghiem_thu_tinh_nang_bat_da_chon_3_video(may_chu, trinh_duyet, monkeypatch):
    """Trang ở trạng thái dùng thật (tính năng bật, đã tick 3 video): ảnh cho người duyệt đặt cạnh mock; ảnh bìa thư viện phải tải được."""
    p = _mo_bat(trinh_duyet, may_chu, monkeypatch)
    p.wait_for_function("document.querySelectorAll('#tl-tab-thu-vien input[type=checkbox]').length >= 8")
    for f in FILE_THU_VIEN[:3]:
        p.locator(f"#tl-tab-thu-vien input[value={f}]").check()
    p.wait_for_function("[...document.querySelectorAll('#tl-tab-thu-vien img')].length >= 8 && [...document.images].every(i => i.complete)")
    assert p.locator("#tat").is_hidden() and "Đã chọn 3 video" in p.locator("#tl-dem").inner_text()
    assert p.locator("#tl-tab-thu-vien img").first.evaluate("i => i.naturalWidth > 0")
    _anh(p, "1a-1280.png")


def test_ten_bo_tu_dien_theo_ngay_va_so_bo_hom_nay(may_chu, trinh_duyet, monkeypatch):
    p = _mo_bat(trinh_duyet, may_chu, monkeypatch)
    hn = time.localtime()
    # hôm nay đã có đúng 1 bộ (bộ B tạo cách đây 3 ngày không tính) ⇒ n = 2
    assert p.locator("#tl-ten-bo").input_value() == f"{hn.tm_mday:02d}/{hn.tm_mon:02d}-2" and p.locator("#tl-ten-bo").is_enabled()
    _chon_mot_video(p)
    assert f"bộ {hn.tm_mday:02d}/{hn.tm_mon:02d}-2" in p.locator("#tl-tao").inner_text()


def test_loi_400_429_hien_cau_loi_thuong(may_chu, trinh_duyet, monkeypatch):
    p = _mo_bat(trinh_duyet, may_chu, monkeypatch)
    _chon_mot_video(p)
    for ma, mong in ((400, "Tên bộ cần 1–80 ký tự"), (429, "quá nhiều video chờ")):
        p.route("**/api/thay-logo/jobs", (lambda ma: lambda r: r.fulfill(status=ma, content_type="application/json", body='{"detail": "raw detail"}'))(ma))
        p.locator("#tl-tao").click()
        p.wait_for_function(f"document.getElementById('tl-loi').textContent.includes({mong!r})")
        assert "raw detail" not in p.locator("#tl-loi").inner_text()
        p.unroute("**/api/thay-logo/jobs")


def test_409_cong_cam_hien_cau_loi_thuong(may_chu, trinh_duyet, monkeypatch):
    class Cam:
        ly_do_khong_nhan = "thư mục ra nằm trong Creative"

    p = _mo_bat(trinh_duyet, may_chu, monkeypatch)
    _chon_mot_video(p)
    monkeypatch.setattr(app_mod, "worker_thay_logo", Cam())  # sau khi trang đã mở: cổng cấu hình cấm ⇒ máy chủ trả 409 THẬT
    p.locator("#tl-tao").click()
    p.wait_for_function("document.getElementById('tl-loi').textContent.includes('tạm tắt')")
    chu = p.locator("#tl-loi").inner_text()
    assert "Creative" not in chu and "Traceback" not in chu
    assert p.locator("#tl-tab-thu-vien input:checked").count() == 1  # lượt không tạo được ⇒ giữ nguyên lựa chọn


def test_tao_luot_gui_ten_bo_va_bo_moi_hien_ra(may_chu, trinh_duyet, monkeypatch):
    p = _mo_bat(trinh_duyet, may_chu, monkeypatch)
    _chon_mot_video(p)
    p.locator("#tl-ten-bo").fill("  Bộ thử nghiệm 1  ")
    with p.expect_request(lambda r: r.url.endswith("/api/thay-logo/jobs") and r.method == "POST") as rq:
        p.locator("#tl-tao").click()
    body = rq.value.post_data_json
    assert body["ten_bo"] == "Bộ thử nghiệm 1" and body["drive_file_ids"] == [FILE_THU_VIEN[0]]
    p.wait_for_function("document.querySelectorAll('.tl-bo-the').length === 3")
    assert "Bộ thử nghiệm 1" in p.locator("#tl-bo-list").inner_text()
    assert p.locator("#tl-loi").inner_text() == "" and p.locator("#tl-tab-thu-vien input:checked").count() == 0
    conn = nhat_ky.mo(app_mod.DATA_DIR / "thay_logo_log.db")
    assert conn.execute("SELECT ten_bo FROM tl_job ORDER BY id DESC LIMIT 1").fetchone()[0] == "Bộ thử nghiệm 1"  # máy chủ đã lưu đúng tên gửi lên
    assert p.locator("#tl-ten-bo").input_value().endswith("-3")  # số bộ hôm nay tăng ⇒ tên mặc định lượt kế tiếp


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
