"""Tests for web/lifecycle.py — Phase 03 upload-then-delete-then-backpressure.

No real Google Drive: `FakeUploader` implements the same
`upload_file(path) -> UploadResult` shape as `DriveUploader.upload_file`,
injected via `lifecycle.set_uploader()`. That is phase-03's constraint
"Không cần credential thật để test" made concrete — the "chưa cấu hình"
path is exercised for REAL (`DriveUploader()` with unset env vars, no
fake), and the "đã cấu hình mà trượt"/"thành công" paths use the fake so no
network call or real service-account key is ever needed.
"""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from tiktok_music_downloader.gdrive_upload import (
    DriveUploader,
    UploadOutcome,
    UploadResult,
    _tighten_credential_permissions,
)
from tiktok_music_downloader.utils import VideoRef
from web import lifecycle
from web import models
from web import queue as queue_mod


class FakeUploader:
    """Scripted uploader: pop one `UploadResult` per call, in order.

    `configured` defaults True — most tests here simulate a Drive that IS
    configured but whose calls succeed/fail per the scripted results; a
    handful of Bước 5 tests set `configured=False` to exercise the
    "chưa cấu hình" gate independently of the failure-counting gate.
    """

    def __init__(self, results: list[UploadResult], configured: bool = True,
                 folder_result: UploadResult | None = None):
        self._results = list(results)
        self._configured = configured
        self._folder_result = folder_result
        self.calls: list[tuple[Path, str | None]] = []
        self.folder_calls: list[int] = []

    def upload_file(self, path: Path, parent_folder_id: str | None = None) -> UploadResult:
        self.calls.append((path, parent_folder_id))
        if not self._results:
            raise AssertionError("FakeUploader gọi nhiều lần hơn kịch bản đã nạp")
        return self._results.pop(0)

    def is_configured(self) -> bool:
        return self._configured

    def create_job_folder(self, job_id: int) -> UploadResult:
        self.folder_calls.append(job_id)
        if self._folder_result is not None:
            return self._folder_result
        if not self._configured:
            return UploadResult(outcome=UploadOutcome.NOT_CONFIGURED, reason="chưa cấu hình")
        return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=f"folder-{job_id}",
                             web_view_link=f"https://drive/folder-{job_id}")


def _success(drive_id: str = "drive-1") -> UploadResult:
    return UploadResult(outcome=UploadOutcome.SUCCESS, file_id="f1",
                         drive_id=drive_id, web_view_link="https://drive/x")


def _failed(reason: str = "network timeout") -> UploadResult:
    return UploadResult(outcome=UploadOutcome.FAILED, reason=reason)


def _not_configured() -> UploadResult:
    return UploadResult(outcome=UploadOutcome.NOT_CONFIGURED, reason="chưa cấu hình")


def _fake_credential_file(tmp_path: Path) -> Path:
    cred = tmp_path / "fake-service-account.json"
    cred.write_text("{}")
    return cred


@pytest.fixture(autouse=True)
def _isolate_lifecycle_state():
    """Every test starts and ends with a clean slate: module-level
    backpressure counters, the per-job Drive-folder cache, and the injected
    uploader must never leak between tests in this file, or into
    test_web_queue.py's own lifecycle-hook test (which relies on an
    UNCONFIGURED real DriveUploader, not a leftover fake)."""
    lifecycle.reset_backpressure_state()
    lifecycle.reset_job_folder_cache()
    lifecycle.set_uploader(None)
    yield
    lifecycle.reset_backpressure_state()
    lifecycle.reset_job_folder_cache()
    lifecycle.set_uploader(None)


# ---------------------------------------------------------------------------
# Wiring: resolve_lifecycle_hook() must pick this module up with ZERO
# changes to web/queue.py.
# ---------------------------------------------------------------------------

def test_queue_wires_on_video_verified_as_the_default_lifecycle_hook():
    """`web/queue.py` imports `on_video_verified` directly at module level —
    no ImportError-swallowing resolver, no no-op fallback. Dropping this
    module would now be a hard ImportError at import time, not a silent
    "keep local, count as done" default."""
    assert queue_mod.on_video_verified is lifecycle.on_video_verified


# ---------------------------------------------------------------------------
# Three-state upload result (constraint 2): success / not_configured /
# failed must never collapse into the same value.
# ---------------------------------------------------------------------------

def test_not_configured_and_failed_are_distinguishable_outcomes():
    not_conf = _not_configured()
    failed = _failed()
    assert not_conf.outcome != failed.outcome
    assert not not_conf.ok
    assert not failed.ok


def test_real_driveuploader_reports_not_configured_when_env_unset(monkeypatch):
    monkeypatch.delenv("GDRIVE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GDRIVE_SHARED_DRIVE_FOLDER_ID", raising=False)
    uploader = DriveUploader()
    result = uploader.upload_file(Path("/nonexistent/whatever.mp4"))
    assert result.outcome is UploadOutcome.NOT_CONFIGURED
    assert result.reason  # secret-safe human message, never empty


# ---------------------------------------------------------------------------
# MUTATION (a): delete-only-after-success. Bỏ điều kiện `if result.ok:`
# trước khi xoá phải làm test dưới đây ĐỎ.
# ---------------------------------------------------------------------------

def test_successful_upload_deletes_local_file(tmp_path):
    video = tmp_path / "abc.mp4"
    video.write_bytes(b"fake video bytes")
    lifecycle.set_uploader(FakeUploader([_success()]))

    lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id="abc", url="u"), path=video)

    assert not video.exists(), "upload THÀNH CÔNG thì file local phải bị xoá ngay"


def test_failed_upload_keeps_local_file(tmp_path):
    video = tmp_path / "abc.mp4"
    video.write_bytes(b"fake video bytes")
    lifecycle.set_uploader(FakeUploader([_failed()]))

    lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id="abc", url="u"), path=video)

    assert video.exists(), "upload TRƯỢT thì file local phải GIỮ lại, không xoá"


def test_not_configured_upload_keeps_local_file(tmp_path):
    video = tmp_path / "abc.mp4"
    video.write_bytes(b"fake video bytes")
    lifecycle.set_uploader(FakeUploader([_not_configured()]))

    lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id="abc", url="u"), path=video)

    assert video.exists(), "chưa cấu hình Drive thì file local phải GIỮ lại, không xoá"


# ---------------------------------------------------------------------------
# MUTATION (b): backpressure. Bỏ cơ chế đếm/tạm dừng phải làm test dưới đây
# ĐỎ — file phải TÍCH LẠI (không mất) và job mới phải bị TỪ CHỐI.
# ---------------------------------------------------------------------------

def test_three_consecutive_failures_trip_backpressure_and_reject_new_jobs(tmp_path):
    fake = FakeUploader([_failed("f1"), _failed("f2"), _failed("f3")])
    lifecycle.set_uploader(fake)

    kept_paths = []
    for i in range(3):
        video = tmp_path / f"v{i}.mp4"
        video.write_bytes(b"x")
        lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id=f"v{i}", url="u"), path=video)
        kept_paths.append(video)

    assert all(p.exists() for p in kept_paths), "cả 3 file trượt phải còn nguyên trên đĩa (tích lại)"

    status = lifecycle.get_backpressure_status()
    assert status.paused
    assert status.consecutive_failures == 3

    rejection = lifecycle.should_reject_new_job()
    assert rejection is not None and "trượt" in rejection, "job mới phải bị từ chối kèm lý do rõ ràng"


def test_backpressure_resets_after_one_successful_upload(tmp_path):
    fake = FakeUploader([_failed(), _failed(), _success()])
    lifecycle.set_uploader(fake)

    for i in range(2):
        video = tmp_path / f"v{i}.mp4"
        video.write_bytes(b"x")
        lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id=f"v{i}", url="u"), path=video)

    ok_video = tmp_path / "ok.mp4"
    ok_video.write_bytes(b"x")
    lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id="ok", url="u"), path=ok_video)

    status = lifecycle.get_backpressure_status()
    assert not status.paused
    assert status.consecutive_failures == 0
    assert lifecycle.should_reject_new_job() is None
    assert not ok_video.exists()  # upload thành công thì phải bị xoá


def test_two_failures_alone_do_not_trip_backpressure(tmp_path):
    fake = FakeUploader([_failed(), _failed()])
    lifecycle.set_uploader(fake)
    for i in range(2):
        video = tmp_path / f"v{i}.mp4"
        video.write_bytes(b"x")
        lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id=f"v{i}", url="u"), path=video)

    status = lifecycle.get_backpressure_status()
    assert not status.paused
    assert lifecycle.should_reject_new_job() is None


# ---------------------------------------------------------------------------
# Disk guard: reads live, never cached (constraint 5).
# ---------------------------------------------------------------------------

def test_disk_guard_ok_when_free_space_above_threshold(tmp_path):
    status = lifecycle.check_disk_guard(tmp_path, min_free_bytes=1)
    assert status.ok
    assert status.free_bytes > 0


def test_disk_guard_rejects_when_free_space_below_threshold(tmp_path):
    huge_threshold = 10 ** 18  # no real disk has an exabyte free
    status = lifecycle.check_disk_guard(tmp_path, min_free_bytes=huge_threshold)
    assert not status.ok
    assert "MB" in status.reason


def test_disk_guard_reads_live_not_cached(tmp_path, monkeypatch):
    """Two calls, mocked `shutil.disk_usage` returning a DIFFERENT answer
    each time, must produce two different verdicts — proves there is no
    cached value sitting in between."""
    import shutil as shutil_mod
    from collections import namedtuple

    Usage = namedtuple("Usage", "total used free")
    calls = iter([Usage(100, 90, 10), Usage(100, 10, 90)])
    monkeypatch.setattr(shutil_mod, "disk_usage", lambda _p: next(calls))

    first = lifecycle.check_disk_guard(tmp_path, min_free_bytes=50)
    second = lifecycle.check_disk_guard(tmp_path, min_free_bytes=50)
    assert not first.ok
    assert second.ok


def test_should_reject_new_job_reports_disk_guard_reason(tmp_path):
    # Configured fake so the disk-guard gate is actually reached — this
    # test is about disk guard, not about Drive configuration state.
    lifecycle.set_uploader(FakeUploader([]))
    reason = lifecycle.should_reject_new_job(downloads_dir=tmp_path, min_free_bytes=10 ** 18)
    assert reason is not None and "MB" in reason


# ---------------------------------------------------------------------------
# Bước 5: "chưa cấu hình" và "đã cấu hình mà trượt" là HAI trạng thái khác
# nhau (guard-marker-and-claim-write-ordering.md vế 2). Gộp chúng lại từng
# gây "3 video đầu là pause vĩnh viễn" trên máy chưa cấu hình Drive.
# ---------------------------------------------------------------------------

def test_not_configured_outcomes_never_trip_backpressure(tmp_path):
    """MUTATION: đếm NOT_CONFIGURED vào bộ đếm trượt (bỏ nhánh early-return
    trong `_note_upload_outcome`) phải làm test này ĐỎ sau đúng 3 video."""
    fake = FakeUploader([_not_configured() for _ in range(5)])
    lifecycle.set_uploader(fake)

    for i in range(5):
        video = tmp_path / f"v{i}.mp4"
        video.write_bytes(b"x")
        lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id=f"v{i}", url="u"), path=video)

    status = lifecycle.get_backpressure_status()
    assert not status.paused, "chưa cấu hình không được tự trip backpressure vĩnh viễn"
    assert status.consecutive_failures == 0
    assert all(v.exists() for v in [tmp_path / f"v{i}.mp4" for i in range(5)])


def test_should_reject_new_job_reports_not_configured_reason_distinctly():
    lifecycle.set_uploader(FakeUploader([], configured=False))
    reason = lifecycle.should_reject_new_job()
    assert reason is not None
    assert "cấu hình" in reason


def test_not_configured_gate_does_not_mask_real_backpressure_once_configured(tmp_path):
    """Ca dương phân định: khi ĐÃ cấu hình (is_configured True) và có 3 lỗi
    thật liên tiếp, gate `should_reject_new_job` vẫn phải báo lý do TRƯỢT,
    không phải lý do "chưa cấu hình" — hai gate độc lập, không cái nào che
    mất cái kia."""
    fake = FakeUploader([_failed("f1"), _failed("f2"), _failed("f3")], configured=True)
    lifecycle.set_uploader(fake)
    for i in range(3):
        video = tmp_path / f"v{i}.mp4"
        video.write_bytes(b"x")
        lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id=f"v{i}", url="u"), path=video)

    reason = lifecycle.should_reject_new_job()
    assert reason is not None
    assert "trượt" in reason
    assert "cấu hình" not in reason


# ---------------------------------------------------------------------------
# MUTATION (c): supportsAllDrives=True. Bỏ cờ này trong gdrive_upload.py
# phải làm test dưới đây ĐỎ. Dùng service Drive GIẢ (không mạng, không
# credential thật) để bắt đúng kwarg gửi lên API.
# ---------------------------------------------------------------------------

class _FakeFilesResource:
    def __init__(self, response: dict):
        self._response = response
        self.create_kwargs: dict | None = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self

    def execute(self):
        return self._response


class _FakeDriveService:
    def __init__(self, response: dict):
        self.files_resource = _FakeFilesResource(response)

    def files(self):
        return self.files_resource


def test_upload_file_always_sets_supports_all_drives(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    fake_service = _FakeDriveService(
        {"id": "file-1", "driveId": "shared-drive-1", "webViewLink": "https://x"}
    )
    uploader = DriveUploader(service_account_file=str(_fake_credential_file(tmp_path)),
                              folder_id="folder-1")
    monkeypatch.setattr(uploader, "_build_service", lambda: fake_service)

    result = uploader.upload_file(video)

    assert result.ok
    assert result.drive_id == "shared-drive-1"
    assert fake_service.files_resource.create_kwargs["supportsAllDrives"] is True


def test_upload_file_fails_when_response_has_no_drive_id(tmp_path, monkeypatch):
    """A response without `driveId` means the file did NOT land in a Shared
    Drive (e.g. `folder_id` itself is not inside one) — must be reported as
    FAILED, not SUCCESS, so the local copy is kept instead of vanishing into
    the wrong 15GB quota."""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    fake_service = _FakeDriveService({"id": "file-1", "webViewLink": "https://x"})
    uploader = DriveUploader(service_account_file=str(_fake_credential_file(tmp_path)),
                              folder_id="folder-1")
    monkeypatch.setattr(uploader, "_build_service", lambda: fake_service)

    result = uploader.upload_file(video)

    assert not result.ok
    assert result.outcome is UploadOutcome.FAILED


# ---------------------------------------------------------------------------
# Credential secrecy (constraint 6): never in the reason string, never in
# the log, and the file's permission bits get tightened before use.
# ---------------------------------------------------------------------------

def test_tighten_credential_permissions_restricts_to_owner_only(tmp_path):
    cred = tmp_path / "sa.json"
    cred.write_text("{}")
    cred.chmod(0o644)

    _tighten_credential_permissions(cred)

    mode = stat.S_IMODE(cred.stat().st_mode)
    # 0600, not 0700: this is a FILE (a service-account key), not a
    # directory — the execute bit has no meaning on it and 0700 grants a
    # bit real filesystems never need for a bearer secret.
    assert mode == 0o600


def test_upload_failure_never_leaks_credential_path_in_reason_or_log(tmp_path, monkeypatch, caplog):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cred_path = _fake_credential_file(tmp_path)
    uploader = DriveUploader(service_account_file=str(cred_path), folder_id="folder-1")

    class _BoomService:
        def files(self):
            raise RuntimeError(f"secret detail near {cred_path}")

    monkeypatch.setattr(uploader, "_build_service", lambda: _BoomService())

    with caplog.at_level("ERROR"):
        result = uploader.upload_file(video)

    assert not result.ok
    assert str(cred_path) not in (result.reason or "")
    assert str(cred_path) not in caplog.text


# ---------------------------------------------------------------------------
# Bước 6: "nhận link" — mỗi job có MỘT thư mục Drive riêng, link được lưu
# vào DB thay vì chỉ log rồi vứt.
# ---------------------------------------------------------------------------

def test_on_video_verified_creates_one_job_folder_and_reuses_it(tmp_path):
    """MUTATION: bỏ `_ensure_job_folder` (không tạo thư mục riêng, upload
    thẳng vào root) phải làm assertion `folder_calls` dưới ĐỎ."""
    fake = FakeUploader([_success("d1"), _success("d2"), _success("d3")])
    lifecycle.set_uploader(fake)

    for i in range(3):
        video = tmp_path / f"v{i}.mp4"
        video.write_bytes(b"x")
        lifecycle.on_video_verified(job_id=42, ref=VideoRef(video_id=f"v{i}", url="u"), path=video)

    assert fake.folder_calls == [42], "thư mục job phải chỉ được tạo MỘT LẦN cho cả job"
    assert all(parent == "folder-42" for _path, parent in fake.calls), (
        "mọi video của job phải upload vào ĐÚNG thư mục riêng của job đó"
    )


def test_on_video_verified_persists_drive_folder_link_to_db(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    fake = FakeUploader([_success()])
    lifecycle.set_uploader(fake)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    lifecycle.on_video_verified(job_id=job_id, ref=VideoRef(video_id="v", url="u"),
                                 path=video, db_path=db_path)

    job = models.get_job(db_path, job_id)
    assert job["drive_folder_link"] == f"https://drive/folder-{job_id}"


def test_on_video_verified_persists_folder_link_only_once_across_videos(tmp_path):
    """DB write for the link happens on folder CREATION, not on every
    video — a second video of the same job must not re-create the folder
    or re-write the (unchanged) link."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 2, "a")
    fake = FakeUploader([_success("d1"), _success("d2")])
    lifecycle.set_uploader(fake)

    for i in range(2):
        video = tmp_path / f"v{i}.mp4"
        video.write_bytes(b"x")
        lifecycle.on_video_verified(job_id=job_id, ref=VideoRef(video_id=f"v{i}", url="u"),
                                     path=video, db_path=db_path)

    assert fake.folder_calls == [job_id]
    job = models.get_job(db_path, job_id)
    assert job["drive_folder_link"] == f"https://drive/folder-{job_id}"


def test_on_video_verified_falls_back_to_root_folder_when_job_folder_creation_fails(tmp_path):
    """Job-folder creation is best-effort: a failure there must not block
    the video's own upload — it just uploads into the top-level folder
    (parent_folder_id=None) instead of a per-job one."""
    fake = FakeUploader([_success("d1")],
                         folder_result=_failed("folder create trượt"))
    lifecycle.set_uploader(fake)

    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    result = lifecycle.on_video_verified(job_id=7, ref=VideoRef(video_id="v", url="u"), path=video)

    assert result.ok
    assert not video.exists()
    assert fake.calls == [(video, None)]


def test_on_video_verified_skips_folder_link_write_without_db_path(tmp_path):
    """No `db_path` passed (e.g. a caller that does not care) must not
    raise — the write is simply skipped."""
    fake = FakeUploader([_success()])
    lifecycle.set_uploader(fake)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    result = lifecycle.on_video_verified(job_id=1, ref=VideoRef(video_id="v", url="u"), path=video)

    assert result.ok  # must not raise despite db_path=None


# ---------------------------------------------------------------------------
# Bước 7: cache credentials, build a FRESH service every call — never cache
# the service/transport itself (Broken-pipe lesson from
# ~/meta-ads-automation's creative_drive_client.py).
# ---------------------------------------------------------------------------

def test_build_service_creates_a_fresh_service_object_every_call(tmp_path, monkeypatch):
    """MUTATION: caching `self._service` (the old behavior) would make the
    two calls below return the SAME object — exactly the stale-socket reuse
    this fix removes."""
    cred_path = _fake_credential_file(tmp_path)
    uploader = DriveUploader(service_account_file=str(cred_path), folder_id="folder-1")
    monkeypatch.setattr(uploader, "_get_credentials", lambda: "fake-creds")

    built: list[tuple[object, object]] = []

    def _fake_build(name, version, credentials=None, cache_discovery=None):
        obj = object()
        built.append((obj, credentials))
        return obj

    import googleapiclient.discovery
    monkeypatch.setattr(googleapiclient.discovery, "build", _fake_build)

    service1 = uploader._build_service()
    service2 = uploader._build_service()

    assert service1 is not service2, "mỗi lần gọi phải build service MỚI, không cache lại"
    assert len(built) == 2
    assert all(creds == "fake-creds" for _obj, creds in built), (
        "credentials phải được TÁI SỬ DỤNG — chỉ service/transport là mới"
    )


def test_get_credentials_is_loaded_once_and_cached_across_calls(tmp_path, monkeypatch):
    cred_path = _fake_credential_file(tmp_path)
    uploader = DriveUploader(service_account_file=str(cred_path), folder_id="folder-1")

    load_calls: list[str] = []

    class _FakeCreds:
        pass

    def _fake_from_file(path, scopes=None):
        load_calls.append(path)
        return _FakeCreds()

    import google.oauth2.service_account as sa
    monkeypatch.setattr(sa.Credentials, "from_service_account_file",
                         staticmethod(_fake_from_file))

    first = uploader._get_credentials()
    second = uploader._get_credentials()

    assert first is second
    assert len(load_calls) == 1, "credentials phải load MỘT LẦN rồi cache, không load lại mỗi call"
