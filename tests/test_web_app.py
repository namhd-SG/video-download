"""Tests for web/app.py's `POST /jobs` gate wiring (Bước 4/5 of the fix
chain). Calls the route function directly — `create_job` is a plain Python
function under the FastAPI decorator, callable without an HTTP client or the
`httpx` test-client dependency this venv does not have installed.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from fastapi import HTTPException

from web import app as app_mod
from web import lifecycle
from web import models
from web.auth import require_user


# `nguoi_tao` arrives as a FastAPI dependency (`web.auth.require_user`), so a
# direct call must supply it the way the resolved dependency would. Auth
# itself is covered in tests/test_web_auth.py.
TEST_USER = "nhanvien@astronex.ai"


def _payload(url: str = "https://www.tiktok.com/music/x-1", so_luong: int = 5):
    return app_mod.CreateJobRequest(url=url, so_luong=so_luong)


# ---------------------------------------------------------------------------
# Bước 4: should_reject_new_job() is wired into POST /jobs. Not calling it (or
# calling it AFTER models.create_job) must make the tests below ĐỎ.
# ---------------------------------------------------------------------------

def test_create_job_rejects_with_503_when_gate_trips(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "should_reject_new_job",
                         lambda **kw: "Drive trượt 3 lần liên tiếp — tạm dừng nhận job mới")

    with pytest.raises(HTTPException) as exc_info:
        app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert exc_info.value.status_code == 503
    assert "trượt" in exc_info.value.detail


def test_create_job_rejects_before_creating_a_job_row(tmp_path, monkeypatch):
    """The gate must run BEFORE any job row is written — a caller retrying
    on 503 must never find a phantom 'pending' row left behind."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: "tạm dừng nhận job mới")

    with pytest.raises(HTTPException):
        app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert models.list_jobs(db_path) == []


def test_create_job_succeeds_when_gate_is_clear(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)

    job = app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert job["trang_thai"] == "pending"
    assert job["nguoi_tao"] == TEST_USER
    assert len(models.list_jobs(db_path)) == 1


def test_create_job_passes_downloads_dir_to_the_gate(tmp_path, monkeypatch):
    """Disk-guard half of the gate needs a real directory to statvfs — prove
    the wiring actually forwards `DOWNLOADS_DIR`, not a stub call."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    captured = {}

    def _fake_gate(**kw):
        captured.update(kw)
        return None

    monkeypatch.setattr(app_mod, "should_reject_new_job", _fake_gate)
    app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert captured.get("downloads_dir") == app_mod.DOWNLOADS_DIR


# ---------------------------------------------------------------------------
# Phase 05: identity comes from the verified JWT, never from the request body.
# ---------------------------------------------------------------------------

def test_body_cannot_set_nguoi_tao(tmp_path, monkeypatch):
    """A client posting `nguoi_tao` must not be able to steer it: that field
    is hashed into a cookie-jar filename, so choosing it means choosing whose
    cookies the job runs with."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)

    payload = app_mod.CreateJobRequest.model_validate({
        "url": "https://www.tiktok.com/music/x-1",
        "so_luong": 5,
        "nguoi_tao": "sep@astronex.ai",  # kẻ gọi cố tự xưng
    })
    assert not hasattr(payload, "nguoi_tao")

    job = app_mod.create_job(payload, nguoi_tao=TEST_USER)
    assert job["nguoi_tao"] == TEST_USER


def _dependency_calls(route) -> set:
    """Flatten a route's resolved dependency tree into the set of callables
    FastAPI will actually run for it."""
    found, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            found.add(dep.call)
        stack.extend(dep.dependencies)
    return found


@pytest.mark.parametrize("path,method", [
    ("/jobs", "POST"),
    ("/jobs", "GET"),
    ("/jobs/{job_id}", "GET"),
    ("/jobs/{job_id}/events", "GET"),
])
def test_job_routes_require_a_verified_user(path, method):
    """ĐỘT BIẾN: gỡ `Depends(require_user)` khỏi một route ⇒ ĐỎ ở đây.

    The direct-call tests above cannot catch that — they pass `nguoi_tao` by
    hand, so an unprotected route keeps them green while standing wide open
    to anything on this box that can reach 127.0.0.1:7870.
    """
    routes = [r for r in app_mod.app.routes
              if getattr(r, "path", None) == path and method in getattr(r, "methods", set())]
    assert routes, f"không tìm thấy route {method} {path}"
    assert require_user in _dependency_calls(routes[0])


def test_healthz_is_the_only_unauthenticated_route():
    """Positive control for the test above: proves `_dependency_calls` can
    return a set WITHOUT require_user, so the assertions there mean something."""
    healthz = [r for r in app_mod.app.routes if getattr(r, "path", None) == "/healthz"]
    assert healthz
    assert require_user not in _dependency_calls(healthz[0])


# ---------------------------------------------------------------------------
# Runtime data must not be readable by other accounts on the box. Measured on
# the mini 15/09: web/data/cookies was 755 and jobs.db 644 on a machine with a
# second user account — mkdir() without an explicit chmod is masked by umask,
# and does nothing at all when the directory already exists.
# ---------------------------------------------------------------------------

def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_prepare_data_dir_creates_private_dirs(tmp_path):
    data = tmp_path / "data"
    downloads, cookies = data / "downloads", data / "cookies"
    db = data / "jobs.db"

    app_mod.prepare_data_dir(data, downloads, cookies, db, data / "tmp")

    for d in (data, downloads, cookies):
        assert _mode(d) == 0o700, f"{d} nên 700, đang {oct(_mode(d))}"


def test_prepare_data_dir_tightens_dirs_that_already_exist_too_open(tmp_path):
    """The real failure on the mini: the directories already existed at 755,
    so a plain mkdir(exist_ok=True) left them wide open."""
    data = tmp_path / "data"
    downloads, cookies = data / "downloads", data / "cookies"
    for d in (data, downloads, cookies):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o755)
    db = data / "jobs.db"
    db.write_bytes(b"")
    os.chmod(db, 0o644)
    # Ca dương: chứng minh phép đo thấy được trạng thái XẤU trước khi sửa.
    assert _mode(cookies) == 0o755 and _mode(db) == 0o644

    app_mod.prepare_data_dir(data, downloads, cookies, db, data / "tmp")

    assert _mode(cookies) == 0o700
    assert _mode(downloads) == 0o700
    assert _mode(db) == 0o600


def test_prepare_data_dir_survives_a_missing_db(tmp_path):
    """First boot on a fresh box: sqlite has not created jobs.db yet."""
    data = tmp_path / "data"
    app_mod.prepare_data_dir(data, data / "downloads", data / "cookies",
                              data / "jobs.db", data / "tmp")
    assert not (data / "jobs.db").exists()


# ---------------------------------------------------------------------------
# Library grid endpoints (15/09)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_id", [
    "../../../etc/passwd", "..", "abc", "7001.webp", "7001/../x", "", "7001 ",
])
def test_thumb_endpoint_refuses_anything_that_is_not_digits(bad_id, tmp_path, monkeypatch):
    """`video_id` reaches the filesystem, so it is constrained by SHAPE: a
    digits-only string cannot contain "/", ".." or NUL. Structural, not a
    blocklist — same reasoning as the sha256 cookie filename."""
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs.db")
    with pytest.raises(HTTPException) as exc_info:
        app_mod.get_thumb(bad_id, nguoi_tao=TEST_USER)
    assert exc_info.value.status_code == 404


def test_thumb_endpoint_serves_a_digits_id_that_exists(tmp_path, monkeypatch):
    """Ca dương cho test trên: chứng minh 404 ở đó đến từ HÌNH DẠNG id, không
    phải vì endpoint này chẳng bao giờ trả được file nào."""
    db = tmp_path / "jobs.db"
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    thumb = lifecycle.thumb_path_for(db, "7001")
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"RIFF....WEBP")

    response = app_mod.get_thumb("7001", nguoi_tao=TEST_USER)

    assert Path(response.path) == thumb
    assert response.media_type == "image/webp"


def test_thumb_endpoint_404s_when_the_picture_was_never_cut(tmp_path, monkeypatch):
    """Absent is ordinary: ffmpeg may have failed for this one video, or it
    predates capture. Must be a clean 404, not a crash."""
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs.db")
    with pytest.raises(HTTPException) as exc_info:
        app_mod.get_thumb("7001", nguoi_tao=TEST_USER)
    assert exc_info.value.status_code == 404


def test_videos_endpoint_returns_the_whole_team_catalogue(tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    models.record_video(db, job_id=1, video_id="1", url="u1", region="MY")
    models.record_video(db, job_id=2, video_id="2", url="u2", region="BR")

    out = app_mod.list_videos(nguoi_tao=TEST_USER)

    assert out["tong"] == 2
    assert {v["video_id"] for v in out["videos"]} == {"1", "2"}


def test_videos_endpoint_includes_sources_from_sightings(tmp_path, monkeypatch):
    """ĐỘT BIẾN: bỏ nối `models.sources_for_videos` vào `list_videos` (app.py)
    ⇒ ĐỎ (KeyError trên `video["nguon"]`, đo tay 15/09 — xem báo cáo)."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    models.record_video(db, job_id=1, video_id="1", url="u1")
    models.record_sighting(db, video_id="1", job_id=1,
                            nguon="https://www.tiktok.com/tag/abc", da_tai=True)
    models.record_sighting(db, video_id="1", job_id=1,
                            nguon="https://www.tiktok.com/music/x-1", da_tai=False)

    out = app_mod.list_videos(nguoi_tao=TEST_USER)

    video = next(v for v in out["videos"] if v["video_id"] == "1")
    assert sorted(video["nguon"]) == [
        "https://www.tiktok.com/music/x-1",
        "https://www.tiktok.com/tag/abc",
    ]


def test_videos_endpoint_reports_empty_sources_for_a_video_with_no_sightings(
        tmp_path, monkeypatch):
    """Ca âm: video có hàng `videos` nhưng chưa từng có `video_sightings` (di
    sản trước khi bảng đó tồn tại) vẫn phải trả `nguon: []`, không KeyError,
    không 500 — bộ lọc "Nguồn" phía UI cần bucket "không rõ" ăn đúng ca này."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    models.record_video(db, job_id=1, video_id="2", url="u2")

    out = app_mod.list_videos(nguoi_tao=TEST_USER)

    video = next(v for v in out["videos"] if v["video_id"] == "2")
    assert video["nguon"] == []


def test_videos_endpoint_queries_sources_once_for_the_whole_page(tmp_path, monkeypatch):
    """Chặn N+1: `sources_for_videos` phải được gọi ĐÚNG MỘT LẦN cho cả trang
    (một mảng video_id), không phải một lần mỗi video."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    for i in range(5):
        models.record_video(db, job_id=1, video_id=str(i), url=f"u{i}")

    calls = []
    real_sources_for_videos = models.sources_for_videos

    def _counting(db_path, video_ids):
        calls.append(list(video_ids))
        return real_sources_for_videos(db_path, video_ids)

    monkeypatch.setattr(models, "sources_for_videos", _counting)

    app_mod.list_videos(nguoi_tao=TEST_USER)

    assert len(calls) == 1, f"gọi sources_for_videos {len(calls)} lần, cần đúng 1"
    assert set(calls[0]) == {"0", "1", "2", "3", "4"}


@pytest.mark.parametrize("limit,offset", [(0, 0), (-1, 0), (1001, 0), (10, -1)])
def test_videos_endpoint_rejects_out_of_range_paging(limit, offset, tmp_path, monkeypatch):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    with pytest.raises(HTTPException) as exc_info:
        app_mod.list_videos(limit=limit, offset=offset, nguoi_tao=TEST_USER)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("path,method", [("/videos", "GET"), ("/thumbs/{video_id}", "GET")])
def test_library_routes_require_a_verified_user(path, method):
    """Same mutation guard as the job routes: the catalogue names who
    downloaded what, and the thumbnails are the team's material."""
    routes = [r for r in app_mod.app.routes
              if getattr(r, "path", None) == path and method in getattr(r, "methods", set())]
    assert routes, f"không tìm thấy route {method} {path}"
    assert require_user in _dependency_calls(routes[0])


def test_thumb_endpoint_will_not_serve_a_file_outside_the_thumbs_dir(tmp_path, monkeypatch):
    """ĐỘT BIẾN: bỏ `video_id.isdigit()` ⇒ test này ĐỎ.

    The parametrised shape test above CANNOT catch that on its own: with the
    guard gone, a traversal path still points at nothing, so it 404s either
    way — green for the wrong reason. This test plants a real file exactly
    where `../` would land, so the two cases finally differ: guarded → 404,
    unguarded → the file is served.
    """
    db = tmp_path / "data" / "jobs.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    lifecycle.thumbs_dir_for(db).mkdir(parents=True, exist_ok=True)

    # thumbs/../khong-phai-cua-ban.webp  →  data/khong-phai-cua-ban.webp
    planted = db.parent / "khong-phai-cua-ban.webp"
    planted.write_bytes("nội dung KHÔNG được phục vụ".encode())
    assert planted.is_file()  # ca dương: file có thật, nên nếu lọt là lọt thật

    with pytest.raises(HTTPException) as exc_info:
        app_mod.get_thumb("../khong-phai-cua-ban", nguoi_tao=TEST_USER)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Trần job/ngày theo cookie phải được GỌI từ POST /jobs. Đây là test ở MỐI NỐI:
# hàm `daily_cap_rejection` có đúng đến mấy cũng vô nghĩa nếu route quên gọi —
# và unit test của riêng nó vẫn xanh trong đúng ca đó.
# ---------------------------------------------------------------------------

def _cap_env(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "COOKIES_DIR", cookies_dir)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)
    return db_path


def test_create_job_refuses_with_429_once_the_cookie_hit_its_daily_cap(tmp_path, monkeypatch):
    db_path = _cap_env(tmp_path, monkeypatch)
    for _ in range(lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY):
        app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    with pytest.raises(HTTPException) as exc_info:
        app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert exc_info.value.status_code == 429, (
        "trần ngày là 429 (chờ tới nửa đêm), KHÔNG phải 503 — 503 đang mang "
        "nghĩa 'máy đang kẹt, thử lại lát nữa' và cách chữa khác hẳn"
    )
    assert len(models.list_jobs(db_path)) == lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY, \
        "lượt bị trần chặn không được để lại hàng job ma"


def test_create_job_allows_every_job_up_to_the_cap(tmp_path, monkeypatch):
    """Ca dương bắt buộc: nếu trần chặn sớm hơn một lượt thì test trên vẫn
    xanh, vì nó chỉ hỏi 'có chặn không', không hỏi 'chặn đúng chỗ không'."""
    db_path = _cap_env(tmp_path, monkeypatch)
    for _ in range(lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY):
        app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert len(models.list_jobs(db_path)) == lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY


# ---------------------------------------------------------------------------
# Cache: vỏ trang + hai tệp nó trỏ tới phải được kiểm lại mỗi lần tải.
# Gọi thẳng hàm middleware — venv này không có `httpx` nên không dùng
# TestClient được (xem docstring đầu file).
# ---------------------------------------------------------------------------

def _header_for(path: str) -> str | None:
    import asyncio
    from types import SimpleNamespace

    from starlette.responses import Response

    request = SimpleNamespace(url=SimpleNamespace(path=path))

    async def call_next(_req):
        return Response(content=b"x")

    response = asyncio.run(app_mod.add_revalidate_header(request, call_next))
    return response.headers.get("cache-control")


def test_shell_and_its_assets_must_be_revalidated():
    assert _header_for("/") == "no-cache"
    assert _header_for("/index.html") == "no-cache"
    assert _header_for("/app.js") == "no-cache"
    assert _header_for("/app.css") == "no-cache"


def test_other_routes_are_left_alone():
    """Ca âm: middleware đóng dấu MỌI response thì bốn assert trên vẫn xanh
    trong khi header đã bị dán sai khắp nơi — kể cả lên JSON của /jobs."""
    assert _header_for("/healthz") is None
    assert _header_for("/jobs") is None


# ---------------------------------------------------------------------------
# Phase 05 — jar cookie tạm không được sống sót qua một lần bị giết.
#
# `download_all` xoá jar trong `finally`; SIGKILL không chạy `finally`, và
# launchd `KeepAlive=true` dựng lại ngay. Không quét thì mỗi lần bị giết để
# lại một tệp cookie dạng văn bản thuần nằm mãi trên đĩa.
#
# ĐỘT BIẾN: bỏ lời gọi `quet_jar_tam` trong `prepare_data_dir` ⇒ test đầu ĐỎ.
# ---------------------------------------------------------------------------

def test_leftover_cookie_jars_are_swept_at_startup(tmp_path, monkeypatch):
    from tiktok_music_downloader import downloader

    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    for i in range(3):
        (tmp_dir / f"{downloader.COOKIE_TMP_PREFIX}{i}.txt").write_text("# Netscape\n")

    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    app_mod.prepare_data_dir(tmp_path / "data", tmp_path / "dl", tmp_path / "ck",
                             db_path, tmp_dir)

    con_lai = list(tmp_dir.glob(f"{downloader.COOKIE_TMP_PREFIX}*"))
    assert con_lai == [], f"còn sót jar tạm: {[p.name for p in con_lai]}"


def test_the_sweep_only_takes_cookie_jars(tmp_path):
    """CA ÂM: một bộ quét xoá sạch thư mục cũng làm test trên xanh, trong khi
    nó đang xoá cả thứ không phải của nó."""
    from tiktok_music_downloader import downloader

    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir()
    (tmp_dir / f"{downloader.COOKIE_TMP_PREFIX}a.txt").write_text("x")
    khong_phai = tmp_dir / "dung-dung-vao-toi.txt"
    khong_phai.write_text("y")

    da_xoa = app_mod.quet_jar_tam(tmp_dir)

    assert da_xoa == 1
    assert khong_phai.exists(), "bộ quét chỉ được lấy jar cookie, không lấy thứ khác"


def test_the_web_layer_keeps_its_temp_jars_out_of_the_shared_temp_dir(tmp_path):
    """Jar tạm phải nằm trong thư mục 0700 của dịch vụ, không phải thư mục tạm
    hệ thống — nếu không thì quét dọn sẽ đụng tệp của công cụ dòng lệnh đang
    chạy trên cùng máy, và cookie nằm ở chỗ ai cũng liệt kê được."""
    from tiktok_music_downloader import downloader

    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    tmp_dir = tmp_path / "tmp"
    # Dựng sẵn với quyền RỘNG rồi mới gọi: nếu không, khẳng định 0700 bên dưới
    # có thể xanh chỉ vì thư mục thường trú của máy đã 0700 từ lần chạy trước —
    # đo CÁI MÁY chứ không đo MÃ. Và sửa-quyền-khi-đã-tồn-tại chính là lý do
    # `_make_private_dir` tồn tại (ca 755 đo trên mini 15/09).
    tmp_dir.mkdir()
    os.chmod(tmp_dir, 0o755)
    app_mod.prepare_data_dir(tmp_path / "data", tmp_path / "dl", tmp_path / "ck",
                             db_path, tmp_dir)

    assert downloader.COOKIE_TMP_DIR is not None, "để None là rơi về thư mục tạm hệ thống"
    assert Path(downloader.COOKIE_TMP_DIR) == tmp_dir
    assert stat.S_IMODE(os.stat(tmp_dir).st_mode) == 0o700, "phải SIẾT lại thư mục đã tồn tại"
