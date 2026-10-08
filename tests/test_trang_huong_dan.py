"""Trang Hướng dẫn: `GET /tinh-nang` + `huong-dan.html` trên trình duyệt thật.

Trang không chép số nào: mọi trần và danh sách nền tảng đến từ `/tinh-nang` (hằng thật), mọi câu đến
từ `stop-reason-text.js` / `cookie-status-text.js` mà trang tải cũng đọc. Các test dưới đây canh đúng
hai lời hứa đó, cộng lời hứa "endpoint chỉ trả hằng, không trả gì của người dùng".

Ảnh chụp sáng/tối ghi vào `$VIDEODL_ANH_HUONG_DAN` nếu có đặt (để người duyệt tự mở xem).
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from tiktok_music_downloader import nguon
from web import app as app_mod
from web import lifecycle, models, pacer
from trinh_duyet_khong_mang import ARGS_CHAN_MANG, dem_mang_ngoai, mo_trang

NGUOI = "huongdan@dev.local"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


# --------------------------------------------------------------- endpoint

@pytest.fixture
def db_tam(tmp_path, monkeypatch):
    """`/tinh-nang` đọc bảng `nen_tang_tat` — DB tạm đã dựng schema, không đụng DB thật."""
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs.db")
    models.init_db(app_mod.DB_PATH)
    return app_mod.DB_PATH


def test_tinh_nang_tra_dung_hang_that_trong_code(db_tam, monkeypatch):
    monkeypatch.delenv(nguon.ENV_NEN_TANG_BAT, raising=False)

    tn = app_mod.tinh_nang(nguoi_tao=NGUOI)

    assert [n["ten"] for n in tn["nguon"]] == [n.ten for n in nguon.NGUON]
    assert tn["nen_tang_bat"] == sorted(nguon.nen_tang_bat())
    t = tn["tran"]
    assert t["so_luong_mot_luot"] == app_mod.MAX_SO_LUONG
    assert t["link_mot_luot"] == app_mod.MAX_LINK_MOT_JOB
    assert t["video_kenh_youtube"] == app_mod.MAX_VIDEO_KENH_YOUTUBE
    assert t["thoi_luong_video_giay"] == nguon.TRAN_THOI_LUONG_GIAY
    assert t["dung_luong_video_mb"] * 1024 * 1024 == nguon.TRAN_DUNG_LUONG_BYTE
    assert t["tiktok_moi_ngay"] == {"luot": lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY,
                                    "video": lifecycle.MAX_VIDEOS_PER_COOKIE_PER_DAY,
                                    "trang_index": lifecycle.MAX_INDEX_PAGES_PER_COOKIE_PER_DAY}
    assert t["ip_moi_nen_tang"] == {nt: {"gio": g, "ngay": n} for nt, (g, n) in pacer.TRAN.items()}


def test_bat_them_nen_tang_thi_trang_doi_theo_khong_ai_sua_chu(db_tam, monkeypatch):
    """Lời hứa "không lạc hậu": đổi cờ đang áp ⇒ endpoint đổi theo ngay."""
    monkeypatch.setenv(nguon.ENV_NEN_TANG_BAT, "youtube,instagram")

    tn = app_mod.tinh_nang(nguoi_tao=NGUOI)

    assert tn["nen_tang_bat"] == ["instagram", "youtube"]
    assert "tiktok" in tn["nen_tang_link_le"], "danh sách có sẵn không phụ thuộc cờ bật"


def test_tinh_nang_chi_tra_hang_khong_tra_gi_cua_nguoi_dung(tmp_path, monkeypatch):
    """Không email, không đường dẫn (thư mục dữ liệu, cookie, DB), không khoá lạ.

    Khoá cấp 1 khoá cứng: thêm một trường mới phải sửa test này — tức phải nghĩ xem trường đó có
    được lộ ra không."""
    monkeypatch.setattr(app_mod, "DATA_DIR", tmp_path / "data-bi-mat")
    monkeypatch.setattr(app_mod, "COOKIES_DIR", tmp_path / "cookies-bi-mat")
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs-bi-mat.db")

    models.init_db(app_mod.DB_PATH)
    # Nền tảng bị tắt kèm lý do chứa chữ lỗi của nền tảng: chỉ TÊN được ra ngoài.
    pacer.tat_nen_tang(app_mod.DB_PATH, "youtube", "ERROR: Sign in bi-mat-ly-do")

    tn = app_mod.tinh_nang(nguoi_tao=NGUOI)
    tho = json.dumps(tn, ensure_ascii=False)

    assert tn["nen_tang_tam_tat"] == ["youtube"]

    assert set(tn) == {"nguon", "nen_tang_link_le", "nen_tang_bat", "nen_tang_tam_tat", "ten_hien_thi", "tran"}
    assert NGUOI not in tho and "@" not in tho
    for bi_mat in ("bi-mat", str(tmp_path), str(Path.home())):
        assert bi_mat not in tho, f"lộ {bi_mat!r}"


# --------------------------------------------------------------- trang

@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    from web.auth import require_user

    tmp = Path(tempfile.mkdtemp(prefix="videodl-huongdan-"))
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


def _mo_huong_dan(br, goc: str, *, theme: str = "light", rong: int = 1100):
    ctx = br.new_context(viewport={"width": rong, "height": 900}, color_scheme=theme)
    chan = dem_mang_ngoai(ctx)
    p = ctx.new_page()
    loi_js: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    mo_trang(p, f"{goc}/huong-dan.html", chan)
    p.wait_for_function("document.querySelector('#bang-nguon tbody tr td') && "
                        "!document.querySelector('#bang-nguon tbody').textContent.includes('Đang tải')")
    return p, loi_js


def _ma_trong_bang(js_tep: str, ten_bang: str) -> set[str]:
    import re
    js = (STATIC / js_tep).read_text(encoding="utf-8")
    dau = js.index(ten_bang)
    return set(re.findall(r"^\s{2,4}(\w+):", js[dau:js.index("};" if "const" in ten_bang else "});", dau)], re.M))


def test_trang_hien_dung_so_tu_may_chu_va_moi_ma_dung(may_chu, trinh_duyet, monkeypatch):
    monkeypatch.delenv(nguon.ENV_NEN_TANG_BAT, raising=False)
    p, loi_js = _mo_huong_dan(trinh_duyet, may_chu)

    assert loi_js == []
    # Nguồn: một dòng mỗi nguồn ở máy chủ.
    assert p.locator("#bang-nguon tbody tr").count() == len(nguon.NGUON)
    # Nền tảng bật: chip theo đúng cờ đang áp.
    chips = p.locator("#nen-tang-bat .hd-chip").all_text_contents()
    assert sorted(chips) == sorted(nguon.TEN_HIEN_THI[nt] for nt in nguon.nen_tang_bat())
    # Mọi ô số đã được điền (không còn "…" hay "?"), và đúng hằng.
    o = {el.get_attribute("data-tran"): el.text_content()
         for el in p.locator("[data-tran]").all()}
    assert all(v not in ("…", "?", "") for v in o.values()), o
    assert o["so_luong_mot_luot"] == str(app_mod.MAX_SO_LUONG)
    assert o["video_kenh_youtube"] == str(app_mod.MAX_VIDEO_KENH_YOUTUBE)
    assert o["thoi_luong_video_phut"] == str(nguon.TRAN_THOI_LUONG_GIAY // 60)
    assert o["tiktok_moi_ngay.luot"] == str(lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY)
    # Mọi mã dừng và mọi mã cookie có một dòng — cùng bảng mà trang tải dùng.
    ma_dung = set(p.locator("#bang-ly-do tbody td.hd-ma").all_text_contents())
    assert ma_dung == _ma_trong_bang("stop-reason-text.js", "const STOP_REASON_TEXT") and ma_dung
    ma_cookie = set(p.locator("#bang-cookie tbody td.hd-ma").all_text_contents())
    from web import cookies
    assert ma_cookie == set(cookies.MA_LOI_COOKIE)


def test_nen_tang_tam_tat_hien_canh_bao_tren_trang(may_chu, trinh_duyet):
    """Admin chưa bật lại sau tín hiệu chặn ⇒ tạo lượt bị 503. Trang phải nói, không chỉ ghi "đang bật"."""
    db = app_mod.DB_PATH
    models.init_db(db)
    p, _ = _mo_huong_dan(trinh_duyet, may_chu)
    assert p.locator("#tam-tat").is_hidden(), "chưa tắt gì mà đã cảnh báo"

    pacer.tat_nen_tang(db, "youtube", "thu")
    try:
        p.reload()
        p.wait_for_selector("#tam-tat:not([hidden])")
        assert "YouTube" in p.locator("#nen-tang-tam-tat").text_content()
    finally:
        with models._connect(db) as conn:
            conn.execute("DELETE FROM nen_tang_tat")


def test_o_tim_loc_bang_ly_do(may_chu, trinh_duyet):
    p, _ = _mo_huong_dan(trinh_duyet, may_chu)
    tong = p.locator("#bang-ly-do tbody tr").count()

    p.fill("#tim-ly-do", "cookie")
    hien = p.locator("#bang-ly-do tbody tr:not([hidden])")

    assert 0 < hien.count() < tong
    assert all("cookie" in t.lower() for t in hien.all_text_contents())


@pytest.mark.parametrize("rong", [1100, 390])
def test_trang_tai_va_cai_dat_deu_co_loi_vao_huong_dan(may_chu, trinh_duyet, rong):
    """Góc trên phải của cả hai trang — đúng chỗ user muốn "để mọi người tự check". Thêm một link vào
    thanh trên không được đẩy trang ra cuộn ngang ở màn điện thoại."""
    ctx = trinh_duyet.new_context(viewport={"width": rong, "height": 800})
    chan = dem_mang_ngoai(ctx)
    p = ctx.new_page()
    thu_muc = os.environ.get("VIDEODL_ANH_HUONG_DAN")
    for duong in ("/", "/settings.html"):
        mo_trang(p, f"{may_chu}{duong}", chan)
        link = p.locator(".topbar-nav a[href='/huong-dan.html']")
        assert link.count() == 1, duong
        assert "Hướng dẫn" in link.text_content()
        assert link.is_visible(), duong
        assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), f"cuộn ngang {duong}"
        if thu_muc:
            Path(thu_muc).mkdir(parents=True, exist_ok=True)
            ten = "trang-tai" if duong == "/" else "cai-dat"
            p.locator(".topbar").screenshot(path=str(Path(thu_muc) / f"topbar-{ten}-{rong}.png"))


def test_trang_tai_van_doc_duoc_bang_ly_do_sau_khi_tach_file(may_chu, trinh_duyet):
    """`app.js` giờ đọc bảng từ `stop-reason-text.js`. Quên nạp tệp đó trước `app.js` thì mọi thẻ dừng
    mất câu — kiểm bằng chính trang tải: bảng có trên window và `app.js` chạy không lỗi."""
    ctx = trinh_duyet.new_context()
    chan = dem_mang_ngoai(ctx)
    p = ctx.new_page()
    loi_js: list[str] = []
    p.on("pageerror", lambda e: loi_js.append(str(e)))
    mo_trang(p, f"{may_chu}/", chan)
    p.wait_for_load_state("load")

    assert loi_js == []
    assert p.evaluate("Object.keys(window.STOP_REASON_TEXT || {}).length") > 10


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("rong", [1100, 390])
def test_chup_trang_sang_toi(may_chu, trinh_duyet, theme, rong):
    """Không khẳng định gì ngoài "mở được, không lỗi JS, không cuộn ngang"; ảnh để người duyệt tự xem."""
    p, loi_js = _mo_huong_dan(trinh_duyet, may_chu, theme=theme, rong=rong)

    assert loi_js == []
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "cuộn ngang"
    thu_muc = os.environ.get("VIDEODL_ANH_HUONG_DAN")
    if thu_muc:
        Path(thu_muc).mkdir(parents=True, exist_ok=True)
        p.screenshot(path=str(Path(thu_muc) / f"huong-dan-{theme}-{rong}.png"), full_page=True)
