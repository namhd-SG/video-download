"""Tests for web/app.py's `POST /jobs` gate wiring (Bước 4/5 of the fix
chain). Calls the route function directly — `create_job` is a plain Python
function under the FastAPI decorator, callable without an HTTP client or the
`httpx` test-client dependency this venv does not have installed.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from web import app as app_mod
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
