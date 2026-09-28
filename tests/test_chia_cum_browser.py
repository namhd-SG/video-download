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
from web import models, models_chia, models_cum

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
    with page.expect_response(lambda r: "/thao-tac" in r.url) as resp1:
        page.fill('[data-cc-field="usecase"]', "Motion")
        page.locator('[data-cc-field="usecase"]').blur()
    than1 = resp1.value.request.post_data_json
    assert than1["loai"] == "doi_insight" and than1["usecase"] == "Motion", \
        "điền usecase gửi MỘT doi_insight mang usecase mới"
    page.wait_for_timeout(150)
    with page.expect_response(lambda r: "/thao-tac" in r.url) as resp2:
        page.fill('[data-cc-field="insight_goc"]', "Strom Ai")
        page.locator('[data-cc-field="insight_goc"]').blur()
    than2 = resp2.value.request.post_data_json
    assert than2["loai"] == "doi_insight"
    assert than2["usecase"] == "Motion" and than2["insight_goc"] == "Strom Ai", \
        "điền ô THỨ HAI vẫn phải mang CẢ HAI giá trị hiện tại trong CÙNG một request"
    page.wait_for_function("!document.querySelector('[data-cc-action=\"duyet-het\"]').disabled")
    assert _so_thao_tac(page) == truoc, \
        "doi_insight KHÔNG tính vào bộ đếm hiển thị D15 — điền 2 ô (2 request) không đổi số"
    assert not page.locator('[data-cc-action="duyet-kieu"]').first.is_disabled()
    assert not page.locator('[data-cc-action="toggle-gop"]').first.is_disabled()
    assert page.locator(".cc-why").count() == 0

    with page.expect_response(lambda r: "/duyet" in r.url):
        page.locator('[data-cc-action="duyet-kieu"]').first.click()
    page.wait_for_function("document.querySelectorAll('.cc-kieu').length < 3")


def test_doi_ten_nhom_gui_mot_thao_tac_va_tang_bo_dem_dung_mot(page, dulieu):
    """Đổi tên MỘT nhóm gửi ĐÚNG một `doi_ten_nhom` (không phải N request rời
    cho N kiểu của nhóm), và bộ đếm hiển thị tăng đúng 1."""
    _mo_chia(page, dulieu["job_full"])
    truoc = _so_thao_tac(page)
    nhom_input = page.locator("[data-cc-nhom-rename]").first
    cur = nhom_input.get_attribute("data-cc-nhom-cur")
    with page.expect_response(lambda r: "/thao-tac" in r.url) as resp:
        nhom_input.fill("Đổi tên nhóm")
        nhom_input.dispatch_event("change")
    than = resp.value.request.post_data_json
    assert than == {"loai": "doi_ten_nhom", "nhom_cu": cur, "nhom_moi": "Đổi tên nhóm"}
    page.wait_for_timeout(150)
    assert _so_thao_tac(page) == truoc + 1


def test_duyet_kieu_xoa_tap_chon_video_da_duyet_khoi_dock(page, dulieu):
    """Chọn một video của một kiểu rồi duyệt đúng kiểu đó — dock không được
    tiếp tục báo video đó "đã chọn" (nó đã rời nháp, vào cụm thật); nếu
    không, thao tác kế tiếp trên dock (tách/chuyển/ngoài chủ đề) sẽ tưởng
    video đó còn ở nháp."""
    _mo_chia(page, dulieu["job_full"])
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="usecase"]', "Motion")
        page.locator('[data-cc-field="usecase"]').blur()
    page.wait_for_timeout(150)
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="insight_goc"]', "Strom Ai")
        page.locator('[data-cc-field="insight_goc"]').blur()
    page.wait_for_function("!document.querySelector('[data-cc-action=\"duyet-kieu\"]').disabled")

    page.locator(".cc-t[data-cc-video]").first.click()
    assert page.inner_text("#cc-dachon") == "1 video đã chọn"

    with page.expect_response(lambda r: "/duyet" in r.url):
        page.locator('[data-cc-action="duyet-kieu"]').first.click()
    page.wait_for_function("document.querySelectorAll('.cc-kieu').length < 3")
    assert page.inner_text("#cc-dachon") == "0 video đã chọn", \
        "video vừa duyệt phải rời khỏi tập đang chọn của dock"


def test_trung_cum_co_san_can_ca_usecase_khong_chi_insight(page, dulieu):
    """Nhãn "trùng cụm có sẵn" phải so CẢ usecase VÀ insight con — cùng khoá
    `models_cum._khoa_ten` server dùng. Cụm có sẵn (Motion, "Strom Mặc
    vest"); usecase khác (Dance) không được dán nhãn, cùng usecase (Motion)
    mới được."""
    db = dulieu["db"]
    models_cum.tao_cum(db, NGUOI, "Motion", "Strom", "Mặc vest")
    _mo_chia(page, dulieu["job_full"])

    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="usecase"]', "Dance")
        page.locator('[data-cc-field="usecase"]').blur()
    page.wait_for_timeout(150)
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="insight_goc"]', "Strom")
        page.locator('[data-cc-field="insight_goc"]').blur()
    page.wait_for_timeout(150)
    assert page.locator(".cc-tag-nhap").count() == 0, \
        "usecase khác cụm có sẵn thì KHÔNG được dán nhãn trùng"

    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="usecase"]', "Motion")
        page.locator('[data-cc-field="usecase"]').blur()
    page.wait_for_timeout(150)
    assert page.locator(".cc-tag-nhap").count() >= 1, \
        "cùng usecase + cùng insight con phải dán nhãn trùng"


def test_duyet_gui_kem_usecase_insight_hien_tai(page, dulieu):
    """Mọi body `/duyet` (duyệt một kiểu, "Duyệt tất cả"...) phải mang đúng
    usecase/insight gốc đang hiển thị trong ô nhập — hết race giữa blur ô
    nhập và bấm Duyệt (hai POST độc lập, server chỉ dùng ĐÚNG giá trị nhận
    được trong body `/duyet`, không tự đọc lại ô nhập)."""
    _mo_chia(page, dulieu["job_full"])
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="usecase"]', "Motion")
        page.locator('[data-cc-field="usecase"]').blur()
    page.wait_for_timeout(150)
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.fill('[data-cc-field="insight_goc"]', "Strom Ai")
        page.locator('[data-cc-field="insight_goc"]').blur()
    page.wait_for_function("!document.querySelector('[data-cc-action=\"duyet-kieu\"]').disabled")

    with page.expect_response(lambda r: "/duyet" in r.url) as resp1:
        page.locator('[data-cc-action="duyet-kieu"]').first.click()
    than1 = resp1.value.request.post_data_json
    assert than1["usecase"] == "Motion" and than1["insight_goc"] == "Strom Ai"
    page.wait_for_function("document.querySelectorAll('.cc-kieu').length < 3")

    with page.expect_response(lambda r: "/duyet" in r.url) as resp2:
        page.locator('[data-cc-action="duyet-het"]').click()
    than2 = resp2.value.request.post_data_json
    assert than2["usecase"] == "Motion" and than2["insight_goc"] == "Strom Ai"


def test_toast_video_da_o_cum_that_hien_ro_ly_do(page, dulieu):
    """Video gán TAY vào một cụm THẬT (`POST /cum/{id}/video`) NGAY SAU khi đã
    chọn trong dock (trước lượt `refresh()` kế tiếp) — root fix C2 khiến
    `lay_chia` ẩn video này khỏi mọi làn từ lượt vẽ SAU, nhưng dock (bộ nhớ
    chọn phía client) không tự biết cho tới lượt đó, nên lựa chọn cũ vẫn được
    gửi đi trong cửa sổ hẹp này — chạm nó qua `ngoai_chu_de` phải báo toast RÕ
    lý do, không phải mã lỗi trần hay câu chung chung. C1(c): `guard()` phải
    vẽ lại sau lỗi để số hiện trên dock khớp `CC.selected` thật (đã bị dock-
    ngoai xoá TRƯỚC khi gửi) — không treo số "1" cũ."""
    db = dulieu["db"]
    video_id = dulieu["ids"][0]
    _mo_chia(page, dulieu["job_full"])
    page.locator(f'.cc-t[data-cc-video="{video_id}"]').click()
    assert page.inner_text("#cc-dachon") == "1 video đã chọn"

    cum_id, _ = models_cum.tao_cum(db, NGUOI, "Motion", "Strom", "Vest")
    models_cum.gan_video(db, cum_id, NGUOI, None, [video_id])

    page.click('[data-cc-action="dock-ngoai"]')
    page.wait_for_function(
        "!document.getElementById('toast').hidden && "
        "document.getElementById('toast').textContent.length > 0")
    toast = page.inner_text("#toast")
    assert toast == "Video đã ở cụm thật, không di chuyển được (1 video).", toast
    assert page.inner_text("#cc-dachon") == "0 video đã chọn", \
        "guard() phải vẽ lại sau lỗi — dock không được treo số chọn cũ"


def test_doi_insight_hai_thay_doi_lien_tiep_khong_mat_ban_go_du_mang_cham(page, dulieu, monkeypatch):
    """Hai `doi_insight` liên tiếp (usecase rồi insight gốc, KHÔNG đợi request
    đầu xong) không được làm mất giá trị người dùng gõ sau — kể cả khi mạng
    làm request ĐẦU tới server CHẬM hơn request thứ hai. Delay chèn TRƯỚC khi
    `ap_thao_tac` mở transaction (`BEGIN IMMEDIATE` khoá ghi SQLite) — chèn
    SAU điểm đó sẽ vô tình để chính khoá ghi tự sắp lại thứ tự, che mất cuộc
    đua cần đo. Patch ở `models_chia.ap_thao_tac` (route `/thao-tac` tra
    thuộc tính module MỖI lượt gọi, không giữ tham chiếu cũ) chạy trên luồng
    threadpool RIÊNG của uvicorn — không phải luồng dispatch của Playwright,
    nên không tự xếp hàng hộ như route interception."""
    goc = models_chia.ap_thao_tac
    da_cham = {"n": 0}

    def _cham_doi_insight_dau(db_path, chia_lan_id, chu, loai, **tham_so):
        if (loai == "doi_insight" and da_cham["n"] == 0
                and tham_so.get("usecase") == "Motion" and tham_so.get("insight_goc") == ""):
            da_cham["n"] += 1
            time.sleep(0.5)
        return goc(db_path, chia_lan_id, chu, loai, **tham_so)

    monkeypatch.setattr(models_chia, "ap_thao_tac", _cham_doi_insight_dau)
    _mo_chia(page, dulieu["job_full"])

    page.fill('[data-cc-field="usecase"]', "Motion")
    page.locator('[data-cc-field="usecase"]').blur()   # request #1 — bị làm CHẬM 500ms
    # KHÔNG đợi request #1 — gõ và blur ô insight NGAY, để request #2 (nhanh,
    # không delay) có cơ hội chạm server TRƯỚC request #1 nếu không xếp hàng.
    page.fill('[data-cc-field="insight_goc"]', "Strom Ai")
    page.locator('[data-cc-field="insight_goc"]').blur()   # request #2 — gửi NGAY
    page.wait_for_timeout(800)   # qua khỏi mốc 500ms — cả hai request đã có phản hồi

    chia = models_chia.lay_chia_theo_job(dulieu["db"], dulieu["job_full"], NGUOI)
    assert (chia["usecase"], chia["insight_goc"]) == ("Motion", "Strom Ai"), \
        "giá trị cuối trên SERVER phải khớp giá trị gõ SAU CÙNG, không bị request #1 chậm đè lại"


def test_refresh_khong_de_len_o_dang_go_dang_focus(page, dulieu, monkeypatch):
    """`refresh()` chạy sau phản hồi CHẬM của request #1 (đổi usecase) không
    được đè GIÁ TRỊ lẫn FOCUS của ô insight người dùng đang gõ dở (CHƯA blur)
    — khác test trên (cả hai ô đều đã blur), test này giữ ô insight Ở TRẠNG
    THÁI ĐANG GÕ xuyên suốt cửa sổ phản hồi chậm để bắt đúng lỗi vẽ-lại-đè."""
    goc = models_chia.ap_thao_tac
    da_cham = {"n": 0}

    def _cham_doi_insight_dau(db_path, chia_lan_id, chu, loai, **tham_so):
        if (loai == "doi_insight" and da_cham["n"] == 0
                and tham_so.get("usecase") == "Motion" and tham_so.get("insight_goc") == ""):
            da_cham["n"] += 1
            time.sleep(0.5)
        return goc(db_path, chia_lan_id, chu, loai, **tham_so)

    monkeypatch.setattr(models_chia, "ap_thao_tac", _cham_doi_insight_dau)
    _mo_chia(page, dulieu["job_full"])

    page.fill('[data-cc-field="usecase"]', "Motion")
    page.locator('[data-cc-field="usecase"]').blur()   # request #1 — bị làm chậm 500ms
    page.fill('[data-cc-field="insight_goc"]', "Strom Ai")   # KHÔNG blur — còn đang gõ dở
    page.wait_for_timeout(700)   # qua khỏi mốc 500ms — request #1 đã có phản hồi, refresh() đã chạy
    assert page.input_value('[data-cc-field="insight_goc"]') == "Strom Ai", \
        "refresh() từ phản hồi CHẬM của request #1 không được đè ô đang gõ dở"
    assert page.evaluate("document.activeElement.getAttribute('data-cc-field')") == "insight_goc", \
        "refresh() không được cướp focus khỏi ô đang gõ"


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


def test_tach_kieu_moi_khi_luot_khong_con_kieu_nao(page, dulieu):
    """Lượt còn 0 kiểu (đã `xoa_kieu` hết) — modal "Kiểu mới từ chọn" phải
    mặc định chế độ "+ nhóm mới…" NGAY, không bế tắc chờ một sự kiện `change`
    không bao giờ xảy ra (chỉ có một option trong `<select>`)."""
    db, job = dulieu["db"], dulieu["job_full"]
    chia = models_chia.lay_chia_theo_job(db, job, NGUOI)
    for k in list(chia["kieu"]):
        models_chia.ap_thao_tac(db, chia["id"], NGUOI, "xoa_kieu", cum_nhap_id=k["cum_nhap_id"])

    _mo_chia(page, job)
    assert page.locator(".cc-kieu").count() == 0
    page.locator(".cc-t[data-cc-video]").first.click()
    page.click('[data-cc-action="dock-tach"]')
    page.wait_for_selector(".cc-modal")
    assert page.locator("[data-cc-tach-nhom-moi]").count() == 1, \
        "ô Tên nhóm mới phải hiện ngay khi lượt không còn nhóm nào"

    page.fill("[data-cc-tach-nhom-moi]", "Nhóm mới")
    page.fill("[data-cc-tach-kieu]", "Kiểu mới")
    page.locator("[data-cc-tach-kieu]").dispatch_event("change")
    with page.expect_response(lambda r: "/thao-tac" in r.url):
        page.click('[data-cc-action="confirm-tach"]')
    page.wait_for_function("document.querySelectorAll('.cc-kieu').length === 1")


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


# --- C1: dock "Ngoài chủ đề" với lựa chọn TRỘN (kiểu + đã ở nghi) -----------

def test_dock_ngoai_loc_video_da_o_nghi_truoc_khi_gui(page, dulieu):
    """C1(a): chọn trộn 1 video ở một KIỂU + 1 video ĐÃ ở "nghi" rồi bấm
    "Ngoài chủ đề" — hợp đồng server chỉ có MỘT trạng thái "nghi" nên từ chối
    CẢ yêu cầu nếu danh sách còn lẫn video đã ở nghi. UI phải tự lọc bỏ video
    đã ở nghi (giống `tra-ve-den`) TRƯỚC khi gửi: video ở kiểu vẫn chuyển sang
    nghi, không toast lỗi, dock về 0 — đây là thao tác tự nhiên khi người dùng
    muốn dồn hết lựa chọn vào nghi."""
    db = dulieu["db"]
    job = dulieu["job_full"]
    ids = dulieu["ids"]
    kieu_vid, nghi_vid = ids[0], ids[8]
    _mo_chia(page, job)

    page.locator(f'.cc-t[data-cc-video="{kieu_vid}"]').click()
    page.locator(f'.cc-t[data-cc-video="{nghi_vid}"]').click()
    assert page.inner_text("#cc-dachon") == "2 video đã chọn"

    with page.expect_response(lambda r: "/thao-tac" in r.url) as resp:
        page.click('[data-cc-action="dock-ngoai"]')
    than = resp.value.request.post_data_json
    assert than["video_ids"] == [kieu_vid], "phải lọc bỏ video đã ở nghi trước khi gửi"
    assert resp.value.ok, "danh sách đã lọc sạch phải được server chấp nhận"

    page.wait_for_function(
        "document.getElementById('cc-dachon').textContent === '0 video đã chọn'")
    assert page.is_hidden("#toast"), "không được có toast lỗi"

    chia = models_chia.lay_chia_theo_job(db, job, NGUOI)
    assert kieu_vid in chia["nghi"] and nghi_vid in chia["nghi"]
    assert kieu_vid not in [v for k in chia["kieu"] for v in k["video_ids"]]


def test_toast_rejection_khong_bao_gio_hien_ma_tran(page, dulieu):
    """C1(b): mọi mã `tu_choi` phải map sang câu tiếng Việt trong
    `errorDetailText`, không bao giờ lộ mã snake_case trần. Ép `khong_hop_le`
    qua nút "Hoàn tác" khi server không còn gì để lùi — gỡ `disabled` bằng tay
    để mô phỏng đúng dạng lỗi spec gọi là "API mismatch" (client tưởng bật
    được, server từ chối vì trạng thái thật không cho): nút này không tự kiểm
    `co_the_hoan_tac` lần hai trong handler, nên gỡ `disabled` là đủ để bấm
    chạm thẳng tới nhánh `tu_choi` thật của server."""
    _mo_chia(page, dulieu["job_full"])
    assert page.locator('[data-cc-action="hoan-tac"]').is_disabled(), \
        "chưa có thao tác sửa nào ⇒ nút phải khoá lúc mở nháp"
    page.evaluate(
        "document.querySelector('[data-cc-action=\"hoan-tac\"]').removeAttribute('disabled')")
    page.click('[data-cc-action="hoan-tac"]')
    page.wait_for_function(
        "!document.getElementById('toast').hidden && "
        "document.getElementById('toast').textContent.length > 0")
    toast = page.inner_text("#toast")
    assert toast == "Có video không thuộc đúng làn cho thao tác này — không thay đổi gì.", toast
    assert "_" not in toast, "không được lộ mã snake_case trần"


# --- C2: video gán TAY vào cụm thật không được chặn nút "cả làn" ------------

def test_hd_ngoai_chu_de_thanh_cong_cho_phan_con_lai_sau_khi_gan_tay(page, dulieu):
    """Root fix C2: một video làn "hướng dẫn" gán TAY vào cụm thật (không qua
    duyệt) trong lúc nháp còn mở phải ẩn khỏi `huong_dan` ngay (`lay_chia`),
    không kẹt ở đó mãi. Nút cả làn "hd-ngoai-chu-de" phải thành công cho phần
    còn lại — trước bản vá, video đã ở cụm thật vẫn nằm trong `huong_dan`,
    khiến `_kiem_video_ids_thao_tac` chặn CẢ yêu cầu vì lý do
    `video_da_o_cum_that`, và phần còn lại không bao giờ chuyển được bằng nút
    này nữa."""
    db = dulieu["db"]
    job = dulieu["job_full"]
    ids = dulieu["ids"]
    gan_vid, con_lai_vid = ids[6], ids[7]
    cum_id, _ = models_cum.tao_cum(db, NGUOI, "Motion", "Strom", "Vest")
    models_cum.gan_video(db, cum_id, NGUOI, None, [gan_vid])
    _mo_chia(page, job)

    tieude = page.inner_text("#cc-tieude")
    assert "thẻ chữ 1" in tieude, "video đã gán tay phải ẩn khỏi 'hướng dẫn' ngay khi mở nháp"

    with page.expect_response(lambda r: "/thao-tac" in r.url) as resp:
        page.click('[data-cc-action="hd-ngoai-chu-de"]')
    than = resp.value.request.post_data_json
    assert than["video_ids"] == [con_lai_vid], "chỉ video CÒN LẠI mới được gửi đi"
    assert resp.value.ok, "phần còn lại phải thành công, không bị chặn vì video kia đã ở cụm thật"

    page.wait_for_function("document.getElementById('cc-tieude').textContent.includes('thẻ chữ 0')")
    assert page.is_hidden("#toast"), "không được có toast lỗi"
    chia = models_chia.lay_chia_theo_job(db, job, NGUOI)
    assert chia["huong_dan"] == [] and con_lai_vid in chia["nghi"]
    assert chia["bi_bo"] == [], "video gán tay không phải video lạc — KHÔNG rơi vào bi_bo"


# --- C3: refresh() (GET) không có seq — phản hồi CŨ về SAU phải bị bỏ ------

def test_refresh_bo_qua_phan_hoi_cu_ve_muon_hon(page, dulieu):
    """`refresh()` xếp GET job/chia/cum chạy `Promise.all` mỗi lượt gọi,
    nhưng KHÔNG xếp các LƯỢT GỌI `refresh()` vào hàng đợi như POST
    (`apiQueueDuoi` chỉ xếp POST — xem `apiSend`). Một GET `/chia/{job_id}` bị
    mạng làm chậm có thể về SAU một GET mới hơn; không có `seq` để bỏ phản hồi
    cũ, DOM sẽ bị ghi ĐÈ NGƯỢC bằng dữ liệu CŨ khi phản hồi chậm cuối cùng
    cũng tới.

    Dùng `page.route` để tự tay kiểm SOÁT THỨ TỰ GIAO (đúng cách spec cho
    phép khi không tái hiện được thứ tự thật bằng mạng): request #1 chạm
    server THẬT ngay lập tức (`route.fetch()`) — đọc đúng usecase CŨ tại
    THỜI ĐIỂM ĐÓ — nhưng route KHÔNG `fulfill()` ngay, giữ lại response đó
    trong tay test. Request #2 (sau khi đã đổi usecase) được giao ngay. Chỉ
    SAU KHI DOM đã vẽ xong theo request #2 mới tự tay `fulfill()` response
    CŨ đã giữ của request #1 — mô phỏng đúng "phản hồi cũ về sau". (KHÔNG
    `time.sleep()` bên trong route handler: nó chạy trên cùng driver đồng bộ
    dùng chung cho MỌI lệnh Playwright khác của test — đo được `sleep` ở đó
    khoá luôn `page.wait_for_timeout()` gọi sau, phồng lên đúng bằng thời
    gian ngủ, che mất thứ tự cần đo)."""
    db = dulieu["db"]
    job = dulieu["job_full"]
    goc = models_chia.lay_chia_theo_job
    dem = {"n": 0}
    giu: dict = {}

    def _chan(route):
        if dem["n"] == 0:
            dem["n"] += 1
            # Chạm server NGAY — đọc usecase CŨ — nhưng KHÔNG giao ngay.
            giu["route"], giu["resp"] = route, route.fetch()
            return
        route.fulfill(response=route.fetch())

    page.route(f"**/chia/{job}", _chan)

    page.click(f'[data-chia="{job}"]')   # refresh #1 — server đã trả lời (usecase CŨ), CHƯA giao cho JS
    page.wait_for_timeout(150)   # đủ để route.fetch() (đồng bộ, nhanh) của request #1 chạy xong ở trên

    lan_id = goc(db, job, NGUOI)["id"]
    models_chia.ap_thao_tac(db, lan_id, NGUOI, "doi_insight", usecase="Moi", insight_goc="Sau")

    page.evaluate(f"() => {{ window.chiaCum.open({job}); }}")   # refresh #2 — chạm server SAU, giao NGAY (usecase MỚI)
    page.wait_for_function(
        "document.querySelector('[data-cc-field=\"usecase\"]') && "
        "document.querySelector('[data-cc-field=\"usecase\"]').value === 'Moi'")

    giu["route"].fulfill(response=giu["resp"])   # giờ mới giao phản hồi CŨ của request #1 — về SAU
    page.wait_for_timeout(200)   # đủ cho refresh() xử lý phản hồi vừa giao (nếu nó không bị bỏ)

    assert page.input_value('[data-cc-field="usecase"]') == "Moi", \
        "GET #1 (cũ, giao SAU) về SAU nhưng phải bị BỎ theo seq — không được ghi đè lại giá trị MỚI"


# --- lượt đã duyệt: không vẽ nút sửa nháp nào (server từ chối tất cả) ------

_NUT_SUA_NHAP = ", ".join([
    '[data-cc-action="hd-thanh-kieu"]', '[data-cc-action="hd-ngoai-chu-de"]',
    '[data-cc-action="toggle-tra-ve"]', '[data-cc-action="gop-nhom"]',
    '[data-cc-action="toggle-gop"]', '[data-cc-action="xoa-kieu"]',
    '[data-cc-action="duyet-kieu"]', '[data-cc-action="duyet-het"]',
    '[data-cc-action="hoan-tac"]', "[data-cc-kieu-rename]", "[data-cc-nhom-rename]",
])


def _duyet_het_sau_lung(dulieu) -> None:
    """Duyệt hết lượt thẳng ở server (như một tab khác vừa bấm "Duyệt tất cả")."""
    db, job = dulieu["db"], dulieu["job_full"]
    lan = models_chia.lay_chia_theo_job(db, job, NGUOI)
    models_chia.duyet_het(db, lan["id"], NGUOI, None, "Dance", "Badaboum")
    assert models_chia.lay_chia_theo_job(db, job, NGUOI)["trang_thai"] == "da_duyet"


def test_luot_da_duyet_khong_con_nut_sua_nhap_va_bao_ro(page, dulieu):
    """Ca thật 28/09 14:49: user duyệt tất cả lượt #10 rồi bấm "Thành kiểu
    ‘Hướng dẫn’" 8 lần, cả 8 bị server chặn (400). Lượt đã duyệt thì trang
    không được vẽ nút sửa nháp nào; ô usecase/insight chỉ đọc; không chọn
    thumb được; có một dòng nói rõ sửa ở đâu."""
    _mo_chia(page, dulieu["job_full"])
    assert page.locator(_NUT_SUA_NHAP).count() > 0, "đối chứng: nháp còn mở thì PHẢI có nút sửa"

    _duyet_het_sau_lung(dulieu)
    page.reload()
    page.wait_for_selector("#queue-list li")
    _mo_chia(page, dulieu["job_full"])
    page.wait_for_selector("[data-cc-da-duyet]")
    assert page.locator(_NUT_SUA_NHAP).count() == 0
    assert "Lượt đã duyệt — video đã vào cụm; sửa ở “Cụm của tôi”." in page.inner_text("#cc-main")
    assert page.locator('[data-cc-field="usecase"]').is_disabled()
    assert page.locator('[data-cc-field="insight_goc"]').is_disabled()
    assert page.locator('#cc-fields select').is_disabled(), "'Chia theo' chỉ hiển thị"
    # Làn Hướng dẫn/Nghi vẫn hiện video (chọn được để LOẠI — test riêng bên dưới),
    # nhưng dock sửa nháp không bao giờ hiện.
    assert page.locator(".cc-t").count() == 4
    page.locator(".cc-t").first.click()
    assert page.locator("#cc-dock").is_hidden()


def test_tab_cu_bam_nut_sua_sau_khi_da_duyet_toast_noi_tieng_nguoi(page, dulieu):
    """Tab mở TRƯỚC khi lượt được duyệt vẫn còn nút cũ — bấm thì server trả
    câu kỹ thuật "lượt đang 'da_duyet' …"; toast phải là câu người đọc được."""
    _mo_chia(page, dulieu["job_full"])
    _duyet_het_sau_lung(dulieu)
    page.click('[data-cc-action="hd-thanh-kieu"]')
    page.wait_for_function(
        "!document.getElementById('toast').hidden && "
        "document.getElementById('toast').textContent.includes('đã duyệt')")
    toast = page.inner_text("#toast")
    assert toast == "Lượt này đã duyệt — không sửa nháp được nữa. Video đã vào cụm; sửa ở “Cụm của tôi”.", toast
    assert "da_duyet" not in toast and "de_xuat" not in toast
    # Trang tự tải lại sang chế độ chỉ đọc — không còn nút nào để bấm tiếp mà 400
    # lần nữa (ca thật: 8 cú bấm liền).
    page.wait_for_selector("[data-cc-da-duyet]")
    assert page.locator(_NUT_SUA_NHAP).count() == 0


def test_tab_cu_dang_mo_hop_huy_luot_thi_hop_dong_sau_khi_bao(page, dulieu):
    """Tab cũ đang mở hộp "Hủy lượt" thì lượt được duyệt ở nơi khác: bấm xác
    nhận ⇒ server 400 ⇒ trang sang chỉ đọc VÀ hộp phải đóng, không để lại nút
    xác nhận bấm mãi vẫn 400."""
    _mo_chia(page, dulieu["job_full"])
    page.click('[data-cc-action="mo-huy"]')
    assert page.locator('[data-cc-action="confirm-huy"]').count() == 1
    _duyet_het_sau_lung(dulieu)
    page.click('[data-cc-action="confirm-huy"]')
    page.wait_for_selector("[data-cc-da-duyet]")
    assert page.locator('#cc-modal [data-cc-action]').count() == 0
    assert page.locator(_NUT_SUA_NHAP).count() == 0



# --- loại video ở làn Hướng dẫn / Nghi (thao tác THƯ VIỆN, chạy cả khi đã duyệt) ---

def _dat_trang_thai(db, job, trang_thai: str) -> None:
    lan = models_chia.lay_chia_theo_job(db, job, NGUOI)
    with models._connect(db) as conn:
        conn.execute("UPDATE chia_lan SET trang_thai = ? WHERE id = ?", (trang_thai, lan["id"]))


def _mo_lai(page, job) -> None:
    page.reload()
    page.wait_for_selector("#queue-list li")
    _mo_chia(page, job)


def test_luot_da_duyet_chi_lan_huong_dan_nghi_chon_duoc_kieu_thuong_thi_khong(page, dulieu):
    """Chéo (i)×(ii): lượt đã duyệt ⇒ thumb của KIỂU THƯỜNG không chọn được
    (không còn thao tác sửa nháp), còn thumb ở 2 làn Hướng dẫn/Nghi chọn được
    (để loại) và có ô tích + nút đếm đúng."""
    db, job = dulieu["db"], dulieu["job_full"]
    _dat_trang_thai(db, job, "da_duyet")   # giữ nguyên video trong kiểu để có thumb kiểu thường
    _mo_lai(page, job)
    page.wait_for_selector("[data-cc-da-duyet]")
    assert page.locator(".cc-kieu .cc-t").count() == 6
    assert page.locator(".cc-kieu .cc-t[data-cc-video]").count() == 0
    assert page.locator(".cc-nhom.cc-lan .cc-t[data-cc-video]").count() == 4
    assert page.locator(".cc-nhom.cc-lan .cc-chk").count() == 4
    assert page.locator('[data-cc-loai-trong="nghi"]').is_disabled()
    page.locator(".cc-nhom.cc-lan").nth(1).locator(".cc-t").first.click()
    assert page.locator(".cc-nhom.cc-lan .cc-t.sel").count() == 1
    assert page.inner_text('[data-cc-action="loai-lan"][data-lan="nghi"]') == "Loại 1 video đã chọn…"


def test_loai_video_o_lan_nghi_sau_khi_duyet_bien_khoi_lan_va_bao_du_so(page, dulieu):
    db, job, ids = dulieu["db"], dulieu["job_full"], dulieu["ids"]
    _duyet_het_sau_lung(dulieu)
    _mo_lai(page, job)
    nghi = page.locator(".cc-nhom.cc-lan").nth(1)
    nghi.locator(".cc-t").nth(0).click()
    nghi.locator(".cc-t").nth(1).click()
    page.click('[data-cc-action="loai-lan"][data-lan="nghi"]')
    assert "Loại 2 video khỏi thư viện?" in page.inner_text("#cc-modal")
    assert "Không có nút khôi phục" in page.inner_text("#cc-modal")
    with page.expect_response(lambda r: r.url.endswith("/videos/loai")):
        page.click('[data-cc-action="confirm-loai"]')
    page.wait_for_function("document.getElementById('toast').textContent.includes('Đã loại')")
    assert page.inner_text("#toast") == "Đã loại 2 video"
    _nhin_thay(page, "#toast")
    # Toast nổi trên cả lớp phủ màn chia (gồm hộp xác nhận) ⇒ không được bắt chuột.
    assert page.evaluate("getComputedStyle(document.getElementById('toast')).pointerEvents") == "none"
    page.wait_for_function("document.querySelectorAll('.cc-nhom.cc-lan')[1].querySelectorAll('.cc-t').length === 0")
    with models._connect(db) as conn:
        da = {r[0] for r in conn.execute("SELECT video_id FROM videos WHERE da_loai_luc IS NOT NULL")}
    assert da == set(ids[8:10]), "đúng 2 video làn Nghi, không đụng video khác"
    assert page.locator(".cc-nhom.cc-lan").nth(0).locator(".cc-t").count() == 2, "làn Hướng dẫn không đổi"


def test_huy_hop_xac_nhan_khong_loai_gi(page, dulieu):
    _mo_chia(page, dulieu["job_full"])
    goi = []
    page.on("request", lambda r: goi.append(r.url) if r.url.endswith("/videos/loai") else None)
    page.locator(".cc-nhom.cc-lan").nth(0).locator(".cc-t").first.click()
    page.click('[data-cc-action="loai-lan"][data-lan="huong_dan"]')
    page.click('#cc-modal [data-cc-action="modal-close"]')
    page.wait_for_timeout(300)
    assert goi == []
    assert page.locator(".cc-nhom.cc-lan").nth(0).locator(".cc-t").count() == 2


def _job_nghi_55(db) -> int:
    job = _job_voi_video(db, 57)
    ids = [f"77{job:03d}{i:04d}" for i in range(57)]
    nhoms = [{"nhom": "Âu phục", "kieu": [{"kieu": "Mặc vest", "video_ids": ids[:2]}]}]
    ket = models_chia.nhap_de_xuat(db, job, "vision:v1", "trang_phuc_dam_dong", nhoms, [], ids[2:], [])
    assert ket is not None and not ket["bo_vi_loc"]
    return job


@pytest.mark.parametrize("lo2_loi", [False, True])
def test_loai_55_video_chat_lo_50_va_dung_giua_chung_bao_con_bao_nhieu(page, dulieu, lo2_loi):
    """55 video ở làn Nghi ⇒ 2 lượt gọi (50 + 5), vì server chặn cứng 50 id.
    Lượt 2 trượt ⇒ dừng, báo đã loại 50 + còn 5 chưa gửi; làn còn 5."""
    job = _job_nghi_55(dulieu["db"])
    _mo_lai(page, job)
    goi = []
    def chan(route):
        goi.append(len(route.request.post_data_json["video_ids"]))
        if lo2_loi and len(goi) == 2:
            route.fulfill(status=500, body="{}", content_type="application/json")
        else:
            route.continue_()
    page.route("**/videos/loai", chan)
    thumbs = page.locator(".cc-nhom.cc-lan").nth(1).locator(".cc-t")
    assert thumbs.count() == 55
    for i in range(55):
        thumbs.nth(i).click()
    page.click('[data-cc-action="loai-lan"][data-lan="nghi"]')
    page.click('[data-cc-action="confirm-loai"]')
    page.wait_for_function("document.getElementById('toast').textContent.includes('Đã loại')")
    assert goi == [50, 5]
    toast = page.inner_text("#toast")
    if lo2_loi:
        assert toast.startswith("Đã loại 50 video") and "còn 5 video chưa gửi" in toast, toast
        page.wait_for_function("document.querySelectorAll('.cc-nhom.cc-lan')[1].querySelectorAll('.cc-t').length === 5")
    else:
        assert toast == "Đã loại 55 video", toast


def _nhin_thay(page, sel: str) -> None:
    """Phần tử có THẬT SỰ lộ ra mắt người không — không phải chỉ `hidden=false`
    và đúng chữ: điểm giữa của nó phải trúng chính nó (hoặc con của nó), không
    trúng một lớp phủ nằm trên (ca `.toast` z 40 dưới `#chia-view` z 50)."""
    trung = page.evaluate("""(sel) => {
      const el = document.querySelector(sel);
      if (!el || el.hidden) return "không hiện";
      el.scrollIntoView({block: "nearest"});
      const r = el.getBoundingClientRect();
      // `.toast` cố ý `pointer-events: none` (không chặn nút bên dưới) mà
      // elementFromPoint bỏ qua phần tử như thế — bật tạm để chỉ đo THỨ TỰ LỚP.
      const cu = el.style.pointerEvents;
      el.style.pointerEvents = "auto";
      const o = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      el.style.pointerEvents = cu;
      return o && el.contains(o) ? "trúng" : (o ? (o.id || o.className || o.tagName) : "null");
    }""", sel)
    assert trung == "trúng", f"{sel}: điểm giữa trúng {trung!r}"


@pytest.mark.parametrize("get_cung_het_phien", [False, True])
def test_loai_lo_2_het_phien_van_bao_da_loai_50_va_lam_moi_lan(page, dulieu, get_cung_het_phien):
    """Lô 1 đã loại 50 (không lùi được) rồi lô 2 hết phiên ⇒ vẫn phải báo
    "Đã loại 50", làn không còn hiện 50 video đó, rồi mới bật băng hết phiên.
    `get_cung_het_phien`: lượt tải lại làn cũng bị đẩy về trang đăng nhập (ca
    hết phiên thật) ⇒ làn phải tự bỏ 50 video tại chỗ."""
    job = _job_nghi_55(dulieu["db"])
    _mo_lai(page, job)
    goi = []
    def ve_dang_nhap(route):
        route.fulfill(status=302, headers={"Location": "/login"}, body="")
    def chan(route):
        goi.append(len(route.request.post_data_json["video_ids"]))
        if len(goi) == 2:
            if get_cung_het_phien:
                page.route(f"**/chia/{job}", ve_dang_nhap)
            ve_dang_nhap(route)
        else:
            route.continue_()
    page.route("**/videos/loai", chan)
    thumbs = page.locator(".cc-nhom.cc-lan").nth(1).locator(".cc-t")
    for i in range(55):
        thumbs.nth(i).click()
    page.click('[data-cc-action="loai-lan"][data-lan="nghi"]')
    page.click('[data-cc-action="confirm-loai"]')
    page.wait_for_function("document.getElementById('toast').textContent.includes('Đã loại')")
    assert goi == [50, 5]
    assert page.inner_text("#toast") == "Đã loại 50 video · phiên đăng nhập hết hạn — còn 5 video chưa gửi"
    page.wait_for_function("document.querySelectorAll('.cc-nhom.cc-lan')[1].querySelectorAll('.cc-t').length === 5")
    assert page.locator("#session-expired").is_visible()
    # Toast và băng phải LỘ RA trên lớp phủ màn chia, không chỉ "có trong DOM".
    _nhin_thay(page, "#toast")
    _nhin_thay(page, "#session-expired")
    # Đóng màn chia: băng về lại luồng trang thư viện và vẫn thấy được.
    page.click('#chia-view [data-cc-action="back"]')
    page.wait_for_selector("#chia-view", state="hidden")
    _nhin_thay(page, "#session-expired")


def test_dang_gui_loai_thi_khoa_nut_khong_gui_lan_hai(page, dulieu):
    """Bấm đôi: trong lúc lượt Loại đang bay, nút Loại phải bị khoá — nếu không
    lượt hai gửi lại các id vừa loại và toast báo sai "N không phải của bạn"."""
    _duyet_het_sau_lung(dulieu)
    _mo_lai(page, dulieu["job_full"])
    dang_giu = []
    def giu(route):
        dang_giu.append(route)   # giữ phản hồi lại, chưa cho server trả lời
    page.route("**/videos/loai", giu)
    nghi = page.locator(".cc-nhom.cc-lan").nth(1)
    nghi.locator(".cc-t").nth(0).click()
    page.click('[data-cc-action="loai-lan"][data-lan="nghi"]')
    page.click('[data-cc-action="confirm-loai"]')
    page.wait_for_function("document.querySelector('[data-cc-loai-dang-gui=\"nghi\"]')")
    assert page.locator('[data-cc-loai-dang-gui="nghi"]').is_disabled()
    assert page.locator('[data-cc-action="loai-lan"]').count() == 0
    assert len(dang_giu) == 1
    dang_giu[0].continue_()
    page.wait_for_function("document.getElementById('toast').textContent.includes('Đã loại')")
    assert page.inner_text("#toast") == "Đã loại 1 video"
    assert page.locator("[data-cc-loai-dang-gui]").count() == 0, "gửi xong thì mở khoá"


def test_tran_lo_loai_chia_khop_backend():
    import re
    src = (Path(__file__).resolve().parent.parent / "web" / "static" / "chia-cum.js").read_text()
    m = re.search(r"const LOAI_TOI_DA_MOI_LUOT = (\d+);", src)
    assert m and int(m.group(1)) == app_mod.MAX_VIDEO_LOAI
