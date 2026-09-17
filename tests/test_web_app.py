"""Tests for web/app.py's `POST /jobs` gate wiring (Bước 4/5 of the fix
chain). Calls the route function directly — `create_job` is a plain Python
function under the FastAPI decorator, callable without an HTTP client or the
`httpx` test-client dependency this venv does not have installed.
"""
from __future__ import annotations

import asyncio
import json
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

    assert models.list_jobs(db_path, None) == []


def test_create_job_succeeds_when_gate_is_clear(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "should_reject_new_job", lambda **kw: None)

    job = app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert job["trang_thai"] == "pending"
    assert job["nguoi_tao"] == TEST_USER
    assert len(models.list_jobs(db_path, None)) == 1


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


def _thu_vien_hai_nguoi(tmp_path, monkeypatch):
    """Kho chung, hai chủ: V1 do TEST_USER tải, V2 do người khác.

    `nguon` của V2 cố ý là một URL tìm kiếm mang từ khoá — đó là thứ cùng hạng
    với `jobs.url`, và là lý do `sources_for_videos` phải lọc chứ không chỉ
    `list_videos`.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job_toi = models.create_job(db, "https://www.tiktok.com/tag/cua-toi", 5, TEST_USER)
    job_ho = models.create_job(db, "https://www.tiktok.com/tag/cua-ho", 5, "ho@astronex.ai")
    models.record_video(db, job_id=job_toi, video_id="1", url="u1", region="MY")
    models.record_sighting(db, video_id="1", job_id=job_toi,
                            nguon="https://www.tiktok.com/tag/cua-toi", da_tai=True)
    models.record_video(db, job_id=job_ho, video_id="2", url="u2", region="BR")
    models.record_sighting(db, video_id="2", job_id=job_ho,
                            nguon="https://www.tiktok.com/search?q=BI-MAT-CUA-HO",
                            da_tai=True)
    # Lượt của họ cũng TRÔNG THẤY V1 — video của tôi — rồi bỏ qua vì đã có.
    # Đây là ca thật, không phải ca dựng: lọc trùng toàn kho bảo đảm nó xảy ra
    # mỗi lần hai người tìm chồng nguồn. Và nó là ca DUY NHẤT phân định được
    # `sources_for_videos`: nếu chỉ có video của họ mang từ khoá của họ thì
    # `list_videos` đã chặn từ trước, `sources_for_videos` không bao giờ được
    # hỏi về nó, và một bản vá quên lọc `nguon` vẫn xanh.
    models.record_sighting(db, video_id="1", job_id=job_ho,
                            nguon="https://www.tiktok.com/search?q=TU-KHOA-RIENG-CUA-HO",
                            da_tai=False)
    return db, job_toi, job_ho


def test_a_member_sees_only_videos_from_jobs_they_created(tmp_path, monkeypatch):
    """17/09 user đổi thư viện từ CHUNG sang RIÊNG: ai nhấn tải thì của người
    đó. Test này trước đây tên `..._returns_the_whole_team_catalogue` và khẳng
    định điều ngược lại — sửa tại chỗ chứ không xoá, để còn thấy dấu vết."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    _thu_vien_hai_nguoi(tmp_path, monkeypatch)

    out = app_mod.list_videos(nguoi_tao=TEST_USER)

    assert {v["video_id"] for v in out["videos"]} == {"1"}
    assert out["tong"] == 1, "`tong` phải đếm cùng bộ lọc, nếu không UI in số của cả kho"


def test_the_words_someone_else_typed_do_not_ride_along_in_sources(tmp_path, monkeypatch):
    """Không chỉ đếm hàng: `nguon` mang nguyên URL tìm kiếm của người khác.
    Lọc `list_videos` mà quên `sources_for_videos` thì vẫn rò."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    _thu_vien_hai_nguoi(tmp_path, monkeypatch)

    thay = json.dumps(app_mod.list_videos(nguoi_tao=TEST_USER), ensure_ascii=False)

    assert "BI-MAT-CUA-HO" not in thay, "video của họ lọt sang thư viện tôi"
    assert "TU-KHOA-RIENG-CUA-HO" not in thay, (
        "từ khoá họ gõ lọt ra qua `nguon` của MỘT video tôi cũng có — "
        "lọc list_videos mà quên sources_for_videos thì rò đúng ở đây")
    assert "cua-toi" in thay, "CA DƯƠNG: nguồn của chính tôi phải còn"


def test_an_admin_still_sees_the_whole_warehouse(tmp_path, monkeypatch):
    """CA DƯƠNG: thiếu nó thì một bản vá 'trả rỗng' vẫn xanh hai test trên."""
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    _thu_vien_hai_nguoi(tmp_path, monkeypatch)

    out = app_mod.list_videos(nguoi_tao="sep@astronex.ai")

    assert {v["video_id"] for v in out["videos"]} == {"1", "2"}
    assert out["tong"] == 2


def test_the_three_library_queries_refuse_to_guess_who_is_asking():
    """Hàm quyết định "ai thấy gì" không được có mặc định im lặng (luật repo,
    sinh ra sau khi `prepare_data_dir` có mặc định trỏ vào production). Quên
    truyền `chi_cua` phải là TypeError, không phải là thư viện của cả kho."""
    import inspect

    for ham in (models.list_videos, models.count_videos, models.sources_for_videos):
        tham_so = inspect.signature(ham).parameters["chi_cua"]
        assert tham_so.default is inspect.Parameter.empty, (
            f"{ham.__name__} có mặc định cho chi_cua — người gọi quên sẽ không ai biết")


def test_the_library_is_newest_first(tmp_path, monkeypatch):
    """Bàn giao 16/09 ghi `list_videos` không có test nào canh `ORDER BY` —
    bỏ nó đi thì lưới lộn ngược mà không ai kêu."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job = models.create_job(db, "https://www.tiktok.com/tag/x", 5, TEST_USER)
    for vid, luc in [("cu", "2026-09-01T00:00:00+00:00"),
                     ("giua", "2026-09-10T00:00:00+00:00"),
                     ("moi", "2026-09-17T00:00:00+00:00")]:
        models.record_video(db, job_id=job, video_id=vid, url="u")
        with models._connect(db) as conn:
            conn.execute("UPDATE videos SET tao_luc = ? WHERE video_id = ?", (luc, vid))

    out = app_mod.list_videos(nguoi_tao=TEST_USER)

    assert [v["video_id"] for v in out["videos"]] == ["moi", "giua", "cu"]


def test_videos_endpoint_includes_sources_from_sightings(tmp_path, monkeypatch):
    """ĐỘT BIẾN: bỏ nối `models.sources_for_videos` vào `list_videos` (app.py)
    ⇒ ĐỎ (KeyError trên `video["nguon"]`, đo tay 15/09 — xem báo cáo)."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job = models.create_job(db, "https://www.tiktok.com/tag/abc", 5, TEST_USER)
    models.record_video(db, job_id=job, video_id="1", url="u1")
    models.record_sighting(db, video_id="1", job_id=job,
                            nguon="https://www.tiktok.com/tag/abc", da_tai=True)
    models.record_sighting(db, video_id="1", job_id=job,
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
    job = models.create_job(db, "https://www.tiktok.com/tag/x", 5, TEST_USER)
    models.record_video(db, job_id=job, video_id="2", url="u2")

    out = app_mod.list_videos(nguoi_tao=TEST_USER)

    video = next(v for v in out["videos"] if v["video_id"] == "2")
    assert video["nguon"] == []


def test_videos_endpoint_queries_sources_once_for_the_whole_page(tmp_path, monkeypatch):
    """Chặn N+1: `sources_for_videos` phải được gọi ĐÚNG MỘT LẦN cho cả trang
    (một mảng video_id), không phải một lần mỗi video."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job = models.create_job(db, "https://www.tiktok.com/tag/x", 5, TEST_USER)
    for i in range(5):
        models.record_video(db, job_id=job, video_id=str(i), url=f"u{i}")

    calls = []
    real_sources_for_videos = models.sources_for_videos

    def _counting(db_path, video_ids, chi_cua):
        calls.append(list(video_ids))
        return real_sources_for_videos(db_path, video_ids, chi_cua)

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
    assert len(models.list_jobs(db_path, None)) == lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY, \
        "lượt bị trần chặn không được để lại hàng job ma"


def test_create_job_allows_every_job_up_to_the_cap(tmp_path, monkeypatch):
    """Ca dương bắt buộc: nếu trần chặn sớm hơn một lượt thì test trên vẫn
    xanh, vì nó chỉ hỏi 'có chặn không', không hỏi 'chặn đúng chỗ không'."""
    db_path = _cap_env(tmp_path, monkeypatch)
    for _ in range(lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY):
        app_mod.create_job(_payload(), nguoi_tao=TEST_USER)

    assert len(models.list_jobs(db_path, None)) == lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY


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


def test_an_absurdly_long_video_id_is_refused_not_crashed(tmp_path, monkeypatch):
    """`.isdigit()` chặn traversal nhưng KHÔNG chặn hệ tệp: một id 300 chữ số
    đi qua cổng rồi làm `is_file()` ném OSError 'File name too long' — lỗi
    không có biên trên endpoint đã qua xác thực, client nhận 500."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    # Thư mục ảnh PHẢI tồn tại — như trên mini, nơi đã có ảnh. Thiếu nó thì hệ
    # tệp trả ENOENT trước khi kịp than tên quá dài, `is_file()` nuốt thành
    # False, và test đi qua một đường KHÁC đường của máy thật: đo sai điều kiện
    # thì kết quả xanh không nói được gì.
    lifecycle.thumbs_dir_for(db_path).mkdir(parents=True, exist_ok=True)

    with pytest.raises(HTTPException) as exc_info:
        app_mod.get_thumb("9" * 300, nguoi_tao=TEST_USER)

    assert exc_info.value.status_code == 404, "phải là 404 có kiểm soát, không phải OSError"


def test_a_normal_video_id_still_reaches_the_lookup(tmp_path, monkeypatch):
    """Ca dương: trần độ dài không được chặn nhầm id thật (19 chữ số)."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)

    with pytest.raises(HTTPException) as exc_info:
        app_mod.get_thumb("7685840805507910932", nguoi_tao=TEST_USER)

    # 404 vì chưa có ảnh, nhưng phải là 404 của "chưa có ảnh" chứ không phải
    # của "id không hợp lệ" — hai ca khác nhau đi qua cùng mã trạng thái.
    assert "chưa có ảnh" in exc_info.value.detail


# ---------------------------------------------------------------------------
# /jobs — mỗi người CHỈ thấy lượt của mình; admin thấy hết.
#
# User chốt 16/09 khi chuẩn bị mở cho cả team, THU HẸP chốt #7 (vốn mở hàng đợi
# cho cả team). Hàng job mang URL người khác tìm gì, email của họ, và mã trạng
# thái cookie cá nhân (hết hạn / chưa đăng nhập).
#
# Lọc phải ở API, không ở giao diện: ẩn trên màn hình mà API vẫn trả thì bất kỳ
# ai mở tab mạng của trình duyệt cũng đọc được.
#
# ĐỘT BIẾN: bỏ lọc trong route (`models.list_jobs(DB_PATH, None)`) ⇒ ca âm ĐỎ.
# ---------------------------------------------------------------------------

def _hai_nguoi(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    a = models.create_job(db_path, "https://www.tiktok.com/tag/cua-A", 5, "a@astronex.ai")
    b = models.create_job(db_path, "https://www.tiktok.com/tag/BI-MAT-CUA-B", 5, "b@astronex.ai")
    models.set_job_stop_reason(db_path, b, "cookie_het_han")
    return db_path, a, b


def test_a_user_sees_only_their_own_jobs(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db_path, job_a, job_b = _hai_nguoi(tmp_path, monkeypatch)

    thay = app_mod.list_jobs(nguoi_tao="a@astronex.ai")

    assert [j["id"] for j in thay] == [job_a]


def test_nothing_of_the_other_person_survives_in_the_response(tmp_path, monkeypatch):
    """Không chỉ đếm hàng: ba thứ cụ thể phải BIẾN MẤT khỏi phản hồi — email,
    URL họ tìm gì, và mã trạng thái cookie cá nhân của họ."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db_path, _, _ = _hai_nguoi(tmp_path, monkeypatch)

    thay = json.dumps(app_mod.list_jobs(nguoi_tao="a@astronex.ai"), ensure_ascii=False)

    assert "b@astronex.ai" not in thay, "email người khác lọt ra"
    assert "BI-MAT-CUA-B" not in thay, "URL người khác lọt ra"
    assert "cookie_het_han" not in thay, "trạng thái cookie người khác lọt ra"


def test_an_admin_sees_everyone(tmp_path, monkeypatch):
    """CA DƯƠNG: thiếu nó thì một bản vá 'chặn tất' vẫn xanh hai test trên
    trong khi đã làm admin mù hoàn toàn."""
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    db_path, job_a, job_b = _hai_nguoi(tmp_path, monkeypatch)

    thay = app_mod.list_jobs(nguoi_tao="sep@astronex.ai")

    assert sorted(j["id"] for j in thay) == sorted([job_a, job_b])


def test_someone_elses_job_is_not_readable_one_id_at_a_time(tmp_path, monkeypatch):
    """Lọc danh sách mà để ngỏ đường đọc từng id thì chưa lọc gì cả. Id tự
    tăng, nên đếm lên là ra job người khác."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db_path, job_a, job_b = _hai_nguoi(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as bat:
        app_mod.get_job(job_id=job_b, nguoi_tao="a@astronex.ai")

    assert bat.value.status_code == 404, "403 tự nó khai job kia có tồn tại"


def test_my_own_job_is_still_readable(tmp_path, monkeypatch):
    """CA DƯƠNG. Thiếu nó thì một bản vá 'từ chối tất' vẫn xanh test trên,
    trong khi đã làm hỏng chính đường người dùng đang dùng."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db_path, job_a, _ = _hai_nguoi(tmp_path, monkeypatch)

    assert app_mod.get_job(job_id=job_a, nguoi_tao="a@astronex.ai")["id"] == job_a


def test_an_admin_can_read_any_job(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    db_path, _, job_b = _hai_nguoi(tmp_path, monkeypatch)

    assert app_mod.get_job(job_id=job_b, nguoi_tao="sep@astronex.ai")["id"] == job_b


def test_the_progress_stream_checks_the_owner_before_it_streams(tmp_path, monkeypatch):
    """Cửa phải đóng TRƯỚC khi mở luồng. Đóng sau thì byte đầu đã ra rồi."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db_path, _, job_b = _hai_nguoi(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as bat:
        asyncio.run(app_mod.job_events(job_id=job_b, nguoi_tao="a@astronex.ai"))

    assert bat.value.status_code == 404


def test_the_admin_list_tolerates_spacing_and_case(tmp_path, monkeypatch):
    """Danh sách admin do người gõ tay vào tệp env. Một khoảng trắng thừa
    không được âm thầm biến admin thành người thường."""
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", " SEP@Astronex.ai , ai-do@x.com ")
    db_path, job_a, job_b = _hai_nguoi(tmp_path, monkeypatch)

    assert len(app_mod.list_jobs(nguoi_tao="sep@astronex.ai")) == 2


def test_an_empty_admin_list_makes_nobody_admin(tmp_path, monkeypatch):
    """Mặc định an toàn: env rỗng/thiếu ⇒ KHÔNG AI thấy hết. Mặc định sai ở đây
    nghĩa là phơi hàng đợi của mọi người."""
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "")
    db_path, job_a, _ = _hai_nguoi(tmp_path, monkeypatch)

    assert [j["id"] for j in app_mod.list_jobs(nguoi_tao="a@astronex.ai")] == [job_a]
