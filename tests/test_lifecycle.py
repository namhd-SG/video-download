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

import hashlib
import sqlite3
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tiktok_music_downloader.gdrive_upload import (
    DriveUploader,
    UploadOutcome,
    UploadResult,
    _tighten_credential_permissions,
)
from tiktok_music_downloader.utils import VideoRef
from tiktok_music_downloader.watermark import find_ffmpeg
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


# ---------------------------------------------------------------------------
# Thumbnail + catalogue capture (15/09). The whole point of this block is the
# window between "upload succeeded" and `path.unlink()`: it is the only moment
# the file both exists and is known to be on Drive, and ANY escape from it
# strands a multi-megabyte mp4 on a disk this tool does not own, with no DB row
# left to find it by. agy caught that in review; these tests are what stop it
# coming back.
# ---------------------------------------------------------------------------

def _ref(video_id: str = "7001", **kw) -> VideoRef:
    return VideoRef(video_id=video_id, url=f"https://www.tiktok.com/@a/video/{video_id}", **kw)


def test_local_file_is_deleted_even_when_recording_the_video_row_explodes(tmp_path):
    """ĐỘT BIẾN: để `record_video` văng ra ngoài ⇒ test này ĐỎ.

    Losing the row costs the INDEX (the video is on Drive, the store of
    record, and the row can be rebuilt). Letting the exception escape costs
    the DISK, and that cannot be rebuilt.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "7001.mp4"
    video.write_bytes(b"fake video bytes")
    lifecycle.set_uploader(FakeUploader([_success()]))

    def _boom(*a, **kw):
        raise sqlite3.OperationalError("database is locked")

    original = models.record_video
    models.record_video = _boom
    try:
        lifecycle.on_video_verified(job_id=1, ref=_ref(), path=video, db_path=db)
    finally:
        models.record_video = original

    assert not video.exists(), "DB lỗi KHÔNG được biến file mp4 thành rác mồ côi"


def test_local_file_is_deleted_even_when_the_thumbnail_step_explodes(tmp_path, monkeypatch):
    """Same window, the other new call."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "7002.mp4"
    video.write_bytes(b"fake video bytes")
    lifecycle.set_uploader(FakeUploader([_success()]))
    monkeypatch.setattr(lifecycle, "find_ffmpeg",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    lifecycle.on_video_verified(job_id=1, ref=_ref("7002"), path=video, db_path=db)

    assert not video.exists()


def test_video_row_survives_a_thumbnail_that_could_not_be_cut(tmp_path, monkeypatch):
    """A missing picture must not cost the catalogue entry: the video IS on
    Drive, and the grid can show a placeholder."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "7003.mp4"
    video.write_bytes(b"not really a video")
    lifecycle.set_uploader(FakeUploader([_success()]))
    monkeypatch.setattr(lifecycle, "find_ffmpeg", lambda: None)

    lifecycle.on_video_verified(job_id=1, ref=_ref("7003", region="VN"), path=video, db_path=db)

    rows = models.list_videos(db, None)
    assert [r["video_id"] for r in rows] == ["7003"]
    assert rows[0]["region"] == "VN"
    assert not lifecycle.thumb_path_for(db, "7003").exists()


def test_a_failed_upload_records_nothing(tmp_path):
    """Ca âm cho ba test trên: hàng `videos` khẳng định "video này ở trên
    Drive". Upload trượt thì không được có hàng nào, nếu không cả bảng thành
    lời nói dối."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "7004.mp4"
    video.write_bytes(b"fake video bytes")
    lifecycle.set_uploader(FakeUploader([_failed()]))

    lifecycle.on_video_verified(job_id=1, ref=_ref("7004"), path=video, db_path=db)

    assert models.list_videos(db, None) == []
    assert video.exists()


def test_thumbnail_is_cut_from_a_real_video_by_the_bundled_ffmpeg(tmp_path):
    """Đường thật, không giả: dựng một mp4 bằng chính ffmpeg đi kèm repo, rồi
    bắt lifecycle cắt ảnh từ nó. Bỏ bước cắt ảnh ⇒ test ĐỎ."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("repo's bundled ffmpeg not available here")
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "7005.mp4"
    made = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc=duration=3:size=320x568:rate=10", str(video)],
        capture_output=True, timeout=60)
    assert made.returncode == 0, made.stderr[:200]
    lifecycle.set_uploader(FakeUploader([_success()]))

    lifecycle.on_video_verified(job_id=1, ref=_ref("7005"), path=video, db_path=db)

    thumb = lifecycle.thumb_path_for(db, "7005")
    assert thumb.is_file(), "phải có ảnh sau khi cắt từ video thật"
    assert thumb.stat().st_size > 0
    # Không tin đuôi file: đọc lại bằng chính ffmpeg xem có phải ảnh thật không.
    probe = subprocess.run([ffmpeg, "-i", str(thumb)], capture_output=True,
                           text=True, timeout=30)
    assert "Video: webp" in probe.stderr, probe.stderr[:300]


def test_same_video_seen_under_two_hashtags_stays_one_row(tmp_path):
    """One file on Drive is one row, and the row keeps its FIRST sighting.

    This test used to assert the opposite — that a second sighting refreshed
    the row — because the first implementation used INSERT OR REPLACE. That
    was the bug: REPLACE rewrote `job_id` and `tao_luc`, so the "who
    downloaded it" and "when" filters silently reported the most recent
    re-download. Later sightings belong in `video_sightings`, not here.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="7006", url="u", region="MY")
    models.record_video(db, job_id=2, video_id="7006", url="u", region="SG")

    rows = models.list_videos(db, None)
    assert len(rows) == 1
    assert rows[0]["region"] == "MY", "lần đầu thắng, không phải lần sau"
    assert rows[0]["job_id"] == 1
    assert models.count_videos(db, None) == 1


# ---------------------------------------------------------------------------
# First sighting wins (15/09). The first version used INSERT OR REPLACE, which
# is DELETE+INSERT: meeting the same video under a second hashtag rewrote
# `job_id` and `tao_luc`, and those two columns are precisely what the
# "who downloaded it" and "when" filters read. The filters would have answered
# with the most recent RE-download — a wrong answer shaped like a right one.
# ---------------------------------------------------------------------------

def test_second_sighting_does_not_rewrite_who_or_when(tmp_path):
    """ĐỘT BIẾN: đổi lại thành INSERT OR REPLACE ⇒ test này ĐỎ."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="9001", url="u", region="MY")
    first = models.list_videos(db, None)[0]

    models.record_video(db, job_id=2, video_id="9001", url="u", region="SG")
    after = models.list_videos(db, None)[0]

    assert after["job_id"] == 1, "job_id phải giữ lần ĐẦU — nó nuôi bộ lọc 'người tải'"
    assert after["tao_luc"] == first["tao_luc"], "tao_luc phải giữ lần ĐẦU — bộ lọc 'ngày tải'"
    assert models.count_videos(db, None) == 1


def test_sightings_keep_every_source_including_skipped_ones(tmp_path):
    """Thẻ lọc theo nguồn đọc bảng này, không đọc `videos.job_id`.

    Ca `da_tai=False` là ca quan trọng: video bị bỏ qua vì trùng KHÔNG bao giờ
    đi vào đường tải, nên đây là chỗ DUY NHẤT hashtag thứ hai được ghi lại.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="9002", url="u")
    models.record_sighting(db, video_id="9002", job_id=1, nguon="#80ssaudi", da_tai=True)
    models.record_sighting(db, video_id="9002", job_id=2, nguon="#retro", da_tai=False)

    sources = models.sources_for_videos(db, ["9002"], None)

    assert sources["9002"] == ["#80ssaudi", "#retro"]


def test_known_video_ids_only_reports_what_we_actually_have(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="9003", url="u")

    assert models.known_video_ids(db, ["9003", "9004"]) == {"9003"}
    # Ca âm: danh sách rỗng không được nổ, và không được trả nhầm cả bảng.
    assert models.known_video_ids(db, []) == set()


def test_music_id_and_drive_file_id_survive_the_round_trip(tmp_path):
    """Cả hai đều là thứ 'chờ thì mất': music id chỉ có trong response index,
    file id chỉ có trong kết quả upload."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="9005", url="u",
                        music_id="7218", drive_file_id="1AbC")

    row = models.list_videos(db, None)[0]
    assert row["music_id"] == "7218"
    assert row["drive_file_id"] == "1AbC"


def test_drive_file_id_is_the_file_not_the_shared_drive(tmp_path):
    """`UploadResult` mang CẢ `file_id` lẫn `drive_id`; `drive_id` giống hệt
    nhau cho mọi file, nên nhầm hai cái là mọi thẻ trỏ về cùng một chỗ."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "9006.mp4"
    video.write_bytes(b"fake video bytes")
    lifecycle.set_uploader(FakeUploader([_success()]))

    lifecycle.on_video_verified(job_id=1, ref=_ref("9006"), path=video, db_path=db)

    row = models.list_videos(db, None)[0]
    success = _success()
    assert row["drive_file_id"] == success.file_id
    assert row["drive_file_id"] != success.drive_id


# ---------------------------------------------------------------------------
# Trần job/ngày theo COOKIE — user chốt 15/09: 20 job, mỗi cookie, ngày giờ VN.
# Ca phân định nằm ở khung 00:00-07:00 giờ VN: đó là khoảng mà ngày VN và ngày
# UTC KHÁC nhau, tức khoảng duy nhất một bản cắt-theo-UTC sẽ đếm sai.
# ---------------------------------------------------------------------------

def _insert_job_at(db: Path, tao_luc: str, nguoi_tao: str = "khach",
                   tong: int = 0) -> None:
    """Một hàng job với thời điểm ĐẶT SẴN. `models.create_job` luôn đóng dấu
    `_now()`, mà mốc thời gian chính là thứ đang đo."""
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO jobs (url, trang_thai, tong, xong, loi, tao_luc, nguoi_tao) "
            "VALUES ('https://www.tiktok.com/tag/x', 'xong', ?, 0, 0, ?, ?)",
            (tong, tao_luc, nguoi_tao),
        )


def _cookies_dir_with_jar(tmp_path: Path, *nguoi_tao: str) -> Path:
    cookies = tmp_path / "cookies"
    cookies.mkdir(exist_ok=True)
    for who in nguoi_tao:
        digest = hashlib.sha256(who.encode("utf-8")).hexdigest()
        (cookies / f"{digest}.json").write_text("[]", encoding="utf-8")
    return cookies


def test_vn_day_starts_at_midnight_in_vietnam_not_utc():
    now = datetime(2026, 9, 15, 16, 30, tzinfo=timezone.utc)  # 23:30 VN cùng ngày
    assert lifecycle.vn_day_start_utc(now).startswith("2026-09-14T17:00:00")


def test_a_job_from_this_morning_counts_though_utc_still_calls_it_yesterday(tmp_path):
    """06:00 giờ VN là HÔM NAY với người dùng nhưng vẫn là hôm qua theo UTC.
    Bản cắt ngày bằng tiền tố chuỗi của `tao_luc` (lưu UTC) bỏ sót đúng ca này
    — trần sẽ tự reset lúc 07:00 sáng, giữa buổi làm việc."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    _insert_job_at(db, "2026-09-14T23:00:00.000000+00:00")  # 06:00 VN ngày 15
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)  # 10:00 VN ngày 15

    assert lifecycle.jobs_today_for_cookie(db, cookies, "khach", now) == 1


def test_a_job_from_last_night_does_not_count(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    _insert_job_at(db, "2026-09-14T16:59:00.000000+00:00")  # 23:59 VN ngày 14
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)

    assert lifecycle.jobs_today_for_cookie(db, cookies, "khach", now) == 0


def test_two_cookies_are_counted_separately(tmp_path):
    """Trần là của cái NICK, không phải của cái người: hai jar khác nhau thì
    hai bộ đếm khác nhau, kể cả khi cùng chạy trên một máy."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path, "namhd")  # "khach" không có jar
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", "namhd")
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", "khach")
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)

    assert lifecycle.jobs_today_for_cookie(db, cookies, "namhd", now) == 1
    assert lifecycle.jobs_today_for_cookie(db, cookies, "khach", now) == 1


def test_jobs_with_no_cookie_share_one_counter(tmp_path):
    """Không có jar nào thì mọi người đi chung một danh tính ẩn danh — vẫn là
    một nick nhìn từ một IP, nên vẫn bị trần, không phải được miễn."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", "an")
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", "binh")
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)

    assert lifecycle.jobs_today_for_cookie(db, cookies, "an", now) == 2


def test_daily_cap_lets_the_last_allowed_job_through_then_refuses(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    for _ in range(lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY - 1):
        _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00")

    assert lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=cookies, nguoi_tao="khach", so_luong=1, now=now) is None

    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00")
    reason = lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=cookies, nguoi_tao="khach", so_luong=1, now=now)

    assert reason is not None
    assert str(lifecycle.MAX_JOBS_PER_COOKIE_PER_DAY) in reason


def test_failed_jobs_still_count_against_the_cap(tmp_path):
    """Job hỏng vẫn đã tiêu lượt gọi TikTok — thứ đang được chia khẩu phần."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO jobs (url, trang_thai, tong, xong, loi, tao_luc, nguoi_tao) "
            "VALUES ('https://www.tiktok.com/tag/x', 'loi', 0, 0, 1, ?, 'khach')",
            ("2026-09-15T02:00:00.000000+00:00",),
        )
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)

    assert lifecycle.jobs_today_for_cookie(db, cookies, "khach", now) == 1


# ---------------------------------------------------------------------------
# Trần theo SỐ VIDEO. Trần job một mình không bó được lưu lượng: một job xin
# tới MAX_SO_LUONG=2000 video, nên 20 job vẫn là 40 000 video/ngày.
# ---------------------------------------------------------------------------

def test_a_big_job_is_refused_even_when_the_job_count_is_fine(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    # MỘT job hôm nay -> trần job (20) còn rất rộng; trần video mới là cái cắn.
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", tong=900)

    reason = lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=cookies, nguoi_tao="khach", so_luong=200, now=now)

    assert reason is not None
    assert "video" in reason
    assert "1 job" not in reason, "phải là lý do TRẦN VIDEO, không phải trần job"


def test_a_job_that_exactly_fits_the_remaining_budget_is_allowed(tmp_path):
    """Ca dương: nếu phép so là `>=` thay vì `>`, test trên vẫn xanh trong khi
    trần đã cắn sớm một video."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", tong=900)

    assert lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=cookies, nguoi_tao="khach",
        so_luong=lifecycle.MAX_VIDEOS_PER_COOKIE_PER_DAY - 900, now=now) is None


def test_video_budget_is_shared_by_the_cookie_not_the_person(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)  # không ai có jar -> chung ẩn danh
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", nguoi_tao="an", tong=600)
    _insert_job_at(db, "2026-09-15T02:00:00.000000+00:00", nguoi_tao="binh", tong=300)

    assert lifecycle.videos_today_for_cookie(db, cookies, "an", now) == 900


def test_yesterdays_videos_do_not_eat_todays_budget(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    _insert_job_at(db, "2026-09-14T16:59:00.000000+00:00", tong=2000)  # 23:59 VN hôm qua

    assert lifecycle.videos_today_for_cookie(db, cookies, "khach", now) == 0


# ---------------------------------------------------------------------------
# Backfill cần ghi ĐÚNG thời điểm cũ. Không có tham số này thì hàng nhập lại
# mang dấu thời gian HÔM NAY, và bộ lọc "Ngày tải" — vốn đọc `videos.tao_luc`
# — sẽ nói video tải từ 14/09 là tải hôm nay.
# ---------------------------------------------------------------------------

def test_record_video_defaults_to_now_but_accepts_a_real_time(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="111", url="u")
    models.record_video(db, job_id=1, video_id="222", url="u",
                        tao_luc="2026-09-14T10:43:08.000000+00:00")

    rows = {r["video_id"]: r["tao_luc"] for r in models.list_videos(db, None)}
    assert rows["222"] == "2026-09-14T10:43:08.000000+00:00"
    assert rows["111"] != rows["222"], "bỏ tham số thì phải là thời điểm hiện tại"


def test_record_sighting_accepts_a_real_time(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_sighting(db, video_id="111", job_id=1,
                           nguon="https://www.tiktok.com/tag/80ssaudi", da_tai=True,
                           thay_luc="2026-09-14T10:43:08.000000+00:00")

    with sqlite3.connect(db) as conn:
        thay_luc = conn.execute("SELECT thay_luc FROM video_sightings").fetchone()[0]
    assert thay_luc == "2026-09-14T10:43:08.000000+00:00"


# ---------------------------------------------------------------------------
# Ảnh: ffmpeg -y TẠO tệp ra TRƯỚC rồi mới hỏng. Không dọn thì còn lại một tệp
# .webp 0 byte, mà `/thumbs` chỉ hỏi `is_file()` ⇒ trả 200 kèm thân RỖNG mãi
# mãi cho video đó, và mọi lượt cắt lại dựa trên `exists()` bỏ qua vĩnh viễn.
# Bất biến của lớp này là "tệp có trên đĩa CHÍNH LÀ sự thật rằng có ảnh".
# ---------------------------------------------------------------------------

def _video_ngan(tmp_path: Path, giay: float) -> Path:
    """Dựng một video thật ngắn hơn `THUMB_SEEK_SECONDS` bằng ffmpeg của repo."""
    from tiktok_music_downloader.watermark import find_ffmpeg
    ff = find_ffmpeg()
    assert ff, "repo có bundle ffmpeg; thiếu nó thì test này vô nghĩa"
    out = tmp_path / "ngan.mp4"
    subprocess.run([str(ff), "-y", "-f", "lavfi", "-i", f"testsrc=duration={giay}:size=64x64:rate=10",
                    "-pix_fmt", "yuv420p", str(out)],
                   capture_output=True, check=True)
    return out


def test_a_video_shorter_than_the_seek_point_leaves_no_empty_thumbnail(tmp_path):
    """ĐỘT BIẾN: bỏ lời gọi dọn tệp ở nhánh `rc != 0` ⇒ ĐỎ.

    `-ss 1` vượt quá độ dài video 0,5s nên ffmpeg không lấy được khung nào và
    trả mã khác 0 — nhưng tệp ra đã được tạo trước đó."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = _video_ngan(tmp_path, 0.5)

    ok = lifecycle._cut_thumbnail_quietly(video, db, "7001")

    assert ok is False, "cắt trượt thì phải trả False"
    duong_anh = lifecycle.thumb_path_for(db, "7001")
    assert not duong_anh.exists(), (
        f"còn tệp dở {duong_anh.stat().st_size if duong_anh.exists() else '?'} byte — "
        "/thumbs sẽ trả 200 rỗng cho video này mãi mãi")


def test_a_normal_video_still_gets_its_thumbnail(tmp_path):
    """CA DƯƠNG bắt buộc: thiếu nó thì một bản vá 'luôn xoá tệp ra' vẫn xanh
    test trên trong khi đã làm hỏng toàn bộ tính năng ảnh."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = _video_ngan(tmp_path, 3)

    ok = lifecycle._cut_thumbnail_quietly(video, db, "7002")

    assert ok is True
    duong_anh = lifecycle.thumb_path_for(db, "7002")
    assert duong_anh.is_file() and duong_anh.stat().st_size > 0


def test_ffmpeg_reporting_success_with_an_empty_file_is_still_a_failure(tmp_path, monkeypatch):
    """Nhánh KHÁC với test trên: ffmpeg trả rc=0 nhưng tệp ra rỗng.

    Video 0,5s cho rc≠0 nên không chạm nhánh này — phải giả lập đúng kết quả
    đó. Đây là nhánh mà review chỉ ra là CÂM: bản cũ `return out.exists()` trả
    True cho một tệp 0 byte, và `/thumbs` sẽ phục vụ 200 kèm thân rỗng mãi mãi.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"khong can la video that")
    duong_anh = lifecycle.thumb_path_for(db, "7003")

    def _ffmpeg_gia(cmd, **kw):
        # Y HỆT ffmpeg: tạo tệp ra rồi báo thành công, nhưng không ghi gì.
        duong_anh.parent.mkdir(parents=True, exist_ok=True)
        duong_anh.touch()
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(lifecycle.subprocess, "run", _ffmpeg_gia)

    ok = lifecycle._cut_thumbnail_quietly(video, db, "7003")

    assert ok is False, "tệp 0 byte không phải là ảnh"
    assert not duong_anh.exists(), "tệp rỗng phải bị dọn, không được để /thumbs phục vụ nó"


# ---------------------------------------------------------------------------
# Trần LIỆT KÊ + miễn trừ "nguồn đã cạn" (user chốt 16/09, đường A).
#
# Quét một hashtag team đã tải hết KHÔNG trừ vào trần 20 lượt/ngày — người dùng
# không làm gì sai. Nhưng lượt đó vẫn đọc ~40 trang index, nên nó phải tốn của
# một trần KHÁC, nếu không thì lặp vô hạn miễn phí và rate-limit đánh cả văn
# phòng (plan R6).
# ---------------------------------------------------------------------------

def _job_xong(db, tao_luc, *, ly_do=None, so_trang=0, nguoi_tao="khach"):
    _insert_job_at(db, tao_luc, nguoi_tao=nguoi_tao)
    with sqlite3.connect(db) as conn:
        jid = conn.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
        conn.execute("UPDATE jobs SET ly_do_dung = ?, so_trang = ? WHERE id = ?",
                     (ly_do, so_trang, jid))
    return jid


def test_an_exhausted_source_does_not_burn_a_daily_job(tmp_path):
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    for _ in range(5):
        _job_xong(db, "2026-09-15T02:00:00.000000+00:00", ly_do="already_owned", so_trang=40)

    assert lifecycle.jobs_today_for_cookie(db, cookies, "khach", now) == 0


def test_a_failed_listing_still_burns_a_daily_job(tmp_path):
    """CA ÂM chống lách trần: nếu miễn cả `index_failed` thì ép lỗi là cách
    chạy vô hạn. Chỉ ca "đã sở hữu hết" mới được miễn."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    for _ in range(3):
        _job_xong(db, "2026-09-15T02:00:00.000000+00:00", ly_do="index_failed", so_trang=5)

    assert lifecycle.jobs_today_for_cookie(db, cookies, "khach", now) == 3


def test_repeating_an_exhausted_source_eventually_hits_the_listing_cap(tmp_path):
    """ĐỘT BIẾN: bỏ cổng trần liệt kê trong `daily_cap_rejection` ⇒ ĐỎ.

    Đây là ca chỉ thị của user mở ra: lượt "đã cạn" không tốn trần job, nên nếu
    không có trần này thì lặp bao nhiêu cũng được, mỗi lần ~40 trang index."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    # 20 lượt "đã cạn" × 40 trang = 800 — đúng mức trần.
    for _ in range(20):
        _job_xong(db, "2026-09-15T02:00:00.000000+00:00", ly_do="already_owned", so_trang=40)

    assert lifecycle.jobs_today_for_cookie(db, cookies, "khach", now) == 0, \
        "không lượt nào bị trừ vào trần job — đó là ý của quyết định"
    ly_do = lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=cookies, nguoi_tao="khach", so_luong=1, now=now)
    assert ly_do is not None and "trang index" in ly_do, \
        "lặp nguồn đã cạn phải chạm trần LIỆT KÊ, dù trần job còn nguyên"


def test_the_listing_cap_leaves_ordinary_use_alone(tmp_path):
    """CA DƯƠNG: trần 800 neo vào mức hôm nay (20 lượt × 40 trang) nên KHÔNG
    được siết chặt hơn hiện trạng. Một ngày làm bình thường phải đi lọt."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    cookies = _cookies_dir_with_jar(tmp_path)
    now = datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)
    for _ in range(10):
        _job_xong(db, "2026-09-15T02:00:00.000000+00:00", so_trang=12)

    assert lifecycle.daily_cap_rejection(
        db_path=db, cookies_dir=cookies, nguoi_tao="khach", so_luong=20, now=now) is None
