"""Nén phản hồi (`GZipMiddleware`) — qua server uvicorn THẬT, đọc byte thô bằng
`http.client` (không tự giải nén) để thấy đúng thứ trình duyệt/Cloudflare nhận.

Phải nén: JSON lớn (`/videos`), tài nguyên tĩnh lớn (`/app.js`) khi có `Accept-Encoding: gzip`.
KHÔNG được nén: SSE tiến độ job (loại trừ để tầng giữa không đệm stream nén), 206 (Range), HEAD, body nhỏ,
client không xin nén. `Cache-Control: no-cache` + 304 của tài nguyên tĩnh phải còn.
"""
from __future__ import annotations

import gzip
import http.client
import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

TOI = "gzip@dev.local"
STATIC = Path(__file__).resolve().parent.parent / "web" / "static"


@pytest.fixture(scope="module")
def may_chu():
    import uvicorn

    import web.app as app_mod
    from web import models
    from web.auth import require_user

    tmp_ctx = tempfile.TemporaryDirectory(prefix="videodl-gzip-")
    tmp = Path(tmp_ctx.name)
    cu = {k: getattr(app_mod, k) for k in
          ("DATA_DIR", "DB_PATH", "DOWNLOADS_DIR", "COOKIES_DIR", "COOKIE_TMP_DIR", "SSE_POLL_SECONDS")}
    app_mod.DATA_DIR, app_mod.DB_PATH = tmp, tmp / "jobs.db"
    app_mod.DOWNLOADS_DIR, app_mod.COOKIES_DIR = tmp / "downloads", tmp / "cookies"
    app_mod.COOKIE_TMP_DIR = tmp / "tmp"
    app_mod.SSE_POLL_SECONDS = 0.1
    models.init_db(app_mod.DB_PATH)
    job = models.create_job(app_mod.DB_PATH, "https://www.tiktok.com/tag/a", 300, TOI)
    for i in range(300):
        models.record_video(app_mod.DB_PATH, job_id=job, video_id=f"v{i:04d}", url=f"https://t.co/{i}",
                            title=f"Video {i} " + "chữ " * 20, tao_luc=f"2026-09-01T00:00:{i % 60:02d}+00:00")
    start, stop = app_mod.worker.start, app_mod.worker.stop
    app_mod.worker.start = app_mod.worker.stop = lambda: None
    app_mod.app.dependency_overrides[require_user] = lambda: TOI
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        port = so.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app_mod.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    het = time.monotonic() + 10
    while not server.started:
        assert t.is_alive() and time.monotonic() < het, "uvicorn không khởi động được"
        time.sleep(0.05)
    yield port, app_mod, job
    server.should_exit = True
    t.join(timeout=5)
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.worker.start, app_mod.worker.stop = start, stop
    for k, v in cu.items():
        setattr(app_mod, k, v)
    tmp_ctx.cleanup()


def _goi(port, method, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    h = {k.lower(): v for k, v in r.getheaders()}
    c.close()
    return r.status, h, body


GZ = {"Accept-Encoding": "gzip"}


def test_videos_lon_duoc_nen_va_giai_ra_dung_json(may_chu):
    port, _, _ = may_chu
    st, h, body = _goi(port, "GET", "/videos?limit=300&offset=0&vao_bo=0", GZ)
    assert st == 200 and h.get("content-encoding") == "gzip"
    goc = json.loads(gzip.decompress(body))
    assert goc["tong"] == 300 and len(goc["videos"]) == 300
    assert len(body) < len(json.dumps(goc)) / 3, "nén phải nhỏ hơn nhiều"


def test_client_khong_xin_nen_thi_nhan_tho_va_content_length_dung(may_chu):
    port, _, _ = may_chu
    st, h, body = _goi(port, "GET", "/videos?limit=300&offset=0&vao_bo=0")
    assert st == 200 and "content-encoding" not in h
    assert int(h["content-length"]) == len(body)
    assert json.loads(body)["tong"] == 300


def test_body_nho_khong_nen(may_chu):
    port, _, _ = may_chu
    st, h, _ = _goi(port, "GET", "/healthz", GZ)
    assert st == 200 and "content-encoding" not in h


def test_app_js_nen_van_no_cache_va_304_khi_khong_doi(may_chu):
    port, _, _ = may_chu
    st, h, body = _goi(port, "GET", "/app.js", GZ)
    assert st == 200 and h.get("content-encoding") == "gzip"
    assert h.get("cache-control") == "no-cache"
    assert gzip.decompress(body) == (STATIC / "app.js").read_bytes()
    st2, h2, body2 = _goi(port, "GET", "/app.js", {**GZ, "If-None-Match": h["etag"]})
    assert st2 == 304 and body2 == b""
    assert h2.get("cache-control") == "no-cache"


def test_range_206_khong_nen(may_chu):
    port, _, _ = may_chu
    st, h, body = _goi(port, "GET", "/app.js", {**GZ, "Range": "bytes=0-499"})
    assert st == 206 and "content-encoding" not in h
    assert body == (STATIC / "app.js").read_bytes()[:500]


def test_head_khong_nen_content_length_bang_tep(may_chu):
    port, _, _ = may_chu
    st, h, body = _goi(port, "HEAD", "/app.js", GZ)
    assert st == 200 and "content-encoding" not in h and body == b""
    assert int(h["content-length"]) == (STATIC / "app.js").stat().st_size


def test_sse_tien_do_khong_nen_va_toi_tung_su_kien(may_chu):
    """SSE KHÔNG nén (header là thứ phân định — đột biến bỏ loại trừ ⇒ có `content-encoding`).
    Đọc sự kiện ĐẦU khi job còn chạy, rồi mới cho job xong và đọc sự kiện thứ hai: đường
    không nén phải stream được từng sự kiện. (Tại server, Starlette flush mỗi chunk nên nén
    cũng không đệm — loại trừ là vì tầng giữa, xem `web/app.py`.)"""
    port, app_mod, job = may_chu
    from web import models
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", f"/jobs/{job}/events", headers=GZ)
    r = c.getresponse()
    h = {k.lower(): v for k, v in r.getheaders()}
    assert r.status == 200 and "content-encoding" not in h
    assert h["content-type"].startswith("text/event-stream")

    def doc_su_kien():
        dong = []
        while True:
            line = r.fp.readline().decode()
            if line in ("\r\n", "\n", ""):
                if dong:
                    return dong
                if line == "":
                    return dong
                continue
            dong.append(line.strip())

    dau = doc_su_kien()
    assert any(x.startswith("event: progress") for x in dau), dau
    models.finish_job(app_mod.DB_PATH, job, "done")
    sau = doc_su_kien()
    assert any('"done"' in x for x in sau if x.startswith("data:")), sau
    c.close()
