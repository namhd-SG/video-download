"""Giao diện tải ảnh — đo trên TRÌNH DUYỆT THẬT (app thật, DB tạm, worker tắt, danh tính giả).

Dữ liệu dựng qua các hàm model thật (job, video, `ghi_bai_anh`); chỉ ảnh thumb và vài đường ghi (POST /jobs,
POST /videos/loai) bị chặn để đo body. Không có Playwright/Chromium thì test SKIP — đọc dòng skip trước khi tin suite xanh.

Đột biến phải ĐỎ (tự áp rồi hoàn nguyên; lệnh mẫu chạy từ thư mục gốc repo):
  - Chạy lại / Tải lại bỏ `job.loai_tai`:
      sed -i '' 's/job.insight_goc, job.loai_tai)/job.insight_goc)/' web/static/app-su-kien-hang-doi-bo-loc.js
      ⇒ test_chay_lai_va_tai_lai_giu_loai_tai ĐỎ; `git checkout`/sửa ngược dòng đó ⇒ XANH.
  - `taoJobBody` luôn gắn `loai_tai`, hoặc công tắc form luôn hiện: test_form_* ĐỎ.
  - Nút Bỏ gửi bai_id thay vì `file_ids`: test_bo_bai_anh_gui_tung_tep ĐỎ.
Ảnh chụp: đặt `UI_TAI_ANH_ANH_DIR=<thư mục>` rồi chạy `test_chup_man_hinh` (không đặt ⇒ SKIP).
"""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import shutil
import tempfile
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from web import app as app_mod
from web import models, models_anh
from tiktok_music_downloader.tai_anh_cau_hinh import ENV_TAI_ANH_BAT, file_id_anh
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang

pw_api = pytest.importorskip("playwright.sync_api")

NGUOI = "tai-anh-ui@dev.local"
URL_ANH = "https://www.tiktok.com/@tai.anh.ui"
JS_HARNESS = Path(__file__).parent / "js"
APP_JS = Path(__file__).resolve().parent.parent / "web" / "static" / "app.js"


# ---------------------------------------------------------------- dữ liệu dựng
def _png(r: int, g: int, b: int, w: int = 90, h: int = 160) -> bytes:
    """PNG đặc một màu, không cần Pillow."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    hang = b"\x00" + bytes([r, g, b]) * w
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(hang * h)) + chunk(b"IEND", b""))


def _mau(khoa: str) -> bytes:
    h = zlib.crc32(khoa.encode())
    return _png(70 + h % 150, 70 + (h >> 8) % 150, 70 + (h >> 16) % 150)


def _job(db: Path, loai_tai: str, *, tong=10, xong=4, ly_do=None, trang_thai="done", url=URL_ANH) -> int:
    job = models.create_job(db, url, tong, NGUOI, loai_tai=loai_tai)
    models.set_job_found(db, job, tong)
    models.increment_job_counts(db, job, xong_delta=xong, loi_delta=0, loi_tiktok_delta=0)
    if ly_do:
        models.set_job_stop_reason(db, job, ly_do)
    models.finish_job(db, job, trang_thai)
    return job


# Số ảnh mỗi bài, cũ → mới: có bài 1 ảnh, 8–20 ảnh, 35 ảnh (trần TikTok đã đo). Bài MỚI NHẤT (cuối) có 3 ảnh: các
# test gửi Creative Desk / nút Bỏ dùng nó và mong đúng 3 tệp.
SO_ANH_MOI_BAI = (1, 8, 35, 12, 20, 1, 9, 15, 2, 18, 5, 3)
# Tên/tác giả dài như bài thật để thẻ phải tự cắt chữ.
_TIEU_DE = ("Phối đồ công sở mùa đông: áo khoác dạ dáng dài, quần ống suông và giày loafer — bộ {n} ảnh chi tiết",
            "Review 7 quán cà phê làm việc yên tĩnh quanh hồ Tây, có ổ cắm và wifi mạnh (phần {n})",
            "Công thức bánh chuối nướng không đường cho người ăn kiêng, từng bước có ảnh #{n}")
_TAC_GIA = ("thoitrang.congso.hangngay_official", "caphe.lamviec.hanoi", "bep.nha.minh.an.lanh")


def _bai(db: Path, job: int, so_anh_moi_bai=SO_ANH_MOI_BAI) -> list[str]:
    """Mỗi phần tử = một bài với chừng ấy tệp; thời điểm tạo cách nhau 7 phút, tăng dần ⇒ danh sách bai_id trả về có
    bài MỚI NHẤT ở cuối (thư viện phải vẽ ngược lại: mới nhất trước)."""
    ra = []
    goc = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)
    for i, so_anh in enumerate(so_anh_moi_bai):
        bai_id = f"anh-tt-76{i:03d}00000{i}"
        tao_luc = (goc + timedelta(minutes=7 * i)).isoformat()
        rows = [{"video_id": file_id_anh(bai_id, k), "job_id": job,
                 "url": f"https://www.tiktok.com/@{_TAC_GIA[i % 3]}/photo/{bai_id}",
                 "title": _TIEU_DE[i % 3].format(n=i + 1), "author": _TAC_GIA[i % 3], "bai_id": bai_id, "thu_tu": k,
                 "drive_file_id": f"drv{bai_id[-6:]}{k:02d}abcdefg", "tao_luc": tao_luc}
                for k in range(1, so_anh + 1)]
        models_anh.ghi_bai_anh(db, rows)
        ra.append(bai_id)
    return ra


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-tai-anh-ui-"))
    cu = {k: getattr(app_mod, k) for k in ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    cong = app_mod.should_reject_new_job
    app_mod.should_reject_new_job = lambda **kw: None
    app_mod.app.dependency_overrides[require_user] = lambda: NGUOI
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
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


@pytest.fixture
def du_lieu(may_chu):
    """DB sạch + bộ dữ liệu dày: 4 lượt (video/ảnh/cả hai/ảnh hỏng), 7 video, 12 bài ảnh."""
    _, db = may_chu
    models.init_db(db)
    with models._connect(db) as conn:
        for bang in ("videos", "jobs", "video_sightings"):
            conn.execute(f"DELETE FROM {bang}")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'jobs'")
    j_video = _job(db, "video", tong=20, xong=20, url="https://www.tiktok.com/tag/vidu")
    j_anh = _job(db, "anh", tong=10, xong=4, ly_do="het_vong")           # ⇒ nút "Tải thêm"
    j_ca = _job(db, "ca_hai", tong=8, xong=8, url="https://www.instagram.com/tai.anh.ui/")
    j_hong = _job(db, "anh", tong=6, xong=0, trang_thai="failed", url="https://www.tiktok.com/@hong.anh")
    for i in range(7):
        models.record_video(db, j_video, f"76870000{i:02d}", "https://www.tiktok.com/@a/video/1", title=f"Video thật {i + 1}",
                            author="tai.anh.ui", duration=15 + i, play_count=1000 * (i + 1), region="VN",
                            drive_file_id=f"drvvideo{i:02d}abcdefghi")
    bai = _bai(db, j_anh)
    return {"db": db, "j_anh": j_anh, "j_hong": j_hong, "j_ca": j_ca, "j_video": j_video, "bai": bai}


@pytest.fixture
def mo(may_chu, du_lieu):
    """`mo(bat=True, rong=1200)` ⇒ `(page, posts)`; `posts` = body các POST /jobs. Cờ tải ảnh đặt qua env (đọc lúc chạy)."""
    dong, cu = [], os.environ.get(ENV_TAI_ANH_BAT)

    def _mo(bat: bool = True, rong: int = 1200, cao: int = 1000, sang: bool = True):
        if bat:
            os.environ[ENV_TAI_ANH_BAT] = "1"
        else:
            os.environ.pop(ENV_TAI_ANH_BAT, None)
        pw = pw_api.sync_playwright().start()
        try:
            br = pw.chromium.launch(args=ARGS_CHAN_MANG)
        except Exception as exc:  # noqa: BLE001 — không có Chromium thì không đo được
            pw.stop()
            pytest.skip(f"không mở được Chromium: {exc}")
        dong.append((br, pw))
        ctx = br.new_context(viewport={"width": rong, "height": cao}, color_scheme="light" if sang else "dark")
        chan = dem_mang_ngoai(ctx)
        p = ctx.new_page()
        posts: list[dict] = []
        p.on("request", lambda r: posts.append(r.post_data_json)
             if r.method == "POST" and r.url.rstrip("/").endswith("/jobs") else None)
        p.route("**/thumbs/*", lambda r: r.fulfill(body=_mau(r.request.url.rsplit("/", 1)[-1]), content_type="image/png"))
        mo_trang(p, may_chu[0], chan)
        p.wait_for_selector("#queue-list li")
        p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")
        return p, posts

    yield _mo
    for br, pw in dong:
        br.close()
        pw.stop()
    if cu is None:
        os.environ.pop(ENV_TAI_ANH_BAT, None)
    else:
        os.environ[ENV_TAI_ANH_BAT] = cu


def _sang_anh(p) -> None:
    p.locator('#chip-loai [data-loai-thu-vien="anh"]').click()
    p.wait_for_function("document.getElementById('card-grid').dataset.napLoai === 'anh'")
    p.wait_for_function("document.querySelectorAll('#card-grid .card').length > 0")


# ------------------------------------------------------------------ taoJobBody
def test_tao_job_body_chi_them_loai_tai_khi_khac_video():
    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật")
    r = subprocess.run([node, str(JS_HARNESS / "tao-job-body.js"), str(APP_JS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["loai_video"] == {"url": "https://x", "so_luong": 5}
    assert d["loai_vang"] == {"url": "https://x", "so_luong": 5}
    assert d["loai_anh"] == {"url": "https://x", "so_luong": 5, "loai_tai": "anh"}
    assert d["loai_ca_hai"] == {"url": "https://x", "so_luong": 5, "usecase": "Dance", "loai_tai": "ca_hai"}


# ------------------------------------------------------------------------ form
def test_form_co_nhom_video_anh_ca_hai_khi_bat_mac_dinh_video(mo):
    p, _ = mo(bat=True)
    p.wait_for_selector("#loai-tai")
    assert p.locator("#loai-tai label span").all_text_contents() == ["Video", "Ảnh", "Cả hai"]
    assert p.locator('#loai-tai input:checked').get_attribute("value") == "video"


def test_form_co_tat_dom_y_het_cu_va_khong_nhan_video(mo):
    p, _ = mo(bat=False)
    assert p.locator("#loai-tai, #chip-loai, #job-form input[type=radio]").count() == 0
    # Hàng tuỳ chọn mở đầu bằng "Lấy" như bản chỉ-video.
    assert p.locator("#job-form .b-opts > span").first.inner_text() == "Lấy"
    # Cờ tắt: lượt video không có nhãn; lượt ảnh đã có sẵn vẫn được gọi tên.
    assert p.locator(".queue-item .nhan-loai-tai").all_text_contents().count("Video") == 0
    assert "Ảnh" in p.locator(".queue-item .nhan-loai-tai").all_text_contents()


def test_chon_anh_gui_loai_tai_anh_va_sau_do_ve_video(mo):
    p, posts = mo(bat=True)
    p.route("**/jobs", lambda r: r.fulfill(status=400, json={"detail": "thử"}) if r.request.method == "POST" else r.fallback())
    p.fill("#url", URL_ANH)
    p.locator("#loai-tai label", has_text="Ảnh").first.click()
    assert p.locator("#so-luong + span").inner_text() == "bài ảnh mới"
    p.click("#job-form button[type=submit]")
    p.wait_for_function("document.getElementById('error').textContent.includes('thử')")
    assert posts[-1] == {"url": URL_ANH, "so_luong": 20, "loai_tai": "anh"}
    # Lỗi thì giữ nguyên lựa chọn; thành công mới về Video (không nhớ lựa chọn).
    assert p.locator("#loai-tai input:checked").get_attribute("value") == "anh"


def test_mac_dinh_video_khong_co_khoa_loai_tai_trong_body(mo):
    p, posts = mo(bat=True)
    p.route("**/jobs", lambda r: r.fulfill(status=400, json={"detail": "thử"}) if r.request.method == "POST" else r.fallback())
    p.fill("#url", "https://www.tiktok.com/tag/vidu")
    p.click("#job-form button[type=submit]")
    p.wait_for_function("document.getElementById('error').textContent.includes('thử')")
    assert posts[-1] == {"url": "https://www.tiktok.com/tag/vidu", "so_luong": 20}


# ------------------------------------------------------------- thẻ lượt + nhãn
def test_nhan_loai_tren_the_luot(mo, du_lieu):
    p, _ = mo(bat=True)
    nhan = {jid: p.locator(f"#job-{jid} .nhan-loai-tai").inner_text()
            for jid in (du_lieu["j_video"], du_lieu["j_anh"], du_lieu["j_ca"])}
    assert nhan == {du_lieu["j_video"]: "Video", du_lieu["j_anh"]: "Ảnh", du_lieu["j_ca"]: "Cả hai"}


def test_chay_lai_va_tai_lai_giu_loai_tai(mo, du_lieu):
    """Lượt ảnh bấm "Tải thêm"/"Tải lại" phải ra lượt ẢNH, không rơi về video (hỏng im lặng: lượt mới chạy sai loại)."""
    p, posts = mo(bat=True)
    p.route("**/jobs", lambda r: r.fulfill(status=400, json={"detail": "thử"}) if r.request.method == "POST" else r.fallback())
    h = p.locator(f"#job-{du_lieu['j_anh']}")
    h.locator("[data-chay-lai]").click()
    h.locator("[data-chay-lai-ok]").click()
    for _ in range(50):
        if posts:
            break
        p.wait_for_timeout(100)
    assert posts[-1].get("loai_tai") == "anh", posts
    posts.clear()
    p.locator(f"#job-{du_lieu['j_hong']} [data-tai-lai]").click()
    for _ in range(50):
        if posts:
            break
        p.wait_for_timeout(100)
    assert posts[-1] == {"url": "https://www.tiktok.com/@hong.anh", "so_luong": 6, "loai_tai": "anh"}


# --------------------------------------------------------------------- thư viện
def test_thu_vien_cong_tac_loai_nap_anh_theo_bai(mo, du_lieu):
    p, _ = mo(bat=True)
    assert p.locator("#card-grid .card").count() == 7          # mặc định: video
    _sang_anh(p)
    assert p.locator("#card-grid .card").count() == len(du_lieu["bai"])
    assert p.locator("#card-grid .card-so-anh").first.inner_text() == "3 ảnh"
    moi_nhat = du_lieu["bai"][-1]
    assert p.locator(f'#card-grid .card[data-video-id="{moi_nhat}"] img').get_attribute("src") == f"/thumbs/{file_id_anh(moi_nhat, 1)}"
    assert "bài ảnh" in p.inner_text("#library-count")
    # Ảnh không có cụm: thanh bên và nút "Đưa vào cụm" ẩn.
    assert not p.locator("#cum-rail").is_visible()
    p.locator("#card-grid .card").first.click()
    assert not p.locator('[data-action="cum"]').is_visible()
    # Loại KHÔNG nằm trong các hộp lọc; "Dài"/"Thị trường" (ảnh không có dữ liệu đó) ẩn ở chế độ Ảnh.
    assert "Loại" not in p.locator("#filter-bar").inner_text()
    assert p.locator('#filter-bar [data-group="dai"], #filter-bar [data-group="thi_truong"]').count() == 0
    assert p.locator('#filter-bar [data-group="nguon"]').count() == 1
    # Mới nhất trước, đúng thứ tự thời điểm tạo (seed tăng dần ⇒ lưới là chiều ngược lại).
    thu_tu = p.eval_on_selector_all("#card-grid .card", "els => els.map(e => e.dataset.videoId)")
    assert thu_tu == list(reversed(du_lieu["bai"]))
    p.locator('#chip-loai [data-loai-thu-vien="video"]').click()
    p.wait_for_function("document.getElementById('card-grid').dataset.napLoai === 'video'")
    assert p.locator("#card-grid .card").count() == 7
    assert p.locator('#filter-bar [data-group="dai"]').count() == 1, "về Video ⇒ nhóm Dài hiện lại"
    assert p.locator("#selection-bar").is_hidden()              # lựa chọn không đi qua loại khác


@pytest.mark.parametrize("rong", [390, 1440])
def test_thu_vien_anh_ten_dai_khong_tran_the_va_khong_cuon_ngang(mo, du_lieu, rong):
    """Tác giả là handle dài không dấu cách: trước khi bọc `.card-author` nó ép cột lưới rộng ra (390: lưới tràn
    ngang, cột phải bị cắt; 1440: chữ đè sang thẻ bên). Đột biến: bỏ `.card { min-width: 0; }` HOẶC bỏ dòng CSS
    `.card-meta .card-author` trong `app.css` ⇒ ĐỎ."""
    p, _ = mo(bat=True, rong=rong)
    _sang_anh(p)
    do = p.evaluate("""() => {
        const luoi = document.getElementById('card-grid').getBoundingClientRect();
        const tran_the = [...document.querySelectorAll('#card-grid .card')].filter(c => {
            const r = c.getBoundingClientRect(), a = c.querySelector('.card-author').getBoundingClientRect();
            return r.right > luoi.right + 1 || a.right > r.right + 1;
        }).length;
        return {cuon_ngang: document.documentElement.scrollWidth > document.documentElement.clientWidth, tran_the};
    }""")
    assert do == {"cuon_ngang": False, "tran_the": 0}


def test_gui_creative_desk_mo_rong_thanh_tung_tep(mo, du_lieu):
    p, _ = mo(bat=True)
    # Tab Creative Desk giả: bắt tin postMessage thay vì mở tab thật.
    p.evaluate("window.open = () => ({ closed: false, postMessage: (m) => { window.__tin = m; } })")
    _sang_anh(p)
    bai = du_lieu["bai"][-1]
    p.locator(f'#card-grid .card[data-video-id="{bai}"]').click()
    p.click('[data-action="self-bundle"]')
    p.wait_for_function("window.__tin")
    items = p.evaluate("window.__tin.items")
    assert len(items) == 3
    assert all(set(i) == {"f", "n", "u"} for i in items), "item không được mang `k` (cụm)"
    assert [i["f"] for i in items] == [f"drv{bai[-6:]}{k:02d}abcdefg" for k in (1, 2, 3)]


def test_bo_bai_anh_gui_tung_tep(mo, du_lieu):
    p, _ = mo(bat=True)
    body = []

    def bat(route):
        body.append(route.request.post_data_json)
        ids = route.request.post_data_json["video_ids"]
        route.fulfill(json={"da_loai": ids, "drive_truot": [], "khong_phai_cua_ban": []})

    p.route("**/videos/loai", bat)
    p.on("dialog", lambda d: d.accept())
    _sang_anh(p)
    bai = du_lieu["bai"][-1]
    p.locator(f'#card-grid .card[data-video-id="{bai}"]').click()
    p.click('[data-action="loai"]')
    for _ in range(50):
        if body:
            break
        p.wait_for_timeout(100)
    assert body == [{"video_ids": [file_id_anh(bai, k) for k in (1, 2, 3)]}]


# -------------------------------------------------------------------- hướng dẫn
@pytest.mark.parametrize("bat,mong", [(True, "BẬT"), (False, "TẮT")])
def test_huong_dan_muc_tai_anh_theo_co(mo, may_chu, du_lieu, bat, mong):
    p, _ = mo(bat=bat)
    p.goto(may_chu[0] + "huong-dan.html")
    p.wait_for_function("!document.getElementById('tai-anh-trang-thai').textContent.includes('…')")
    assert mong in p.text_content("#tai-anh-trang-thai")
    assert p.locator("#tai-anh-chi-tiet").is_visible() is bat
    # Cờ tắt ⇒ cả mục "Tải ảnh" và link mục lục của nó ẩn (trang như trước khi có tính năng).
    assert p.locator("#tai-anh").is_visible() is bat
    assert p.locator("#muc-luc-tai-anh").is_visible() is bat


# ---------------------------------------------------------------------- ảnh chụp
@pytest.mark.parametrize("rong", [1440, 390])
@pytest.mark.parametrize("sang", [True, False], ids=["sang", "toi"])
def test_chup_man_hinh(mo, du_lieu, rong, sang):
    thu_muc = os.environ.get("UI_TAI_ANH_ANH_DIR")
    if not thu_muc:
        pytest.skip("đặt UI_TAI_ANH_ANH_DIR để chụp")
    out = Path(thu_muc)
    out.mkdir(parents=True, exist_ok=True)
    che = "sang" if sang else "toi"
    p, _ = mo(bat=True, rong=rong, cao=900, sang=sang)
    p.wait_for_timeout(300)
    p.locator("section.hero").screenshot(path=str(out / f"{rong}-{che}-1-form.png"))
    p.locator("section.queue-sec").screenshot(path=str(out / f"{rong}-{che}-2-hang-luot.png"))
    p.locator('#job-form input[value="anh"]').evaluate("el => el.click()")
    p.locator("section.hero").screenshot(path=str(out / f"{rong}-{che}-1b-form-chon-anh.png"))
    _sang_anh(p)
    p.wait_for_timeout(300)
    p.locator('section[aria-label="Thư viện creative"]').screenshot(path=str(out / f"{rong}-{che}-3-thu-vien-anh.png"))
    p.locator("#card-grid .card").first.click()
    p.screenshot(path=str(out / f"{rong}-{che}-4-chon-bai.png"))
