"""Tests for web/app.py's `POST /jobs` gate wiring (Bước 4/5 of the fix
chain). Calls the route function directly — `create_job` is a plain Python
function under the FastAPI decorator, callable without an HTTP client or the
`httpx` test-client dependency this venv does not have installed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from pathlib import Path

import pytest
from fastapi import HTTPException

from web import app as app_mod
from web import lifecycle
from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from web import cookies
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
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    job = models.create_job(db, "https://www.tiktok.com/tag/x", 5, TEST_USER)
    models.record_video(db, job_id=job, video_id="7001", url="u")
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


# ===========================================================================
# Trang "Cookie của tôi" — P3
# ===========================================================================

BI_MAT = "SECRET-TOKEN-XYZ"


def _jar_hop_le(gia_tri: str = BI_MAT) -> str:
    """Một jar Cookie-Editor tối thiểu mà `ly_do_jar_khong_dung_duoc` chấp
    nhận: có `sessionid`, hạn ở tương lai xa."""
    return json.dumps([{"name": "sessionid", "value": gia_tri,
                        "domain": ".tiktok.com", "path": "/",
                        "expires": 4102444800}])


def _san_cookie(tmp_path, monkeypatch):
    """Sân thật: thư mục cookies + thư mục tạm riêng cho mỗi test."""
    from tiktok_music_downloader import downloader as dl

    cookies_dir = tmp_path / "cookies"
    tmp_dir = tmp_path / "tmp"
    cookies_dir.mkdir()
    tmp_dir.mkdir()
    monkeypatch.setattr(app_mod, "COOKIES_DIR", cookies_dir)
    monkeypatch.setattr(dl, "COOKIE_TMP_DIR", str(tmp_dir))
    monkeypatch.setattr(app_mod, "DB_PATH", tmp_path / "jobs.db")
    models.init_db(tmp_path / "jobs.db")
    return cookies_dir, tmp_dir


def test_a_pasted_jar_lands_where_the_job_path_will_look_for_it(tmp_path, monkeypatch):
    """Phép nối, không phải "tệp có trên đĩa": thứ duy nhất đáng khẳng định là
    `cookies_path_for_user` — hàm đường job dùng — tìm thấy đúng tệp vừa ghi."""
    cookies_dir, _ = _san_cookie(tmp_path, monkeypatch)

    out = app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le()),
                                nguoi_tao=TEST_USER)

    assert out["co_jar"] is True and out["trang_thai"] == "dung_duoc"
    tim_thay = cookies.cookies_path_for_user(cookies_dir, TEST_USER)
    assert tim_thay is not None, "đường job không thấy jar vừa dán"
    assert Path(tim_thay) == cookies.cookie_jar_path(cookies_dir, TEST_USER)


def test_the_jar_is_not_readable_by_the_other_accounts_on_this_machine(
        tmp_path, monkeypatch):
    """Mini là máy dùng chung (có user `autotest` của đội khác). Mode phải
    0600 ngay từ byte đầu, không phải chmod sau khi ghi."""
    cookies_dir, _ = _san_cookie(tmp_path, monkeypatch)
    monkeypatch.setattr(os, "umask", lambda m: 0o022)

    app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le()), nguoi_tao=TEST_USER)

    mode = cookies.cookie_jar_path(cookies_dir, TEST_USER).stat().st_mode
    assert mode & 0o077 == 0, f"jar mở cho người khác đọc: {stat.filemode(mode)}"


def test_a_broken_paste_does_not_replace_a_working_jar(tmp_path, monkeypatch):
    """Ca đắt nhất: đang có jar chạy được, dán nhầm bản RTF. Nếu ghi thẳng vào
    đích thì mất cookie đang dùng được vì một cú dán hỏng."""
    cookies_dir, tmp_dir = _san_cookie(tmp_path, monkeypatch)
    app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le()), nguoi_tao=TEST_USER)

    with pytest.raises(HTTPException) as bat:
        app_mod.put_my_cookie(app_mod.CookieBody(json=r"{\rtf1\ansi cookie"),
                              nguoi_tao=TEST_USER)

    assert bat.value.detail in cookies.MA_LOI_COOKIE
    con = cookies.cookies_path_for_user(cookies_dir, TEST_USER)
    assert con is not None, "jar đang dùng được đã bị cú dán hỏng xoá mất"
    assert cookies.ly_do_jar_khong_dung_duoc(con) is None
    assert list(tmp_dir.iterdir()) == [], "còn sót jar tạm đọc được trên đĩa"


def test_no_byte_of_the_jar_comes_back_out(tmp_path, monkeypatch, caplog):
    """Không một ký tự nào của tệp được ra ngoài — kể cả khi jar hỏng."""
    cookies_dir, _ = _san_cookie(tmp_path, monkeypatch)
    caplog.set_level(logging.DEBUG)

    tra_ve = app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le()),
                                   nguoi_tao=TEST_USER)
    tra_ve_str = json.dumps(tra_ve, ensure_ascii=False) + caplog.text

    assert BI_MAT not in tra_ve_str
    # CA DƯƠNG, cùng phép grep, cùng điều kiện: chuỗi ấy CÓ trong tệp trên đĩa.
    # Thiếu nó thì phép trên xanh cả khi tôi grep nhầm một chuỗi không tồn tại.
    tren_dia = Path(cookies.cookies_path_for_user(cookies_dir, TEST_USER)).read_text()
    assert BI_MAT in tren_dia


def test_my_jar_is_not_someone_elses(tmp_path, monkeypatch):
    """Khoá cấu tạo: A dán thì B vẫn là chưa có jar."""
    _san_cookie(tmp_path, monkeypatch)
    app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le()), nguoi_tao=TEST_USER)

    assert app_mod.get_my_cookie(nguoi_tao="nguoikhac@astronex.ai")["co_jar"] is False
    assert app_mod.get_my_cookie(nguoi_tao=TEST_USER)["co_jar"] is True


def test_deleting_my_cookie_puts_me_back_to_anonymous(tmp_path, monkeypatch):
    cookies_dir, _ = _san_cookie(tmp_path, monkeypatch)
    app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le()), nguoi_tao=TEST_USER)

    app_mod.delete_my_cookie(nguoi_tao=TEST_USER)

    assert cookies.cookies_path_for_user(cookies_dir, TEST_USER) is None
    assert app_mod.get_my_cookie(nguoi_tao=TEST_USER)["co_jar"] is False


def test_deleting_a_cookie_that_was_never_there_is_not_an_error(tmp_path, monkeypatch):
    _san_cookie(tmp_path, monkeypatch)
    app_mod.delete_my_cookie(nguoi_tao=TEST_USER)


def test_quota_counts_the_same_jobs_the_gate_counts(tmp_path, monkeypatch):
    """Trang hạn mức phải đếm ĐÚNG thứ cổng chặn đếm.

    Đo bằng SQL độc lập chứ không so với chính hàm đang test — so một hàm với
    chính nó thì bản vá nào cũng xanh. Nếu hai bên lệch, người dùng thấy
    "còn 18 lượt" đúng lúc cổng trả 429 và không có cách nào biết bên nào đúng.
    """
    cookies_dir, _ = _san_cookie(tmp_path, monkeypatch)
    db = tmp_path / "jobs.db"
    for _ in range(3):
        models.create_job(db, "https://www.tiktok.com/tag/x", 7, TEST_USER)

    out = app_mod.my_quota(nguoi_tao=TEST_USER)

    with models._connect(db) as conn:
        that = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE nguoi_tao = ?", (TEST_USER,)
        ).fetchone()[0]
    assert out["luot_tai"]["da_dung"] == that == 3
    assert out["luot_tai"]["tran"] == lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY
    assert out["an_danh"] is True, "chưa dán cookie thì phải nói là đang ẩn danh"


def test_quota_says_you_are_no_longer_anonymous_once_you_paste(tmp_path, monkeypatch):
    """CA DƯƠNG cho cờ `an_danh` — thiếu nó thì một bản vá trả `True` cứng
    vẫn xanh test trên, và người đã dán cookie vẫn bị bảo là đang ẩn danh."""
    _san_cookie(tmp_path, monkeypatch)
    app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le()), nguoi_tao=TEST_USER)

    assert app_mod.my_quota(nguoi_tao=TEST_USER)["an_danh"] is False


def test_me_tells_the_page_who_it_is_talking_to(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    db = tmp_path / "jobs.db"
    models.init_db(db)
    _moi_admin(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)

    assert app_mod.me(nguoi_tao=TEST_USER) == {"email": TEST_USER, "la_admin": False}
    assert app_mod.me(nguoi_tao="sep@astronex.ai")["la_admin"] is True


def test_visiting_the_page_puts_you_in_the_directory(tmp_path, monkeypatch):
    """Bảng người dùng phải thấy người CHƯA tạo job nào.

    Danh tính chỉ sống ở `jobs.nguoi_tao` và tên tệp cookie `sha256(email)`
    (một chiều) — nên không ghi lúc đăng nhập thì trang Quản trị chỉ thấy
    người đã tải, đúng lúc admin cần thấy người mới để đặt trần cho họ.
    """
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db = tmp_path / "jobs.db"
    models.init_db(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)

    assert models.danh_sach_nguoi_dung(db) == []
    app_mod.me(nguoi_tao="nguoimoi@astronex.ai")

    ds = models.danh_sach_nguoi_dung(db)
    assert [u["email"] for u in ds] == ["nguoimoi@astronex.ai"]
    assert ds[0]["la_admin"] == 0, "vào trang không tự làm ai thành admin"


# Route nào được phép KHÔNG kiểm quyền sở hữu, và vì sao. Danh sách này là
# cái phải sửa khi thêm route — không phải một danh sách route-có-kiểm gõ tay,
# vì danh sách kiểu đó im lặng khi ai đó quên thêm vào.
# Khoá theo "METHOD /đường-dẫn", KHÔNG theo đường dẫn trần.
#
# Bản trước khoá theo đường dẫn, và đó là một LƯỚI GIẢ đo được 18/09: thêm
# `DELETE /jobs/{job_id}` vào một đường dẫn ĐÃ CÓ `GET` thì tập đường dẫn
# không đổi một phần tử nào ⇒ suite xanh trọn cho một route ghi hoàn toàn
# mới. Tệ hơn: suất miễn trừ của `/jobs/{job_id}` được cấp vì GET đi qua
# `_job_cua_toi_hoac_404`, rồi nó che luôn cho một DELETE không đi qua hàm
# đó. Một lưới mà cách qua mặt là "dùng lại đường dẫn cũ" thì nó canh tên
# route, không canh quyền.
KHONG_CAN_KIEM_CHU = {
    "GET /healthz": "thăm dò, không đọc dữ liệu của ai",
    "GET /jobs": "trả danh sách, tự lọc bên trong `models.list_jobs`",
    "POST /jobs": "tạo cho chính người đang gọi",
    "GET /videos": "trả danh sách, tự lọc bên trong `models.list_videos`",
    "GET /me": "chính người đang gọi",
    "GET /me/cookie": "chính người đang gọi",
    "PUT /me/cookie": "chính người đang gọi",
    "DELETE /me/cookie": "chính người đang gọi",
    "GET /me/quota": "chính người đang gọi",
    "GET /admin/nguoi-dung": "require_admin — 403 cho người thường",
    "GET /admin/nguoi-dung/{email}": "require_admin — 403 cho người thường",
    "PUT /admin/nguoi-dung/{email}": "require_admin — 403 cho người thường",
    "POST /videos/loai": "nhận danh sách id, tự lọc quyền sở hữu trong `models.video_de_loai`",
    "GET /cum": "trả danh sách, tự lọc `chu` bên trong `models_cum.liet_ke_cum`",
    "POST /cum": "tạo cho chính người đang gọi",
    "PATCH /cum/{cum_id}": "`models_cum.doi_kieu` ràng `chu` NGAY trong câu SELECT/UPDATE; "
                           "404 cho cụm người khác (tests/test_web_cum.py)",
    "DELETE /cum/{cum_id}": "`models_cum.xoa_cum` ràng `chu` NGAY trong câu DELETE; 404",
    "POST /cum/{cum_id}/video": "`models_cum.gan_video/go_video` ràng `chu` cho cụm VÀ "
                                "lọc quyền sở hữu video trong SQL; 404",
    "POST /cum/{cum_id}/lo/{thu}/da-mo": "`_cum_hoac_404` + `models_cum.ghi_lo_da_mo` "
                                         "ràng `chu` trong INSERT … SELECT; 404",
    "DELETE /jobs/{job_id}": "`models.huy_job_dang_cho` ràng `nguoi_tao` NGAY "
                             "trong câu UPDATE, nên không cần cổng ngoài; "
                             "404 cho job người khác, giống GET",
}


def test_every_route_that_takes_an_id_checks_who_is_asking():
    """Lưới cho route TƯƠNG LAI, không phải cho route hôm nay.

    Hai test canh cũ liệt kê tay tên route có `require_user`; đột biến đo được:
    thêm một route mới có `require_user` nhưng quên kiểm chủ ⇒ suite vẫn XANH
    TRỌN. Danh sách gõ tay không thể đỏ cho thứ chưa ai gõ vào nó.

    Test này lật chiều: duyệt `app.routes` thật, và bắt mọi route phải nằm
    trong danh sách khai báo ở trên. Route mới ⇒ ĐỎ cho tới khi người viết
    khai nó thuộc loại nào.
    """
    from fastapi.routing import APIRoute

    duong_dan = {
        f"{method} {r.path}"
        for r in app_mod.app.routes if isinstance(r, APIRoute)
        for method in r.methods if method != "HEAD"
    }
    chua_khai = duong_dan - set(KHONG_CAN_KIEM_CHU) - {
        "GET /jobs/{job_id}",
        "GET /jobs/{job_id}/events",
        "GET /thumbs/{video_id}",
    }
    assert not chua_khai, (
        f"route chưa khai: {sorted(chua_khai)} — hoặc cho nó qua "
        f"`_job_cua_toi_hoac_404`, hoặc thêm vào KHONG_CAN_KIEM_CHU kèm lý do")


def test_every_route_demands_a_verified_user():
    """`require_user` là cửa ngoài. Route quên nó thì mở cho cả internet."""
    from fastapi.routing import APIRoute

    thieu = []
    for r in app_mod.app.routes:
        if not isinstance(r, APIRoute) or r.path == "/healthz":
            continue
        ten_tham_so = set(r.dependant.query_params + r.dependant.path_params)
        # `require_admin` hợp lệ vì nó BỌC `require_user` — nhưng chuỗi đó phải
        # được chứng minh (khẳng định dưới cùng), không phải được giả định.
        cua_hop_le = {require_user, app_mod.require_admin}
        co_require = any(d.call in cua_hop_le for d in r.dependant.dependencies)
        if not co_require:
            thieu.append(r.path)
    assert not thieu, f"route không đòi người dùng đã xác thực: {sorted(thieu)}"

    # Chứng minh chuỗi: `require_admin` thật sự đi qua `require_user`. Thiếu
    # khẳng định này thì việc chấp nhận `require_admin` ở trên là một giả định,
    # và một ngày nào đó ai đó gỡ `Depends(require_user)` khỏi nó mà lưới vẫn xanh.
    import inspect
    assert any(v.default.dependency is require_user
               for v in inspect.signature(app_mod.require_admin).parameters.values()
               if hasattr(v.default, "dependency")), \
        "require_admin không còn đi qua require_user — cửa ngoài đã mất"


def _thu_vien_hai_nguoi(tmp_path, monkeypatch):
    """Kho chung, hai chủ: V1 do TEST_USER tải, V2 do người khác.

    `nguon` của V2 cố ý là một URL tìm kiếm mang từ khoá — đó là thứ cùng hạng
    với `jobs.url`, và là lý do `sources_for_videos` phải lọc chứ không chỉ
    `list_videos`.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    _moi_admin(db)
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


class _UploaderGia:
    """Uploader giả: đếm lời gọi trash và cho phép ép trượt.

    `trash_file` trả đúng `UploadResult` như bản thật, nên test đi qua CÙNG
    nhánh phân loại kết quả mà production đi — một stub trả `True/False` sẽ
    bỏ qua đúng chỗ dễ sai nhất.
    """

    def __init__(self, truot=()):
        self.da_trash = []
        self._truot = set(truot)

    def is_configured(self):
        return True

    def upload_file(self, path, parent_folder_id=None):
        raise AssertionError("test này không đụng đường tải lên")

    def create_job_folder(self, job_id):
        raise AssertionError("test này không đụng đường tải lên")

    def trash_file(self, file_id):
        self.da_trash.append(file_id)
        if file_id in self._truot:
            return UploadResult(outcome=UploadOutcome.FAILED, reason="ép trượt")
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=file_id)


def _kho_hai_nguoi(tmp_path, monkeypatch, truot=()):
    db, job_toi, job_ho = _thu_vien_hai_nguoi(tmp_path, monkeypatch)
    with models._connect(db) as conn:
        conn.execute("UPDATE videos SET drive_file_id = 'drive-' || video_id")
    gia = _UploaderGia(truot=truot)
    lifecycle.set_uploader(gia)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    return db, gia


def test_removing_a_video_takes_it_out_of_my_library_only(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db, gia = _kho_hai_nguoi(tmp_path, monkeypatch)

    out = app_mod.loai_video(app_mod.LoaiVideoRequest(video_ids=["1"]),
                              nguoi_tao=TEST_USER)

    assert out["da_loai"] == ["1"] and out["drive_truot"] == []
    assert gia.da_trash == ["drive-1"], "tệp phải được đưa vào thùng rác"
    assert app_mod.list_videos(nguoi_tao=TEST_USER)["videos"] == []
    # Người kia KHÔNG bị ảnh hưởng — đây là toàn bộ điểm của "loại là việc riêng".
    assert {v["video_id"] for v in
            app_mod.list_videos(nguoi_tao="ho@astronex.ai")["videos"]} == {"2"}


def test_a_removed_video_is_still_counted_as_already_in_the_warehouse(
        tmp_path, monkeypatch):
    """Lọc trùng KHÔNG được quên video đã loại. Quên là lượt quét sau tải lại
    đúng thứ chủ vừa dọn — tốn một lượt TikTok và dựng lại rác."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db, _ = _kho_hai_nguoi(tmp_path, monkeypatch)

    app_mod.loai_video(app_mod.LoaiVideoRequest(video_ids=["1"]), nguoi_tao=TEST_USER)

    assert models.known_video_ids(db, ["1"]) == {"1"}


def test_i_cannot_remove_someone_elses_video(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db, gia = _kho_hai_nguoi(tmp_path, monkeypatch)

    out = app_mod.loai_video(app_mod.LoaiVideoRequest(video_ids=["2"]),
                              nguoi_tao=TEST_USER)

    assert out["da_loai"] == [] and out["khong_phai_cua_ban"] == ["2"]
    assert gia.da_trash == [], "không được chạm Drive cho video của người khác"
    assert {v["video_id"] for v in
            app_mod.list_videos(nguoi_tao="ho@astronex.ai")["videos"]} == {"2"}


def test_a_failed_trash_leaves_the_video_where_it_was(tmp_path, monkeypatch):
    """Ca đắt nhất: Drive trượt. Ghi mốc trước rồi trượt ⇒ video biến khỏi thư
    viện trong khi tệp còn nguyên, và KHÔNG CÓ GÌ BÁO. Phải thà ồn còn hơn."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db, gia = _kho_hai_nguoi(tmp_path, monkeypatch, truot=["drive-1"])

    out = app_mod.loai_video(app_mod.LoaiVideoRequest(video_ids=["1"]),
                              nguoi_tao=TEST_USER)

    assert out["drive_truot"] == ["1"] and out["da_loai"] == []
    assert {v["video_id"] for v in
            app_mod.list_videos(nguoi_tao=TEST_USER)["videos"]} == {"1"}, \
        "video phải còn trong thư viện để chủ thấy và bấm lại"


def test_removing_more_than_the_cap_is_refused(tmp_path, monkeypatch):
    _kho_hai_nguoi(tmp_path, monkeypatch)
    with pytest.raises(Exception):
        app_mod.LoaiVideoRequest(video_ids=[str(i) for i in range(51)])


def test_a_thumbnail_of_someone_elses_video_is_a_404(tmp_path, monkeypatch):
    """Cặp 200/404 của `/thumbs` là một câu trả lời: "team đã tải video này
    chưa". Id thật thì CHÍNH tool này phát ra hàng loạt
    (`hashtag_enumerator.py:165` trích `video_id` cho mọi item của một feed),
    nên "id 19 chữ số khó đoán" không phải lớp bảo vệ — kẻ hỏi không đoán."""
    monkeypatch.delenv("VIDEODL_ADMIN_EMAILS", raising=False)
    db, _, job_ho = _thu_vien_hai_nguoi(tmp_path, monkeypatch)
    thumb = lifecycle.thumb_path_for(db, "2")
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"RIFF....WEBP")

    with pytest.raises(HTTPException) as bat:
        app_mod.get_thumb("2", nguoi_tao=TEST_USER)

    assert bat.value.status_code == 404
    # CA DƯƠNG cùng điều kiện: ảnh CÓ trên đĩa và chủ của nó lấy được. Thiếu
    # nó thì một bản vá "404 tất" cũng xanh, và thư viện mất sạch ảnh.
    thumb1 = lifecycle.thumb_path_for(db, "1")
    thumb1.write_bytes(b"RIFF....WEBP")
    assert app_mod.get_thumb("1", nguoi_tao=TEST_USER).media_type == "image/webp"


def test_an_admin_can_see_any_thumbnail(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    db, _, _ = _thu_vien_hai_nguoi(tmp_path, monkeypatch)
    thumb = lifecycle.thumb_path_for(db, "2")
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"RIFF....WEBP")

    assert app_mod.get_thumb("2", nguoi_tao="sep@astronex.ai").media_type == "image/webp"


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

def _moi_admin(db_path):
    """Làm đúng thứ `_lifespan` làm lúc khởi động: mồi bảng admin từ env.

    Không có bước này thì test set `VIDEODL_ADMIN_EMAILS` rồi đo một bảng
    rỗng — tức đo một hệ thống chưa khởi động xong, và mọi ca dương admin sẽ
    đỏ vì lý do sai.
    """
    from web.auth import admin_tu_env
    models.moi_admin_tu_env(db_path, admin_tu_env())


def _hai_nguoi(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    _moi_admin(db_path)
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


# ===========================================================================
# Trang Quản trị — T2.1
# ===========================================================================

def _san_admin(tmp_path, monkeypatch):
    """Sân: SEP là admin (mồi từ env), NHANVIEN là người thường."""
    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    db = tmp_path / "jobs.db"
    models.init_db(db)
    _moi_admin(db)
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "COOKIES_DIR", tmp_path / "cookies")
    (tmp_path / "cookies").mkdir(exist_ok=True)
    app_mod.me(nguoi_tao=TEST_USER)          # người thường ghé qua → vào danh bạ
    return db


def test_a_member_cannot_open_the_admin_page(tmp_path, monkeypatch):
    """403 ở SERVER, không phải giấu nút. Giấu nút không phải phân quyền —
    người thường vẫn gọi thẳng API được."""
    _san_admin(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as bat:
        app_mod.require_admin(nguoi_tao=TEST_USER)
    assert bat.value.status_code == 403

    # CA DƯƠNG: admin vào được. Thiếu nó thì bản vá "403 tất" vẫn xanh.
    assert app_mod.require_admin(nguoi_tao="sep@astronex.ai") == "sep@astronex.ai"


def test_the_admin_list_shows_people_who_only_logged_in(tmp_path, monkeypatch):
    db = _san_admin(tmp_path, monkeypatch)

    out = app_mod.admin_liet_ke(nguoi_tao="sep@astronex.ai")

    emails = {u["email"] for u in out["nguoi_dung"]}
    assert TEST_USER in emails, "người mới đăng nhập phải có trong danh bạ"
    assert out["tran_mac_dinh"]["luot"] == lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY


def test_granting_admin_takes_effect_immediately(tmp_path, monkeypatch):
    db = _san_admin(tmp_path, monkeypatch)
    assert app_mod._la_admin(TEST_USER) is False

    app_mod.admin_cap_nhat(email=TEST_USER,
                            body=app_mod.CapNhatNguoiDung(la_admin=True),
                            nguoi_tao="sep@astronex.ai")

    assert app_mod._la_admin(TEST_USER) is True
    # Truy được ai đã cấp — một bảng phân quyền không có vết thì không trả lời
    # được câu duy nhất người ta sẽ hỏi nó khi có chuyện.
    hang = next(u for u in models.danh_sach_nguoi_dung(db) if u["email"] == TEST_USER)
    assert hang["cap_boi"] == "sep@astronex.ai"


def test_the_last_admin_cannot_remove_themselves(tmp_path, monkeypatch):
    """Bỏ hết admin thì không còn ai vào được trang này để phong lại — đường
    duy nhất còn lại là gõ shell trên máy thật rồi khởi động lại dịch vụ. Một
    giao diện cho phép tự khoá mình ra ngoài là cái bẫy, không phải tuỳ chọn."""
    _san_admin(tmp_path, monkeypatch)

    with pytest.raises(HTTPException) as bat:
        app_mod.admin_cap_nhat(email="sep@astronex.ai",
                                body=app_mod.CapNhatNguoiDung(la_admin=False),
                                nguoi_tao="sep@astronex.ai")
    assert bat.value.status_code == 409
    assert app_mod._la_admin("sep@astronex.ai") is True


def test_an_admin_can_step_down_once_someone_else_is_admin(tmp_path, monkeypatch):
    """CA DƯƠNG cho khoá trên: khoá phải chặn ĐÚNG ca cuối cùng, không phải
    chặn mọi lượt bỏ quyền."""
    _san_admin(tmp_path, monkeypatch)
    app_mod.admin_cap_nhat(email=TEST_USER,
                            body=app_mod.CapNhatNguoiDung(la_admin=True),
                            nguoi_tao="sep@astronex.ai")

    app_mod.admin_cap_nhat(email="sep@astronex.ai",
                            body=app_mod.CapNhatNguoiDung(la_admin=False),
                            nguoi_tao="sep@astronex.ai")

    assert app_mod._la_admin("sep@astronex.ai") is False
    assert app_mod._la_admin(TEST_USER) is True


def test_a_cap_cannot_be_raised_past_the_hard_ceiling(tmp_path, monkeypatch):
    """Trang quản trị không được thành cửa tắt lưới. Ai cần vượt trần cứng thì
    phải đụng code, tức phải có người soát."""
    _san_admin(tmp_path, monkeypatch)

    with pytest.raises(Exception):
        app_mod.CapNhatNguoiDung(tran_luot=app_mod.MAX_TRAN_LUOT + 1)
    # CA DƯƠNG: ngay dưới trần thì nhận.
    assert app_mod.CapNhatNguoiDung(tran_luot=app_mod.MAX_TRAN_LUOT).tran_luot \
        == app_mod.MAX_TRAN_LUOT


def test_editing_someone_who_never_logged_in_is_a_404(tmp_path, monkeypatch):
    _san_admin(tmp_path, monkeypatch)
    with pytest.raises(HTTPException) as bat:
        app_mod.admin_cap_nhat(email="chua-tung-vao@x.com",
                                body=app_mod.CapNhatNguoiDung(la_admin=True),
                                nguoi_tao="sep@astronex.ai")
    assert bat.value.status_code == 404


def test_env_seeds_only_when_no_admin_exists(tmp_path, monkeypatch):
    """"Một lần" định nghĩa bằng TRẠNG THÁI, không bằng cờ. Nếu env thắng mãi
    thì admin cấp từ env không bỏ được ở giao diện, và nút "Bỏ quyền admin"
    thành nút bấm-không-làm-gì."""
    db = _san_admin(tmp_path, monkeypatch)
    app_mod.admin_cap_nhat(email=TEST_USER,
                            body=app_mod.CapNhatNguoiDung(la_admin=True),
                            nguoi_tao="sep@astronex.ai")
    app_mod.admin_cap_nhat(email="sep@astronex.ai",
                            body=app_mod.CapNhatNguoiDung(la_admin=False),
                            nguoi_tao="sep@astronex.ai")

    from web.auth import admin_tu_env
    assert models.moi_admin_tu_env(db, admin_tu_env()) == 0, "đã có admin thì KHÔNG mồi lại"
    assert app_mod._la_admin("sep@astronex.ai") is False, \
        "env không được phục hồi quyền đã bị bỏ ở giao diện"


def test_startup_survives_a_database_older_than_the_users_table(tmp_path, monkeypatch):
    """Ca đắt nhất, và test cũ KHÔNG bắt được vì test nào cũng gọi `init_db` tay.

    Máy thật có `jobs.db` tạo từ trước khi bảng `nguoi_dung` tồn tại. Nếu bước
    mồi admin chạy trước khi lược đồ được di trú thì nó ném `no such table` và
    **giết cả tiến trình lúc khởi động** — đo được khi chạy app thật:
    "Application startup failed. Exiting."
    """
    import asyncio
    import sqlite3

    db = tmp_path / "jobs.db"
    # DB "đời cũ": có bảng jobs, KHÔNG có nguoi_dung.
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, nguoi_tao TEXT)")
    conn.commit()
    conn.close()
    assert not _co_bang(db, "nguoi_dung"), "sân phải bắt đầu KHÔNG có bảng"

    monkeypatch.setenv("VIDEODL_ADMIN_EMAILS", "sep@astronex.ai")
    monkeypatch.setattr(app_mod, "DB_PATH", db)
    monkeypatch.setattr(app_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "DOWNLOADS_DIR", tmp_path / "downloads")
    monkeypatch.setattr(app_mod, "COOKIES_DIR", tmp_path / "cookies")
    monkeypatch.setattr(app_mod, "COOKIE_TMP_DIR", tmp_path / "tmp")
    monkeypatch.setattr(app_mod.worker, "start", lambda: None)
    monkeypatch.setattr(app_mod.worker, "stop", lambda: None)

    async def _chay():
        async with app_mod._lifespan(app_mod.app):
            pass

    asyncio.run(_chay())      # không được ném

    assert _co_bang(db, "nguoi_dung")
    assert app_mod._la_admin("sep@astronex.ai") is True, "mồi admin phải chạy được"


def _co_bang(db_path, ten):
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (ten,)).fetchone()[0] > 0


# ===========================================================================
# Các lỗ review tìm ra — mỗi test là một ca hỏng đã dựng lại được
# ===========================================================================

def test_a_per_user_cap_actually_stops_the_job(tmp_path, monkeypatch):
    """Trần riêng phải CÓ HIỆU LỰC ở cổng chặn.

    Ca hỏng review dựng: đặt `tran_luot=1` vào DB rồi tạo 3 job — cổng chặn
    trả `None` cả ba lần vì nó vẫn dùng hằng số 20. Một trần ghi được mà cổng
    không đọc thì chỉ là ô nhập liệu không làm gì.
    """
    db = _san_admin(tmp_path, monkeypatch)
    models.dat_tran_nguoi_dung(db, TEST_USER, tran_luot=1, tran_video=10)
    ck = tmp_path / "cookies"

    models.create_job(db, "https://www.tiktok.com/tag/a", 1, TEST_USER)
    tu_choi = lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=ck, nguoi_tao=TEST_USER, so_luong=1)

    assert tu_choi is not None, "trần riêng 1 lượt phải chặn lượt thứ hai"
    assert "1" in tu_choi


def test_the_default_cap_still_applies_when_no_per_user_cap_is_set(tmp_path, monkeypatch):
    """CA DƯƠNG: không đặt trần riêng thì vẫn theo mặc định, không phải chặn hết."""
    db = _san_admin(tmp_path, monkeypatch)
    ck = tmp_path / "cookies"
    models.create_job(db, "https://www.tiktok.com/tag/a", 1, TEST_USER)

    assert lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=ck, nguoi_tao=TEST_USER, so_luong=1) is None


def test_changing_one_cap_does_not_wipe_the_other(tmp_path, monkeypatch):
    """Ca hỏng review dựng: đặt cả hai → 5/500; rồi PUT chỉ `tran_luot=7`
    ⇒ `tran_video` bị xoá về NULL, không một lời cảnh báo."""
    db = _san_admin(tmp_path, monkeypatch)
    app_mod.admin_cap_nhat(email=TEST_USER,
                            body=app_mod.CapNhatNguoiDung(tran_luot=5, tran_video=500),
                            nguoi_tao="sep@astronex.ai")
    assert models.tran_rieng_cua(db, TEST_USER) == (5, 500)

    app_mod.admin_cap_nhat(email=TEST_USER,
                            body=app_mod.CapNhatNguoiDung(tran_luot=7),
                            nguoi_tao="sep@astronex.ai")

    assert models.tran_rieng_cua(db, TEST_USER) == (7, 500), \
        "sửa một trần không được xoá trần kia"


def test_sending_a_null_cap_means_back_to_default(tmp_path, monkeypatch):
    """`None` CÓ TRUYỀN = về mặc định hệ thống. Khác hẳn "không gửi"."""
    db = _san_admin(tmp_path, monkeypatch)
    models.dat_tran_nguoi_dung(db, TEST_USER, tran_luot=5, tran_video=500)

    app_mod.admin_cap_nhat(email=TEST_USER,
                            body=app_mod.CapNhatNguoiDung(tran_luot=None),
                            nguoi_tao="sep@astronex.ai")

    assert models.tran_rieng_cua(db, TEST_USER) == (None, 500)


def test_two_admins_demoting_each_other_cannot_reach_zero(tmp_path, monkeypatch):
    """Ca hỏng review dựng bằng hai luồng: cả hai đọc "còn 2 admin" trước khi
    ai kịp ghi ⇒ hai lượt 200 ⇒ **còn 0 admin**.

    Ở đây đo bằng phép tương đương, không cần luồng: gọi tuần tự hai lượt bỏ
    quyền. Điều kiện canh nằm TRONG câu UPDATE nên lượt thứ hai phải thất bại
    dù người gọi không đếm gì cả — đó là tính chất chống đua, và nó kiểm được
    mà không cần dựng đua.
    """
    db = _san_admin(tmp_path, monkeypatch)
    models.dat_quyen_admin(db, TEST_USER, True, "sep@astronex.ai")
    assert models.dem_admin(db) == 2

    assert models.dat_quyen_admin(db, "sep@astronex.ai", False, "x") is True
    assert models.dat_quyen_admin(db, TEST_USER, False, "x") is False, \
        "lượt bỏ quyền thứ hai phải bị TỪ CHỐI, không phải im lặng thành công"
    assert models.dem_admin(db) == 1, "không bao giờ được về 0 admin"


def test_a_transient_db_error_cannot_unlock_the_last_admin_guard(tmp_path, monkeypatch):
    """Ca hỏng review dựng: `is_admin` trả `False` khi DB lỗi thoáng qua, và
    `False` làm điều kiện canh bị short-circuit ⇒ lượt bỏ quyền đi thẳng.

    Sau bản vá, trạng thái lấy từ hàng đã đọc và quyết định nằm trong UPDATE,
    nên `_la_admin` có trả sai cũng không mở được khoá.
    """
    db = _san_admin(tmp_path, monkeypatch)
    monkeypatch.setattr(app_mod, "_la_admin", lambda e: False)

    with pytest.raises(HTTPException) as bat:
        app_mod.admin_cap_nhat(email="sep@astronex.ai",
                                body=app_mod.CapNhatNguoiDung(la_admin=False),
                                nguoi_tao="sep@astronex.ai")

    assert bat.value.status_code == 409
    assert models.dem_admin(db) == 1


def test_upgrading_an_old_database_keeps_the_people_who_already_downloaded(
        tmp_path, monkeypatch):
    """Ca hỏng review dựng: sau nâng cấp, trang Quản trị gần như trống và
    **không đặt được trần cho ai** cho tới khi từng người tự ghé `/me`.

    Máy thật đang có 6 lượt tải của 2 danh tính — họ phải có mặt ngay.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.create_job(db, "https://www.tiktok.com/tag/x", 5, "nguoicu@astronex.ai")
    # Xoá sạch bảng danh bạ để giả lập "DB có job nhưng chưa có bảng người dùng".
    with models._connect(db) as conn:
        conn.execute("DELETE FROM nguoi_dung")

    models.init_db(db)          # nâng cấp lần nữa = chạy backfill

    assert "nguoicu@astronex.ai" in {u["email"] for u in models.danh_sach_nguoi_dung(db)}


# ---------------------------------------------------------------------------
# T2.2 — vị trí trong hàng đợi + rút lượt chưa chạy.
#
# Hai thứ dễ ship sai ở đây, và cả hai đều SAI ÂM THẦM:
#   · đếm vị trí bằng mỗi `pending` ⇒ người đứng sau một job đang tải thấy
#     "0 lượt trước bạn" mà vẫn phải đợi;
#   · trả cùng một câu cho "job của người khác" và "job vừa bắt đầu chạy" ⇒
#     người bấm đúng lúc bị bảo là bấm nhầm.
# ---------------------------------------------------------------------------
NGUOI_KHAC = "nguoikhac@astronex.ai"


def _mk_job(db_path, url, nguoi_tao=TEST_USER, trang_thai="pending"):
    job_id = models.create_job(db_path, url, 5, nguoi_tao)
    if trang_thai != "pending":
        with models._connect(db_path) as conn:
            conn.execute("UPDATE jobs SET trang_thai = ? WHERE id = ?",
                         (trang_thai, job_id))
    return job_id


def test_vi_tri_dem_ca_job_dang_chay(tmp_path):
    """Job đang tải đã rời `pending` nhưng vẫn chiếm chỗ của worker.

    Đột biến: đếm mỗi `pending` (bỏ vế `running`) ⇒ chờ_1 thành 1 ⇒ ĐỎ.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    _mk_job(db_path, "https://www.tiktok.com/tag/a", trang_thai="running")
    cho_1 = _mk_job(db_path, "https://www.tiktok.com/tag/b")
    cho_2 = _mk_job(db_path, "https://www.tiktok.com/tag/c")

    vi_tri = models.vi_tri_hang_doi(db_path, [cho_1, cho_2])

    assert vi_tri[cho_1] == 2, "một job đang chạy phải chiếm chỗ thứ nhất"
    assert vi_tri[cho_2] == 3


def test_vi_tri_chi_gan_cho_job_dang_cho(tmp_path):
    """Job xong/đang chạy không có vị trí — số đó vô nghĩa với chúng."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    xong = _mk_job(db_path, "https://www.tiktok.com/tag/a", trang_thai="done")
    cho = _mk_job(db_path, "https://www.tiktok.com/tag/b")

    vi_tri = models.vi_tri_hang_doi(db_path, [xong, cho])

    assert xong not in vi_tri
    assert vi_tri[cho] == 1


def test_vi_tri_theo_thu_tu_worker_thuc_su_nhat(tmp_path):
    """Thứ tự đếm phải TRÙNG thứ tự `claim_next_pending_job` nhặt.

    Không phải hai câu SQL giống nhau về hình thức — mà là: job worker lấy
    ra tiếp theo phải đúng là job đang mang vị trí 1. Đây là phép phân
    định thật; so hai chuỗi ORDER BY chỉ là đọc chính mình.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    a = _mk_job(db_path, "https://www.tiktok.com/tag/a")
    b = _mk_job(db_path, "https://www.tiktok.com/tag/b")

    vi_tri = models.vi_tri_hang_doi(db_path, [a, b])
    dau_tien = min(vi_tri, key=lambda jid: vi_tri[jid])
    nhat_duoc = models.claim_next_pending_job(db_path)

    assert nhat_duoc is not None
    assert nhat_duoc["id"] == dau_tien


def test_huy_job_dang_cho_thi_worker_khong_nhat_nua(tmp_path):
    """Nghiệm thu chính của mục: rút rồi thì worker phải BỎ QUA nó.

    Đột biến: bỏ `AND trang_thai = 'pending'` khỏi câu UPDATE thì test
    `test_huy_job_dang_chay_tra_409` ĐỎ; bỏ hẳn việc đổi trạng thái thì
    test này ĐỎ vì worker nhặt đúng job vừa bị rút.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    bi_huy = _mk_job(db_path, "https://www.tiktok.com/tag/a")
    con_lai = _mk_job(db_path, "https://www.tiktok.com/tag/b")

    assert models.huy_job_dang_cho(db_path, bi_huy, TEST_USER) == "da_huy"

    assert models.get_job(db_path, bi_huy)["trang_thai"] == "cancelled"
    nhat_duoc = models.claim_next_pending_job(db_path)
    assert nhat_duoc is not None and nhat_duoc["id"] == con_lai


def test_huy_job_dang_chay_tra_409(tmp_path, monkeypatch):
    """Bấm đúng nhưng chậm một nhịp — KHÔNG được trả 404 như bấm nhầm."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    dang_chay = _mk_job(db_path, "https://www.tiktok.com/tag/a",
                        trang_thai="running")

    with pytest.raises(HTTPException) as e:
        app_mod.huy_job(dang_chay, nguoi_tao=TEST_USER)

    assert e.value.status_code == 409
    assert models.get_job(db_path, dang_chay)["trang_thai"] == "running"


def test_huy_job_cua_nguoi_khac_tra_404_va_khong_dong_gi(tmp_path, monkeypatch):
    """404 chứ không 403: id job chạy tuần tự, 403 là xác nhận id có thật."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    cua_ho = _mk_job(db_path, "https://www.tiktok.com/tag/a",
                     nguoi_tao=NGUOI_KHAC)

    with pytest.raises(HTTPException) as e:
        app_mod.huy_job(cua_ho, nguoi_tao=TEST_USER)

    assert e.value.status_code == 404
    assert models.get_job(db_path, cua_ho)["trang_thai"] == "pending"


def test_huy_job_khong_ton_tai_cung_tra_404(tmp_path, monkeypatch):
    """Hai ca không phân biệt được từ ngoài — có chủ đích."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)

    with pytest.raises(HTTPException) as e:
        app_mod.huy_job(99999, nguoi_tao=TEST_USER)

    assert e.value.status_code == 404


def test_admin_khong_rut_ho_job_nguoi_khac(tmp_path, monkeypatch):
    """Admin ĐỌC được job người khác nhưng không rút hộ.

    Xem là đọc, rút là ghi vào việc đang chờ của người khác. Nếu sau này
    mở cửa đó thì phải có màn hình cho nó — test này sẽ ĐỎ và buộc người
    sửa phải quyết định có chủ đích, thay vì để nó trôi vào.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "_la_admin", lambda ai: True)
    cua_ho = _mk_job(db_path, "https://www.tiktok.com/tag/a",
                     nguoi_tao=NGUOI_KHAC)

    with pytest.raises(HTTPException) as e:
        app_mod.huy_job(cua_ho, nguoi_tao=TEST_USER)

    assert e.value.status_code == 404
    assert models.get_job(db_path, cua_ho)["trang_thai"] == "pending"


def test_list_jobs_gan_vi_tri_cho_job_dang_cho(tmp_path, monkeypatch):
    """Vị trí phải do MÁY CHỦ đếm, không để trang tự đếm.

    Trang chỉ thấy job của chính mình; nếu nó tự đếm thì nó bỏ qua hàng
    đợi của người khác và ra một con số nhỏ hơn sự thật.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    monkeypatch.setattr(app_mod, "DB_PATH", db_path)
    monkeypatch.setattr(app_mod, "_la_admin", lambda ai: False)
    _mk_job(db_path, "https://www.tiktok.com/tag/x", nguoi_tao=NGUOI_KHAC)
    cua_toi = _mk_job(db_path, "https://www.tiktok.com/tag/b")

    jobs = app_mod.list_jobs(nguoi_tao=TEST_USER)

    assert [j["id"] for j in jobs] == [cua_toi], "chỉ thấy job của mình"
    assert jobs[0]["vi_tri"] == 2, "phải đếm cả job người khác đang chờ trước"


# ---------------------------------------------------------------------------
# T3 — nút "Tạo bộ tự tìm" bàn giao sang Creative Desk.
#
# Repo không có hạ tầng test JS, nên hai test dưới đây KHÔNG kiểm hành vi —
# chúng canh đúng một tính chất AN TOÀN, và tính chất đó kiểm được bằng cách
# đọc tệp: Video Desk **không gọi API** của Creative Desk. Bàn giao phải đi
# qua thanh địa chỉ, để danh tính là phiên của chính người dùng bên đó.
#
# Hành vi (payload đúng, URL đúng) được nghiệm thu bằng trình duyệt thật —
# xem báo cáo 18/09. Đừng đọc hai test này thành "đã phủ tính năng".
# ---------------------------------------------------------------------------
STATIC = Path(app_mod.__file__).parent / "static"


def test_nut_tao_bo_tu_tim_co_mat_trong_thanh_chon():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-action="self-bundle"' in html


def test_video_desk_khong_goi_api_creative_desk():
    """Đột biến: đổi `window.open(...)` thành `fetch(CREATIVE_DESK_URL + ...)`
    ⇒ test này ĐỎ. Đó là cả điểm của nó.

    Gọi API chéo origin sẽ buộc Video Desk cầm token của người dùng hoặc một
    service token — dựng một bề mặt mạo danh cho việc vốn chỉ là copy file.
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "CREATIVE_DESK_URL" in js, "chưa có hằng số đích — test này thành vô nghĩa"
    assert "window.open(" in js, "bàn giao phải qua thanh địa chỉ"

    for dong in js.splitlines():
        if "fetch(" in dong or "XMLHttpRequest" in dong or "EventSource(" in dong:
            assert "CREATIVE_DESK_URL" not in dong, f"gọi API sang Creative Desk: {dong.strip()}"
            assert "automation.nobidigital.asia" not in dong, f"gọi API sang Creative Desk: {dong.strip()}"


# ---------------------------------------------------------------------------
# Dấu thời gian trong log.
#
# Log trên mini gộp stdout+stderr vào một tệp và định dạng mặc định của
# uvicorn không có giờ, nên không ai định vị được sự kiện theo thời gian.
# ---------------------------------------------------------------------------
def test_log_co_dau_thoi_gian(caplog):
    """Định dạng phải mang giờ, và phải THẮNG handler uvicorn đã gắn trước.

    Đột biến: bỏ `force=True` trong `_dat_dinh_dang_log` ⇒ khi root logger đã
    có handler (đúng tình trạng dưới uvicorn) `basicConfig` im lặng không làm
    gì ⇒ test này ĐỎ. Đó là cả điểm của nó — không có `force`, hàm vẫn chạy,
    vẫn không lỗi, và vẫn không đổi một dòng log nào.
    """
    import logging as _logging

    # Dựng lại đúng tình trạng dưới uvicorn: root logger ĐÃ có handler.
    goc = _logging.getLogger()
    rac = _logging.StreamHandler()
    rac.setFormatter(_logging.Formatter("%(message)s"))
    goc.addHandler(rac)
    try:
        app_mod._dat_dinh_dang_log()
        dinh_dang = goc.handlers[0].formatter._fmt
    finally:
        goc.removeHandler(rac)

    assert "%(asctime)s" in dinh_dang, "thiếu dấu thời gian"
    assert "%(levelname)s" in dinh_dang


def test_log_uvicorn_cung_co_dau_thoi_gian():
    """Test cũ kiểm ROOT logger và XANH, trong khi log thật không đổi một dòng.

    Đo 20/09 ngay sau deploy: 0/6800 dòng trong `videodl.log` có dấu thời
    gian. Nguyên nhân đo được: uvicorn dựng log config **SAU** khi mô-đun app
    được import, cấp cho `uvicorn.access` handler riêng và đặt
    `propagate = False` — nên định dạng đặt ở root không bao giờ chạm tới nó,
    mà gần như mọi dòng trong tệp là của `uvicorn.access`.

    Test này dựng lại ĐÚNG thứ tự đó (nạp app trước, uvicorn cấu hình sau) rồi
    mới gọi hàm vá. Đột biến: bỏ `_dong_dau_thoi_gian_vao_uvicorn()` khỏi
    `_lifespan`, hoặc bỏ `uvicorn.access` khỏi danh sách trong hàm đó ⇒ ĐỎ.
    """
    import logging as _logging
    import logging.config as _config
    import uvicorn.config

    # Thứ tự THẬT: app đã nạp (conftest/import ở đầu tệp), giờ uvicorn cấu hình.
    _config.dictConfig(uvicorn.config.LOGGING_CONFIG)
    access = _logging.getLogger("uvicorn.access")
    assert access.handlers, "khuôn test sai: uvicorn.access phải có handler riêng"
    assert access.propagate is False, "khuôn test sai: uvicorn.access phải ngắt khỏi root"
    # Trước khi vá, định dạng là của uvicorn — đây là phép phân định.
    assert "%(asctime)s" not in access.handlers[0].formatter._fmt

    app_mod._dong_dau_thoi_gian_vao_uvicorn()

    for ten in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        h = _logging.getLogger(ten).handlers
        if h:
            assert "%(asctime)s" in h[0].formatter._fmt, f"{ten} vẫn thiếu giờ"
            assert "%(levelprefix)s" not in h[0].formatter._fmt, f"{ten} còn mã màu"


def test_lifespan_co_goi_va_uvicorn():
    """Vá đúng mà không ai gọi thì log vẫn trần. Đột biến: xoá lời gọi ⇒ ĐỎ."""
    import inspect
    nguon = inspect.getsource(app_mod._lifespan)
    assert "_dong_dau_thoi_gian_vao_uvicorn()" in nguon


def test_van_tay_doi_khi_thay_cookie_va_khong_mang_byte_nao_cua_jar(tmp_path, monkeypatch):
    """Vân tay phải PHÂN ĐỊNH được hai jar, và không được rò nội dung.

    Hai phép đo, vì một mình phép đầu không đủ: một hằng số cũng "có mặt" ở mọi
    lượt gọi, nên phải chứng minh nó ĐỔI khi jar đổi, và GIỮ NGUYÊN khi jar
    không đổi. Đây đúng chỗ dễ dựng một trường trang trí mà không ai kiểm.
    """
    _san_cookie(tmp_path, monkeypatch)

    app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le("JAR-MOT")),
                          nguoi_tao=TEST_USER)
    mot = app_mod.get_my_cookie(nguoi_tao=TEST_USER)["van_tay"]
    # Đọc lại cùng một jar: cùng nội dung ⇒ cùng vân tay.
    assert app_mod.get_my_cookie(nguoi_tao=TEST_USER)["van_tay"] == mot

    app_mod.put_my_cookie(app_mod.CookieBody(json=_jar_hop_le("JAR-HAI")),
                          nguoi_tao=TEST_USER)
    hai = app_mod.get_my_cookie(nguoi_tao=TEST_USER)["van_tay"]

    assert hai != mot, "thay cookie mà vân tay không đổi ⇒ không kiểm được bản thay đã ăn"
    assert len(mot) == 8 and len(hai) == 8

    # Và không mang byte nào của jar: giá trị bí mật không xuất hiện ở BẤT KỲ
    # trường nào, không riêng `van_tay`.
    tt = app_mod.get_my_cookie(nguoi_tao=TEST_USER)
    assert "JAR-HAI" not in json.dumps(tt)
    assert "sessionid" not in json.dumps(tt)


def test_chua_dan_cookie_thi_van_tay_la_none(tmp_path, monkeypatch):
    """Không có jar ⇒ `van_tay` là None, không phải chuỗi rỗng hay thiếu khoá:
    trang Cài đặt phân biệt "chưa có" với "có mà không đọc được"."""
    _san_cookie(tmp_path, monkeypatch)
    tt = app_mod.get_my_cookie(nguoi_tao=TEST_USER)
    assert tt["co_jar"] is False
    assert "van_tay" in tt and tt["van_tay"] is None


# ---------------------------------------------------------------------------
# Bàn giao bộ tự tìm phải BỎ CHỌN sau khi mở tab
# ---------------------------------------------------------------------------

def test_ban_giao_bo_tu_tim_bo_chon_sau_khi_mo_tab():
    """Bấm "Tạo bộ tự tìm" xong mà lựa chọn còn nguyên thì lần bấm kế tiếp mở
    thêm một tab với ĐÚNG danh sách cũ — người dùng đọc thành "bộ cũ không gỡ
    được" (user báo 22/09, 9 video).

    Đây là test HÀNH VI, không phải grep chuỗi: nó trích `moBoTuTim` từ
    `app.js` thật rồi GỌI hàm đó với `window.open` giả. Assert bằng chuỗi sẽ
    xanh cho một lời gọi `clear()` nằm sai nhánh.

    Từ 26/09 chọn tay đi qua postMessage; điểm bỏ chọn dời từ "tab mở được"
    sang "Creative Desk ack ok:true". Hai ca gốc vẫn giữ:
      · có ack        ⇒ bỏ chọn, gỡ dấu trên thẻ, vẽ lại thanh
      · popup bị chặn ⇒ GIỮ nguyên lựa chọn — chưa có gì được bàn giao, xoá ở
        đó là bắt người dùng chọn lại vì một việc CHƯA xảy ra. Cùng khuôn với
        `loaiDaChon`, nó chỉ `clear()` sau khi API thành công.

    ĐỐI CHỨNG đã chạy trên `origin/main` trước khi vá: cả hai ca đều trả
    `conChon=3` ⇒ phép đo này phân định được hai bản.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này "
                    "KHÔNG chạy, đừng đọc suite xanh thành 'đã kiểm'")

    harness = Path(__file__).parent / "js" / "chon-sau-ban-giao.js"
    ket_qua = subprocess.run([node, str(harness), str(STATIC / "app.js")],
                             capture_output=True, text=True, timeout=30)
    assert ket_qua.returncode == 0, ket_qua.stderr
    do = json.loads(ket_qua.stdout)

    # 26/09: chọn tay gửi qua postMessage — bỏ chọn CHỈ khi Creative Desk ack `ok:true`.
    ack = do["ack"]
    assert ack["moTab"] == 1, "phải mở tab bàn giao"
    assert ack["url"].endswith("/creative-order/self-bundles?videodesk_pm=1")
    assert ack["dich"] == "https://automation.example", "targetOrigin phải cố định, không phải '*'"
    assert ack["tin"] == {"type": "videodesk-handoff", "v": 2, "coId": True, "soItem": 3, "coNhan": False}
    assert ack["conChon"] == 0 and ack["theConTo"] == 0 and ack["veLaiThanh"] == 1
    assert ack["nutKhiCho"]["disabled"] is True and ack["nutSau"]["disabled"] is False

    for ca in ("tu_choi", "im", "sai_origin", "sai_id"):
        assert do[ca]["conChon"] == 3, f"{ca}: chưa có ack ok:true thì KHÔNG được xoá lựa chọn"
    assert do["im"]["soLanGui"] > 2, "không ack thì phải gửi lặp (tab có thể đang đăng nhập)"

    assert do["popup_bi_chan"]["conChon"] == 3 and do["popup_bi_chan"]["soLanGui"] == 0, \
        "popup bị chặn thì chưa bàn giao được — không được xoá lựa chọn"
    assert do["nhieu"]["tin"]["soItem"] == 86, "90 chọn, 4 chưa lên Drive ⇒ gửi 86, không trần 30"
    assert "4 video chưa lên Drive" in do["nhieu"]["toast"]
    assert do["qua_tran"]["moTab"] == 0 and do["qua_tran"]["conChon"] == 501
    assert do["bam_dup"]["moTab"] == 1, "bấm đúp lúc đang chờ ack không được mở tab thứ hai"
    assert do["gui_lai"]["moTab"] == 2 and do["gui_lai"]["lanHai"]["idMoi"] is True, \
        "bấm lại sau khi hết hạn phải mở TAB MỚI (tab cũ có thể đã mất ?videodesk_pm=1 sau /login)"
    assert do["gui_lai"]["conChon"] == 0


def test_o_dan_cookie_duoc_xoa_ca_khi_bi_tu_choi():
    """Dán cookie hỏng ⇒ ô dán phải trống sau khi bấm Lưu, như nhánh thành công.

    Bản trước chỉ xoá ô khi lưu ĐƯỢC. Cookie bị từ chối vẫn nằm nguyên trên
    màn hình — với một bản xuất thật là nguyên giá trị phiên đăng nhập.
    Chạy NGUYÊN `settings.js` qua node (harness `tests/js/o-dan-cookie-sau-khi-luu.js`).

    Đối chứng: trên bản chưa vá harness ra `oDanConLai="[COOKIE-GIA]"` ở cả hai
    nhánh lỗi, và `loi` khác rỗng chứng minh nhánh lỗi đã thật sự chạy.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy settings.js thật — không có thì test này "
                    "KHÔNG chạy, đừng đọc suite xanh thành 'đã kiểm'")

    harness = Path(__file__).parent / "js" / "o-dan-cookie-sau-khi-luu.js"
    ket_qua = subprocess.run([node, str(harness), str(STATIC / "settings.js")],
                             capture_output=True, text=True, timeout=30)
    assert ket_qua.returncode == 0, ket_qua.stderr
    do = json.loads(ket_qua.stdout)

    for nhanh in ("bi_tu_choi", "loi_mang"):
        assert do[nhanh]["loi"], f"{nhanh}: nhánh lỗi không chạy — phép đo rỗng"
        assert do[nhanh]["oDanConLai"] == "", f"{nhanh}: cookie còn nằm trong ô dán"
    assert "hết hạn" in do["bi_tu_choi"]["loi"], "mã từ chối phải hiện câu của nó"
    assert "bị từ chối" in do["bi_tu_choi"]["loi"]
    assert do["thanh_cong"]["oDanConLai"] == "" and do["thanh_cong"]["loi"] == ""


def test_bo_video_chia_lo_theo_tran_backend():
    """Chọn nhiều hơn trần một lượt ⇒ FE chia lô ≤ trần, gửi tuần tự, không 422.

    Ca thật 23/09 10:45: thư viện 86 video, bản cũ gửi nguyên lựa chọn trong MỘT
    request ⇒ `max_length=50` trả 422 ⇒ không video nào được bỏ. Harness
    `tests/js/loai-theo-lo.js` chạy `loaiDaChon` THẬT với `apiSend` giả áp ĐÚNG
    `MAX_VIDEO_LOAI` của backend (truyền từ đây, không chép số).

    Đối chứng: bản chưa vá ra `goi=[120]`, `conChon=120`, toast "Không bỏ được:
    POST /videos/loai -> 422" — đúng câu user báo.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này "
                    "KHÔNG chạy, đừng đọc suite xanh thành 'đã kiểm'")

    harness = Path(__file__).parent / "js" / "loai-theo-lo.js"
    ket_qua = subprocess.run([node, str(harness), str(STATIC / "app.js"),
                              str(app_mod.MAX_VIDEO_LOAI)],
                             capture_output=True, text=True, timeout=30)
    assert ket_qua.returncode == 0, ket_qua.stderr
    do = json.loads(ket_qua.stdout)

    assert do["ba_lo"]["goi"] == [50, 50, 20], "120 id phải đi thành 3 lô ≤ trần"
    assert do["ba_lo"]["conChon"] == 0 and do["ba_lo"]["toast"] == "đã bỏ 120"
    assert do["mot_lo"]["goi"] == [30], "dưới trần vẫn là MỘT request như trước"
    assert do["dung_ngay_50"]["goi"] == [50], "đúng bằng trần: một lô, không lô rỗng thứ hai"

    loi = do["loi_lo_2"]
    assert loi["goi"] == [50, 50], "lô lỗi ⇒ DỪNG, không gửi lô 3"
    assert loi["conChon"] == 70, "chỉ gỡ lô đã bỏ được; lô lỗi + lô chưa gửi vẫn chọn"
    assert "đã bỏ 50" in loi["toast"] and "dừng ở lô 2/3" in loi["toast"]
    assert "còn 70 video đang chọn" in loi["toast"]
    assert "-> 500" not in loi["toast"], "không in dòng kỹ thuật cho người dùng"
    assert loi["lanNap"] == 1, "đã bỏ được một phần ⇒ phải nạp lại thư viện"


def test_tran_lo_loai_khop_backend():
    """Hằng FE `LOAI_TOI_DA_MOI_LUOT` phải bằng `MAX_VIDEO_LOAI`. Lệch ⇒ 422 quay lại
    (FE lớn hơn) hoặc thừa lượt gọi (FE nhỏ hơn) mà không test hành vi nào kêu."""
    import re

    src = (STATIC / "app.js").read_text(encoding="utf-8")
    m = re.search(r"const LOAI_TOI_DA_MOI_LUOT = (\d+);", src)
    assert m, "không tìm thấy hằng lô trong app.js"
    assert int(m.group(1)) == app_mod.MAX_VIDEO_LOAI


def test_cat_trang_va_day_nut_trang():
    """`catTrang` + `dayTrang` THẬT trích từ app.js (harness `tests/js/cat-trang.js`).

    86 video / 40 ⇒ 40/40/6 (đề bài 23/09) · trang vượt/âm bị KẸP, không ra lưới
    rỗng · 100/trang ⇒ 1 trang · danh sách rỗng không nổ · dải nút THU GỌN: trần
    nạp 2000 ở 10/trang = 200 trang, in đủ 200 nút là dài hơn cả lưới.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này "
                    "KHÔNG chạy, đừng đọc suite xanh thành 'đã kiểm'")
    harness = Path(__file__).parent / "js" / "cat-trang.js"
    r = subprocess.run([node, str(harness), str(STATIC / "app.js")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    do = json.loads(r.stdout)
    assert [do[k]["so"] for k in ("t1", "t2", "t3")] == [40, 40, 6]
    assert do["t3"]["dauTien"] == "v80"
    assert do["qua"]["trang"] == 3 and do["am"]["trang"] == 1, "trang ngoài khoảng phải kẹp"
    assert do["mot"] == {"trang": 1, "soTrang": 1, "dau": 0, "so": 86, "dauTien": "v0"}
    assert do["rong"]["soTrang"] == 1 and do["rong"]["so"] == 0
    assert do["day_giua"] == [1, "…", 98, 99, 100, 101, 102, "…", 200]
    assert do["day_dau"] == [1, 2, 3] and do["day_1"] == [1]


def test_giu_chon_xuyen_trang_ham_thuan():
    """Hàm THẬT trích từ app.js (harness `tests/js/giu-chon-xuyen-trang.js`).

    User 26/09: thêm 30/trang; chuyển trang / đổi số mỗi trang GIỮ lựa chọn. Cái giá
    "không thấy thẻ đã chọn ở trang kia" trả bằng con số: đếm id đã chọn KHÔNG thuộc
    trang đang xem, hiện trên thanh chọn và chèn vào hộp xác nhận thao tác hàng loạt.
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("cần `node` để chạy hàm JS thật — không có thì test này "
                    "KHÔNG chạy, đừng đọc suite xanh thành 'đã kiểm'")
    harness = Path(__file__).parent / "js" / "giu-chon-xuyen-trang.js"
    r = subprocess.run([node, str(harness), str(STATIC / "app.js")],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    do = json.loads(r.stdout)
    assert do["so_moi_trang"] == [10, 20, 30, 40, 100]
    assert (do["ngoai_0"], do["ngoai_2"], do["ngoai_rong"]) == (0, 2, 0)
    assert do["nhan_0"] == "" and do["nhan_2"] == "· 2 không hiện ở trang này"
    assert do["dong_0"] == ""
    assert "2 video không hiện ở trang này" in do["dong_2"]
