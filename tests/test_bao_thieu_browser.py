"""Báo thiếu trên hàng đợi — luồng thật trên TRÌNH DUYỆT.

App thật (uvicorn, DB tạm, worker tắt, danh tính giả), fixture dựng qua CÁC HÀM
MODEL THẬT — cùng khuôn `test_chia_cum_browser.py`. Không có Playwright /
Chromium thì test SKIP; đọc dòng skip trước khi tin suite xanh.

Đột biến phải ĐỎ: mẫu số về `tong` · nút chạy lại hiện với mọi mã dừng · N =
`tong` thay vì phần thiếu.
"""
from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from web import app as app_mod
from web import models

NGUOI = "baothieu@dev.local"
URL_TAG = "https://www.tiktok.com/tag/vidu-bao-thieu"


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-baothieu-"))
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    # Máy thử không có Drive/đĩa thật: cổng "từ chối job mới" sẽ trả 503 và cú
    # bấm "Chạy lại" không bao giờ tạo được job. Cổng đó có test riêng.
    cong = app_mod.should_reject_new_job
    app_mod.should_reject_new_job = lambda **kw: None
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
    app_mod.should_reject_new_job = cong
    for k, v in cu.items():
        setattr(app_mod, k, v)


def _job(db: Path, *, tong: int, tim: int, bo_qua: int, xong: int, loi: int = 0,
         loi_tiktok: int = 0, ly_do: str | None = None, trang_thai: str = "done",
         url: str = URL_TAG) -> int:
    """Một job đã chạy, dựng bằng đúng các hàm mà worker gọi."""
    job = models.create_job(db, url, tong, NGUOI)
    models.set_job_found(db, job, tim)
    models.set_job_skipped(db, job, bo_qua)
    models.increment_job_counts(db, job, xong_delta=xong, loi_delta=loi,
                                loi_tiktok_delta=loi_tiktok)
    if ly_do:
        models.set_job_stop_reason(db, job, ly_do)
    if trang_thai == "done":
        models.finish_job(db, job, "done")
    elif trang_thai == "failed":
        models.finish_job(db, job, "failed")
    elif trang_thai == "running":
        with models._connect(db) as conn:
            conn.execute("UPDATE jobs SET trang_thai = 'running' WHERE id = ?", (job,))
    return job


@pytest.fixture
def db(may_chu):
    url, db = may_chu
    models.init_db(db)
    with models._connect(db) as conn:
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'jobs'")
    return db


def _mo_trang(may_chu):
    """Mở trang thật; trả `(page, gioi_han)` — `gioi_han` gom các POST /jobs."""
    pw_api = pytest.importorskip("playwright.sync_api")
    pw = pw_api.sync_playwright().start()
    try:
        br = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
        pw.stop()
        pytest.skip(f"không mở được Chromium: {exc}")
    ctx = br.new_context(viewport={"width": 1000, "height": 1100},
                         permissions=["clipboard-read", "clipboard-write"])
    p = ctx.new_page()
    posts: list[dict] = []
    p.on("request", lambda r: posts.append(r.post_data_json)
         if r.method == "POST" and r.url.rstrip("/").endswith("/jobs") else None)
    p.goto(may_chu[0])
    p.wait_for_selector("#queue-list li")
    return p, posts, (br, pw)


@pytest.fixture
def trang(may_chu, db):
    """`trang()` mở trình duyệt SAU khi test đã dựng job; trả `(page, posts)`."""
    dong = []

    def mo():
        p, posts, kem = _mo_trang(may_chu)
        dong.append(kem)
        return p, posts

    yield mo
    for br, pw in dong:
        br.close()
        pw.stop()


def _hang(p, job_id: int):
    return p.locator(f"#job-{job_id}")


def test_job_140_xin_88_do_duoc_hien_87_tren_88_va_dong_nguon(trang, db):
    job = _job(db, tong=140, tim=88, bo_qua=1, xong=87, loi=1, loi_tiktok=1, ly_do="het_vong")
    p, _ = trang()
    h = _hang(p, job)
    assert "Tải 87/88" in h.locator(".progress-row").inner_text()
    assert "140" not in h.locator(".progress-row").inner_text().split("/")[0]
    assert h.locator(".status-badge").inner_text() == "Nguồn hụt"
    nguon = h.locator(".nguon").inner_text()
    assert "Nguồn lần này có 89 video" in nguon and "bạn xin 140" in nguon
    assert "88 mới · 1 đã có trong kho" in nguon
    assert h.locator(".lo-tt").count() == 1 and "1 video nguồn không cho tải" in h.locator(".lo-tt").inner_text()
    assert h.locator(".lo-ht").count() == 0, "lỗi TikTok không được tô đỏ"
    assert h.locator(".progress-fill.has-errors").count() == 0
    assert h.get_by_role("button", name="Chạy lại để kiếm thêm 53 video…").count() == 1
    assert h.get_by_role("button", name="Chép link").count() == 1


def test_nghi_bi_chan_khong_co_nut_chay_lai_nhung_van_chep_link(trang, db):
    job = _job(db, tong=100, tim=30, bo_qua=0, xong=30, ly_do="nghi_bi_chan")
    p, _ = trang()
    h = _hang(p, job)
    assert h.locator("[data-chay-lai]").count() == 0
    assert h.locator(".status-badge").inner_text() == "Nghi bị chặn"
    assert h.get_by_role("button", name="Chép link").count() == 1
    assert "Nguồn lần này có 30 video" in h.locator(".nguon").inner_text()


@pytest.mark.parametrize("ma, co_nut", [
    ("het_vong", True), ("het_thoi_gian", True), ("page_cap", True), ("het_dia", True),
    ("nghi_bi_chan", False), ("stalled", False), ("already_owned", False),
    ("source_empty", False), ("feed_rong", False), ("index_failed", False),
    ("cookie_het_han", False), (None, False),
])
def test_nut_chay_lai_chi_cho_ba_ma_co_the_ra_them(trang, db, ma, co_nut):
    job = _job(db, tong=50, tim=20, bo_qua=0, xong=20, ly_do=ma)
    p, _ = trang()
    assert (_hang(p, job).locator("[data-chay-lai]").count() == 1) is co_nut, ma


def test_da_du_so_xin_khong_co_nut_chay_lai_du_ma_dung_la_het_vong(trang, db):
    job = _job(db, tong=20, tim=20, bo_qua=0, xong=20, ly_do="het_vong")
    p, _ = trang()
    assert _hang(p, job).locator("[data-chay-lai]").count() == 0


def test_loi_he_thong_khung_do_nhan_thieu_va_thanh_do(trang, db):
    job = _job(db, tong=20, tim=20, bo_qua=0, xong=19, loi=1, loi_tiktok=0)
    p, _ = trang()
    h = _hang(p, job)
    assert h.locator(".status-badge").inner_text() == "Thiếu"
    assert "1 video lỗi hệ thống" in h.locator(".lo-ht").inner_text()
    assert h.locator(".lo-tt").count() == 0
    assert h.locator(".progress-fill.has-errors").count() == 1
    assert "đủ số bạn xin" in h.locator(".nguon").inner_text()


def test_dang_tai_mau_so_la_so_do_duoc(trang, db):
    job = _job(db, tong=140, tim=88, bo_qua=0, xong=26, trang_thai="running")
    p, _ = trang()
    h = _hang(p, job)
    assert "Tải 26/88 · nguồn có 88 (xin 140)" in h.locator(".progress-row").inner_text()
    assert h.locator(".nguon").count() == 0


def test_chua_do_xong_mau_so_van_la_so_xin(trang, db):
    job = _job(db, tong=140, tim=0, bo_qua=0, xong=0, trang_thai="running")
    p, _ = trang()
    assert "Tải 0/140" in _hang(p, job).locator(".progress-row").inner_text()


def test_bam_chay_lai_gui_dung_mot_post_voi_phan_thieu(trang, db):
    job = _job(db, tong=140, tim=88, bo_qua=1, xong=87, loi=1, loi_tiktok=1, ly_do="het_vong")
    p, posts = trang()
    h = _hang(p, job)
    h.locator("[data-chay-lai]").click()
    o = h.locator("[data-chay-lai-n]")
    assert o.input_value() == "53", "N mặc định = tong − xong, không phải tong"
    with p.expect_response(lambda r: r.url.rstrip("/").endswith("/jobs") and r.request.method == "POST") as rs:
        h.locator("[data-chay-lai-ok]").click()
    assert rs.value.status == 200, rs.value.text()
    assert posts == [{"url": URL_TAG, "so_luong": 53}]
    p.wait_for_function("document.querySelectorAll('#queue-list > li').length === 2")
    assert len(posts) == 1


def test_sua_n_roi_chay_lai_gui_n_da_sua_va_so_khong_hop_le_khong_gui(trang, db):
    job = _job(db, tong=140, tim=88, bo_qua=1, xong=87, loi=1, loi_tiktok=1, ly_do="het_vong")
    p, posts = trang()
    h = _hang(p, job)
    h.locator("[data-chay-lai]").click()
    h.locator("[data-chay-lai-n]").fill("0")
    h.locator("[data-chay-lai-ok]").click()
    assert posts == [], "0 không hợp lệ ⇒ không gửi"
    assert "từ 1 đến 2000" in p.inner_text("#toast")
    h.locator("[data-chay-lai-n]").fill("7")
    with p.expect_response(lambda r: r.url.rstrip("/").endswith("/jobs") and r.request.method == "POST"):
        h.locator("[data-chay-lai-ok]").click()
    assert posts == [{"url": URL_TAG, "so_luong": 7}]


def test_o_chay_lai_song_sot_qua_nhip_ve_lai_hang_doi(trang, db):
    """Poll vẽ lại `innerHTML` mỗi 5 giây: ô đang mở không được biến mất."""
    job = _job(db, tong=140, tim=88, bo_qua=1, xong=87, ly_do="het_vong")
    p, _ = trang()
    h = _hang(p, job)
    h.locator("[data-chay-lai]").click()
    h.locator("[data-chay-lai-n]").fill("9")
    h.locator("[data-chay-lai-huy]").focus()   # rời ô ⇒ được phép vẽ lại
    p.wait_for_timeout(5600)
    assert p.locator(f"#job-{job} [data-chay-lai-n]").input_value() == "9"


def test_chep_link_dua_url_len_clipboard(trang, db):
    job = _job(db, tong=10, tim=10, bo_qua=0, xong=10)
    p, _ = trang()
    _hang(p, job).get_by_role("button", name="Chép link").click()
    p.wait_for_function("!document.getElementById('toast').hidden")
    assert p.evaluate("navigator.clipboard.readText()") == URL_TAG


def test_chep_link_truot_thi_bao_toast_khong_im_lang(trang, db):
    job = _job(db, tong=10, tim=10, bo_qua=0, xong=10)
    p, _ = trang()
    p.evaluate("() => { navigator.clipboard.writeText = () => Promise.reject(new Error('chan')); }")
    _hang(p, job).get_by_role("button", name="Chép link").click()
    p.wait_for_function("!document.getElementById('toast').hidden")
    assert "Không chép được" in p.inner_text("#toast")


def test_bam_doi_khi_post_dang_bay_qua_lan_ve_lai_chi_ra_mot_post(trang, db):
    """POST bị giữ, hàng đợi vẽ lại (poll 5s), bấm lần nữa ⇒ vẫn đúng 1 POST.

    Đột biến ĐỎ: bỏ `state.dangGuiChayLai.add(id)`.
    """
    job = _job(db, tong=140, tim=88, bo_qua=1, xong=87, ly_do="het_vong")
    p, _ = trang()
    giu: list = []
    dem = {"post": 0}

    def cong(route):
        if route.request.method == "POST":
            dem["post"] += 1
            giu.append(route)      # giữ lại, chưa cho đi
        else:
            route.continue_()

    p.route("**/jobs", cong)
    h = _hang(p, job)
    h.locator("[data-chay-lai]").click()
    h.locator("[data-chay-lai-ok]").click()
    p.wait_for_timeout(5600)          # ≥1 nhịp poll ⇒ hàng đợi đã vẽ lại
    ok = p.locator(f"#job-{job} [data-chay-lai-ok]")
    assert ok.is_disabled(), "sau vẽ lại nút xác nhận phải vẫn khoá khi POST còn bay"
    ok.dispatch_event("click")
    p.wait_for_timeout(300)
    assert dem["post"] == 1
    for r in giu:
        r.continue_()                 # KHÔNG unroute: unroute huỷ request đang giữ
    p.wait_for_function("document.querySelectorAll('#queue-list > li').length === 2")
    assert dem["post"] == 1


@pytest.mark.parametrize("ma, nhan", [
    ("het_vong", "Nguồn hụt"), ("het_thoi_gian", "Nguồn hụt"), ("page_cap", "Nguồn hụt"),
    ("nghi_bi_chan", "Nghi bị chặn"), ("stalled", "Hết video"),
    ("already_owned", "Đã có hết"), ("source_empty", "Nguồn rỗng"),
    # Đã tải hết số dò được, không lỗi hệ thống ⇒ không có gì "thiếu" để tô nhãn.
    ("feed_rong", "Xong"), (None, "Xong"),
])
def test_nhan_theo_ly_do_dung_nguon_hut_chi_cho_nhom_chay_lai_duoc(trang, db, ma, nhan):
    """Đột biến ĐỎ: "Nguồn hụt" bất kể mã dừng."""
    job = _job(db, tong=50, tim=20, bo_qua=0, xong=20, ly_do=ma)
    p, _ = trang()
    assert _hang(p, job).locator(".status-badge").inner_text() == nhan, ma


def test_loi_he_thong_thang_nhan_theo_ly_do_dung(trang, db):
    job = _job(db, tong=50, tim=20, bo_qua=0, xong=19, loi=1, ly_do="nghi_bi_chan")
    p, _ = trang()
    assert _hang(p, job).locator(".status-badge").inner_text() == "Thiếu"


def test_chay_lai_mang_theo_usecase_va_insight_goc_cua_luot_goc(trang, db):
    """Đột biến ĐỎ: bỏ usecase/insight_goc khỏi body chạy lại."""
    job = _job(db, tong=140, tim=88, bo_qua=1, xong=87, ly_do="het_vong")
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET usecase = 'Dance', insight_goc = 'Badaboum' WHERE id = ?", (job,))
    p, posts = trang()
    h = _hang(p, job)
    h.locator("[data-chay-lai]").click()
    with p.expect_response(lambda r: r.url.rstrip("/").endswith("/jobs") and r.request.method == "POST"):
        h.locator("[data-chay-lai-ok]").click()
    assert posts == [{"url": URL_TAG, "so_luong": 53, "usecase": "Dance", "insight_goc": "Badaboum"}]


def test_job_truoc_ban_cap_nhat_loi_chua_phan_loai_khung_xam_khong_do_khong_thieu(trang, db):
    """Hàng THẬT: tong=tim=20, xong=19, loi=1, loi_tiktok NULL, không mã dừng ⇒
    khung xám trung tính; KHÔNG đỏ, KHÔNG nhãn Thiếu (lỗi đó giải thích chỗ thiếu)."""
    job = _job(db, tong=20, tim=20, bo_qua=0, xong=19, loi=1)
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET loi_tiktok = NULL, ly_do_dung = NULL WHERE id = ?", (job,))
    p, _ = trang()
    h = _hang(p, job)
    assert h.locator(".lo-ht").count() == 0
    assert h.locator(".progress-fill.has-errors").count() == 0
    assert "1 lỗi (chưa phân loại — lượt trước bản cập nhật)" in h.locator(".lo-tt").inner_text()
    assert h.locator(".status-badge").inner_text() != "Thiếu"


def test_thieu_chi_vi_loi_tiktok_khong_gan_nhan_thieu(trang, db):
    """Job mới: 19/20, một video TikTok không cho tải ⇒ đã giải thích, không "Thiếu".

    Đột biến ĐỎ: trả lại nhánh cũ `xong < tong ⇒ Thiếu`."""
    job = _job(db, tong=20, tim=20, bo_qua=0, xong=19, loi=1, loi_tiktok=1)
    p, _ = trang()
    assert _hang(p, job).locator(".status-badge").inner_text() != "Thiếu"


def test_thieu_khong_giai_thich_duoc_van_la_thieu(trang, db):
    job = _job(db, tong=20, tim=20, bo_qua=0, xong=15)
    p, _ = trang()
    assert _hang(p, job).locator(".status-badge").inner_text() == "Thiếu"


def test_co_hang_loat_giu_cau_dung_cua_ma_khong_khuyen_chay_lai(trang, db):
    """Cờ + nghi_bi_chan ⇒ vẫn còn câu "NGHỈ…", vẫn không có nút chạy lại.

    Đột biến ĐỎ: ẩn câu dừng với MỌI mã khi có cờ."""
    job = _job(db, tong=50, tim=20, bo_qua=0, xong=15, loi=5, loi_tiktok=5, ly_do="nghi_bi_chan")
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET nghi_su_co_hang_loat = 1 WHERE id = ?", (job,))
    p, _ = trang()
    h = _hang(p, job)
    assert "NGHỈ" in h.locator(".stop-reason").inner_text()
    assert h.locator("[data-chay-lai]").count() == 0
    assert h.locator(".lo-ht").count() == 1



def test_co_nghi_su_co_hang_loat_khung_do_de_khung_xam_va_nhan_thieu(trang, db):
    """Đột biến ĐỎ: giao diện bỏ qua cờ."""
    job = _job(db, tong=50, tim=20, bo_qua=0, xong=15, loi=5, loi_tiktok=5, ly_do="het_vong")
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET nghi_su_co_hang_loat = 1 WHERE id = ?", (job,))
    p, _ = trang()
    h = _hang(p, job)
    assert "Có thể là sự cố hàng loạt" in h.locator(".lo-ht").inner_text()
    assert h.locator(".lo-tt").count() == 0, "khung đỏ ghi đè khung xám TikTok"
    assert h.locator(".status-badge").inner_text() == "Thiếu"
    assert h.locator(".progress-fill.has-errors").count() == 1


def test_job_cu_khong_co_co_hang_loat_thi_khong_do(trang, db):
    job = _job(db, tong=50, tim=20, bo_qua=0, xong=15, loi=5, loi_tiktok=5, ly_do="het_vong")
    p, _ = trang()
    h = _hang(p, job)
    assert h.locator(".lo-ht").count() == 0
    assert h.locator(".lo-tt").count() == 1


def test_co_hang_loat_an_nut_chay_lai_va_cau_ra_them_chi_con_khung_do(trang, db):
    """Đột biến ĐỎ: luật nút chạy lại bỏ qua cờ."""
    job = _job(db, tong=50, tim=20, bo_qua=0, xong=15, loi=5, loi_tiktok=5, ly_do="het_vong")
    with models._connect(db) as conn:
        conn.execute("UPDATE jobs SET nghi_su_co_hang_loat = 1 WHERE id = ?", (job,))
    p, _ = trang()
    h = _hang(p, job)
    assert h.locator("[data-chay-lai]").count() == 0
    assert "kiếm thêm" not in h.inner_text()
    assert h.locator(".stop-reason").count() == 0
    assert "ra thêm" not in h.inner_text()
    assert h.locator(".lo-ht").count() == 1
    assert h.get_by_role("button", name="Chép link").count() == 1
    assert h.locator(".status-badge").inner_text() == "Thiếu"


def test_the_feed_rong_hien_cau_xac_minh_khong_khuyen_dan_cookie(trang, db, tmp_path):
    """Thẻ hàng đợi THẬT của một lượt dừng vì `feed_rong` (profile, 0 video): khung lý do
    dừng nói "đòi xác minh (captcha)" và KHÔNG khuyên dán lại cookie — đo 01–02/10 cho
    thấy không cookie / cookie khác rỗng y hệt. Không gọi TikTok thật (DB tạm, worker tắt).
    Ảnh: `$VIDEODL_SHOT_DIR/the-feed-rong.png` nếu đặt biến đó (để người duyệt tự mở)."""
    import os
    job = _job(db, tong=20, tim=0, bo_qua=0, xong=0, ly_do="feed_rong",
               url="https://www.tiktok.com/@vidu.profile")
    p, _ = trang()
    h = _hang(p, job)
    cau = h.locator(".stop-reason").inner_text()
    assert "xác minh" in cau and "không chữa được" in cau, cau
    assert "dán lại cookie TikTok mới" not in cau, cau
    thu_muc = Path(os.environ.get("VIDEODL_SHOT_DIR", tmp_path))
    thu_muc.mkdir(parents=True, exist_ok=True)
    h.screenshot(path=str(thu_muc / "the-feed-rong.png"))


@pytest.mark.parametrize("ma", ["source_empty", "feed_rong", "nghi_bi_chan"])
def test_luot_rong_bi_loi_hien_loi_va_cau_khong_noi_xong(trang, db, ma):
    """Lượt rỗng giờ kết thúc `failed` (worker `process_job`): thẻ phải đọc "Lỗi",
    và câu lý do không được mở bằng "Xong:" — trước đây `source_empty` viết
    "Xong: nguồn này hiện không có video nào." cạnh một thẻ không tải được gì."""
    job = _job(db, tong=20, tim=0, bo_qua=0, xong=0, ly_do=ma, trang_thai="failed")
    p, _ = trang()
    h = _hang(p, job)
    assert h.locator(".status-badge").inner_text() == "Lỗi", ma
    cau = h.locator(".stop-reason").inner_text()
    assert cau and not cau.startswith("Xong"), (ma, cau)

