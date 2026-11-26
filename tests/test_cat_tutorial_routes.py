"""Trang Cắt tutorial: proxy `/cat-tutorial/*` (web/cat_tutorial_routes.py) với ui_server GIẢ (`httpx.MockTransport`).

Đột biến đã chạy tay khi viết:
  - bỏ `Depends(require_user)` khỏi route ⇒ test_chua_dang_nhap_401…, test_bat_bien_… , test_app_that_… ĐỎ;
  - gửi Cookie của trình duyệt thay cho `cookie_khu(email)` ⇒ test_hai_email… + test_cookie_trinh_duyet… ĐỎ.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import socket
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from web import app as app_mod
from web import auth
from web import cat_tutorial_routes as ctr
from web import gan_phien_ban_tai_nguyen as gpb
from web.auth import require_user
from web.cat_tutorial_duong_dan import kiem_hop_dong, viet_lai_index

FIXTURE = Path(__file__).parent / "fixtures" / "cat_tutorial_index_c96edb3.html"
STATIC = app_mod.STATIC_DIR
A, B = "a@astronex.ai", "B.Nguoi@Astronex.ai"
VIDEO = bytes(range(256)) * 4  # 1024 byte
_CHUA_TIEN_TO = re.compile(r"""["'`]/(?!cat-tutorial/)[A-Za-z]""")


KHOA = "khoa-thu-nghiem"


def _khu(email: str) -> str:  # tính ĐỘC LẬP với code: HMAC-SHA256(KHOA, email.lower())[:32]
    return "ct_ws=" + hmac.new(KHOA.encode(), email.lower().encode(), hashlib.sha256).hexdigest()[:32]


class _DongTungManh(httpx.AsyncByteStream):
    """Body đến từng mảnh như socket thật (`content=` của httpx thì đọc sẵn hết, không thử được đường stream)."""

    def __init__(self, b: bytes):
        self.b = b

    async def __aiter__(self):
        for i in range(0, len(self.b), 100):
            yield self.b[i:i + 100]


class UiServerGia:
    """Đóng vai ui_server: ghi lại mọi yêu cầu nhận được, trả như bản thật (Set-Cookie khu mới, Range ⇒ 206…)."""

    def __init__(self, loi: Exception | None = None):
        self.nhan: list[httpx.Request] = []
        self.loi = loi

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if self.loi:
            raise self.loi
        self.nhan.append(req)
        p = req.url.path
        sc = {"set-cookie": "ct_ws=" + "f" * 32 + "; Path=/; HttpOnly"}
        if p == "/":
            return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8", **sc}, content=FIXTURE.read_bytes())
        if p == "/api/state":
            return httpx.Response(200, json={"videos": [], "groups": [], "web": True, "dem": "x" * 3000},
                                  headers={"cache-control": "no-store", **sc})
        if p == "/api/upload":
            return httpx.Response(200, json={"ok": True})
        if p == "/video":  # cố ý octet-stream: proxy phải bỏ gzip theo ĐƯỜNG, không nhờ Content-Type
            rng = req.headers.get("range")
            if rng:
                a, b = (int(x) for x in rng.removeprefix("bytes=").split("-"))
                return httpx.Response(206, content=VIDEO[a:b + 1], headers={
                    "content-type": "application/octet-stream", "accept-ranges": "bytes",
                    "content-range": f"bytes {a}-{b}/{len(VIDEO)}"})
            return httpx.Response(200, stream=_DongTungManh(VIDEO), headers={
                "content-type": "application/octet-stream", "content-length": str(len(VIDEO)),
                "accept-ranges": "bytes", **sc})
        return httpx.Response(404, json={"error": "not found"})


def _app(ui: UiServerGia, nguoi: dict | None = None, gzip: bool = False) -> FastAPI:
    app = FastAPI()
    if gzip:
        app.add_middleware(ctr.GZipTruMedia, minimum_size=500)
    ctr.dang_ky(app, require_user=require_user, transport=httpx.MockTransport(ui))
    if nguoi is not None:
        app.dependency_overrides[require_user] = lambda: nguoi["email"]
    return app


@pytest.fixture(autouse=True)
def _bat(monkeypatch):
    monkeypatch.setenv(ctr.ENV_BAT, "1")
    monkeypatch.setenv(ctr.ENV_KHOA_KHU, KHOA)
    monkeypatch.delenv(ctr.ENV_UPSTREAM, raising=False)


@pytest.fixture
def access_da_cau_hinh(monkeypatch):
    """Access đã cấu hình nhưng request không mang JWT ⇒ `require_user` ném 401 (không tới bước lấy khoá)."""
    monkeypatch.setattr(auth, "_verifier", auth.AccessVerifier(team_domain="t.cloudflareaccess.com", aud="x",
                                                               certs_fetcher=lambda u: {"k": "c"}))


def test_chua_dang_nhap_401_dang_error_videos_va_khong_cham_ui_server(access_da_cau_hinh):
    ui = UiServerGia()
    app = _app(ui)

    @app.get("/khac")
    def khac(email: str = Depends(require_user)):
        return {}

    with TestClient(app) as c:
        for r in (c.get("/cat-tutorial/api/state"), c.get("/cat-tutorial/"),
                  c.post("/cat-tutorial/api/upload?id=abcdefgh&offset=0&total=3", content=b"abc")):
            assert r.status_code == 401
            assert r.json() == {"error": ctr.CAU_CHUA_DANG_NHAP, "videos": []}
        assert c.get("/khac").json().keys() == {"detail"}, "ngoài /cat-tutorial giữ dạng lỗi mặc định"
    assert ui.nhan == []


def test_hai_email_hai_khu_co_dinh_va_bo_set_cookie():
    ui, nguoi = UiServerGia(), {"email": A}
    with TestClient(_app(ui, nguoi)) as c:
        ra = [c.get("/cat-tutorial/api/state")]
        nguoi["email"] = B
        ra += [c.get("/cat-tutorial/api/state"), c.get("/cat-tutorial/"), c.get("/cat-tutorial/video?v=x")]
    assert all(r.status_code == 200 for r in ra)
    assert all("set-cookie" not in r.headers for r in ra)
    cookie = [q.headers.get("cookie") for q in ui.nhan]
    assert cookie == [_khu(A), _khu(B), _khu(B), _khu(B)]
    assert _khu(A) != _khu(B) and _khu(B) == _khu("b.nguoi@astronex.ai")
    assert ra[0].headers["cache-control"] == "no-store", "giữ no-store của ui_server"


def test_cookie_trinh_duyet_gui_khu_nguoi_khac_bi_thay_han():
    ui = UiServerGia()
    with TestClient(_app(ui, {"email": A})) as c:
        c.get("/cat-tutorial/api/state", headers={"Cookie": f"{_khu(B)}; khac=1",
                                                   auth.ACCESS_JWT_HEADER: "jwt-that"})
    (q,) = ui.nhan
    assert q.headers["cookie"] == _khu(A)
    assert auth.ACCESS_JWT_HEADER.lower() not in {k.lower() for k in q.headers}, "JWT Access không đi tới ui_server"


def test_upload_manh_32mb_giu_content_length_khong_chunked():
    ui, manh = UiServerGia(), bytes(range(256)) * (32 * 2**20 // 256)
    with TestClient(_app(ui, {"email": A})) as c:
        r = c.post("/cat-tutorial/api/upload?id=abcdefgh12&name=a.mp4&batch=x&offset=0&total=99999999",
                   content=manh, headers={"Content-Type": "application/octet-stream"})
        qua_lon = c.post("/cat-tutorial/api/upload?id=abcdefgh12", content=b"\0" * (ctr.TRAN_THAN_BYTE + 1))
    assert r.status_code == 200 and r.json() == {"ok": True}
    (q,) = ui.nhan
    assert q.method == "POST" and q.headers["content-length"] == str(len(manh))
    assert "transfer-encoding" not in q.headers and q.content == manh
    assert q.url.query == b"id=abcdefgh12&name=a.mp4&batch=x&offset=0&total=99999999"
    assert qua_lon.status_code == 413 and qua_lon.json() == {"error": ctr.CAU_THAN_QUA_LON, "videos": []}


def test_range_206_chuyen_tiep_va_media_khong_gzip():
    ui = UiServerGia()
    with TestClient(_app(ui, {"email": A}, gzip=True)) as c:
        r = c.get("/cat-tutorial/video?v=x", headers={"Range": "bytes=10-19", "Accept-Encoding": "gzip"})
        day = c.get("/cat-tutorial/video?v=x", headers={"Accept-Encoding": "gzip"})
        json_lon = c.get("/cat-tutorial/api/state", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 206 and r.content == VIDEO[10:20]
    assert r.headers["content-range"] == "bytes 10-19/1024" and r.headers["accept-ranges"] == "bytes"
    assert ui.nhan[0].headers["range"] == "bytes=10-19"
    assert day.status_code == 200 and day.content == VIDEO and day.headers["content-length"] == "1024"
    assert "content-encoding" not in day.headers and "content-encoding" not in r.headers
    assert json_lon.headers.get("content-encoding") == "gzip", "đối chứng: JSON lớn vẫn được nén"


def test_ui_server_tat_503_dang_dung(monkeypatch):
    with socket.socket() as s:  # cổng vừa trống ⇒ không ai nghe
        s.bind(("127.0.0.1", 0))
        cong = s.getsockname()[1]
    monkeypatch.setenv(ctr.ENV_UPSTREAM, f"http://127.0.0.1:{cong}")
    app = FastAPI()
    ctr.dang_ky(app, require_user=require_user)  # mạng THẬT, không MockTransport
    app.dependency_overrides[require_user] = lambda: A
    with TestClient(app) as c:
        r = c.get("/cat-tutorial/api/state")
    assert r.status_code == 503 and r.json() == {"error": ctr.CAU_DICH_VU_TAT, "videos": []}
    with TestClient(_app(UiServerGia(loi=httpx.ReadTimeout("x")), {"email": A})) as c:
        r = c.get("/cat-tutorial/api/edge?v=x&t=1")
    assert r.status_code == 504 and r.json() == {"error": ctr.CAU_QUA_LAU, "videos": []}


def test_ngoai_danh_sach_va_co_tat_404(monkeypatch):
    ui = UiServerGia()
    with TestClient(_app(ui, {"email": A})) as c:
        sai = [c.get("/cat-tutorial/api/open"), c.post("/cat-tutorial/api/open", json={"folder": "/"}),
               c.post("/cat-tutorial/api/pick", json={}), c.post("/cat-tutorial/api/reveal", json={}),
               c.get("/cat-tutorial/api/upload"), c.post("/cat-tutorial/api/state"),
               c.get("/cat-tutorial/etc/passwd"), c.get("/cat-tutorial/api/../api/open")]
        monkeypatch.setenv(ctr.ENV_BAT, "0")
        tat = c.get("/cat-tutorial/api/state")
    for r in sai:
        assert r.status_code == 404 and r.json() == {"error": ctr.CAU_KHONG_CO_DUONG, "videos": []}, r.url
    assert tat.status_code == 404 and tat.json() == {"error": ctr.CAU_TINH_NANG_TAT, "videos": []}
    assert ui.nhan == []


def test_trang_goc_viet_lai_tinh_lai_content_length_khong_gui_range():
    ui = UiServerGia()
    with TestClient(_app(ui, {"email": A})) as c:
        r = c.get("/cat-tutorial/", headers={"Range": "bytes=0-9"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert int(r.headers["content-length"]) == len(r.content) != FIXTURE.stat().st_size
    html = r.text
    assert '"/cat-tutorial/api/state"' in html and "`/cat-tutorial/api/edge?" in html
    assert 'url("/cat-tutorial/sprite?' in html and "studio-theme" not in html and '"videodl-theme"' in html
    assert "range" not in ui.nhan[0].headers and ui.nhan[0].url.path == "/"


def test_hop_dong_duong_dan_fixture_c96edb3():
    """Hợp đồng: sau viết lại KHÔNG còn `"/x` `'/x` `` `/x `` (x là chữ) thiếu tiền tố; `.split("/")` không bị tính."""
    goc = FIXTURE.read_text(encoding="utf-8")
    da_viet = viet_lai_index(goc)
    assert _CHUA_TIEN_TO.findall(da_viet) == []
    assert kiem_hop_dong(da_viet) == []
    assert viet_lai_index(da_viet) == da_viet, "viết lại hai lần không đổi thêm"
    assert '.split("/")' in da_viet
    # Đối chứng: bản gốc chưa viết lại phải ĐỎ; đường lạ (route mới của bản sau) phải ĐỎ dù đã viết lại.
    assert _CHUA_TIEN_TO.findall(goc) and kiem_hop_dong(goc)
    for la in ('fetch("/thumbs?v=1")', "x = '/api2/a'", "f(`/cat-tutorial/api/moi`)", 'f("/api/" + ten)'):
        assert kiem_hop_dong(viet_lai_index(la)), la


def test_bat_bien_moi_route_cat_tutorial_doi_require_user():
    routes = [r for r in app_mod.app.routes if getattr(r, "path", "").startswith("/cat-tutorial")]
    assert routes, "app thật chưa đăng ký route /cat-tutorial"
    for r in routes:
        assert isinstance(r, APIRoute), f"{r.path}: không phải APIRoute (mount/route thô thoát lưới require_user)"
        assert any(d.call is require_user for d in r.dependant.dependencies), r.path
        assert r.methods <= {"GET", "POST"}, r.methods


def test_app_that_401_dang_error_va_noi_day_du(access_da_cau_hinh, tmp_path, monkeypatch):
    """App THẬT (không `with` ⇒ không chạy lifespan/worker): cửa 401 + handler + GZip + revalidate + /tinh-nang + trang khung."""
    c = TestClient(app_mod.app)
    r = c.get("/cat-tutorial/api/state")
    assert r.status_code == 401 and r.json() == {"error": ctr.CAU_CHUA_DANG_NHAP, "videos": []}
    assert any(m.cls is ctr.GZipTruMedia for m in app_mod.app.user_middleware)
    trang = c.get("/cat-tutorial.html")
    assert trang.status_code == 200 and trang.headers["cache-control"] == "no-cache"
    assert re.search(r'src="cat-tutorial\.js\?v=[0-9a-f]{10}"', trang.text), "trang khung đi qua gắn ?v="
    assert "cat-tutorial.html" in gpb.TRANG_GAN_PHIEN_BAN
    from web import models
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    assert app_mod.tinh_nang(nguoi_tao=A)["cat_tutorial_bat"] is True
    monkeypatch.setenv(ctr.ENV_BAT, "0")
    assert app_mod.tinh_nang(nguoi_tao=A)["cat_tutorial_bat"] is False


def test_link_nav_an_mac_dinh_tren_5_trang_va_bat_theo_co():
    for ten in ("index.html", "settings.html", "huong-dan.html", "thay-logo.html", "thay-logo-lo.html"):
        html = (STATIC / ten).read_text(encoding="utf-8")
        assert '<a href="/cat-tutorial.html" id="link-cat-tutorial" hidden>Cắt tutorial</a>' in html, ten
        assert 'src="thay-logo-link.js"' in html, ten
    js = (STATIC / "thay-logo-link.js").read_text(encoding="utf-8")
    assert '"link-cat-tutorial", tn.cat_tutorial_bat' in js
    khung = (STATIC / "cat-tutorial.html").read_text(encoding="utf-8")
    assert 'id="ct-khung"' in khung and 'class="here" aria-current="page">Cắt tutorial' in khung
    assert 'khung.src = "/cat-tutorial/"' in (STATIC / "cat-tutorial.js").read_text(encoding="utf-8")


def test_bat_ma_thieu_khoa_khu_503_ro_va_khong_cham_ui_server(monkeypatch):
    monkeypatch.delenv(ctr.ENV_KHOA_KHU)
    ui = UiServerGia()
    with TestClient(_app(ui, {"email": A})) as c:
        r = c.get("/cat-tutorial/api/state")
    assert r.status_code == 503 and r.json() == {"error": ctr.CAU_CHUA_CAU_HINH_KHOA, "videos": []}
    assert ui.nhan == [], "thiếu khoá thì không được gọi ui_server bằng khoá đoán được"


def test_khoa_khu_khong_phai_sha256_tran_cua_email():
    # Biết email KHÔNG đủ để tự tính khu: khác sha256 trần, và đổi khoá ⇒ đổi khu.
    tran = "ct_ws=" + hashlib.sha256(A.encode()).hexdigest()[:32]
    assert ctr.cookie_khu(A, KHOA) == _khu(A) != tran
    assert ctr.cookie_khu(A, "khoa-khac") != ctr.cookie_khu(A, KHOA)


def test_post_tu_trang_khac_bi_chan_cung_nguon_thi_qua():
    ui = UiServerGia()
    with TestClient(_app(ui, {"email": A})) as c:
        la = c.post("/cat-tutorial/api/clear", json={}, headers={"Sec-Fetch-Site": "cross-site"})
        cung = c.post("/cat-tutorial/api/clear", json={}, headers={"Sec-Fetch-Site": "same-origin"})
    assert la.status_code == 403 and la.json()["error"] == ctr.CAU_KHAC_NGUON
    assert cung.status_code != 403
    assert [r.url.path for r in ui.nhan] == ["/api/clear"], "POST từ trang lạ không được tới ui_server"


def test_thieu_gach_cuoi_chuyen_sang_co_gach_cuoi_va_van_doi_dang_nhap(access_da_cau_hinh):
    with TestClient(_app(UiServerGia(), {"email": A})) as c:
        r = c.get("/cat-tutorial", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/cat-tutorial/"
    with TestClient(_app(UiServerGia(), None)) as c:  # chưa đăng nhập ⇒ không chuyển hướng
        assert c.get("/cat-tutorial", follow_redirects=False).status_code == 401
