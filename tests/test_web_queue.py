"""Tests for the web job queue: models.py + queue.py.

Covers the four mutation-tested invariants from the phase-02 plan (a-d) plus
the supporting plumbing (job CRUD, FIFO claim order, per-video verification
gate, lifecycle hook wiring). Uses `tmp_path` for a fresh SQLite file per
test — no shared state, no network, no real Chromium/yt-dlp calls.
"""
from __future__ import annotations

import json

import hashlib
import sqlite3
import time
from pathlib import Path

import pytest

from tiktok_music_downloader import hashtag_enumerator as he

from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from tiktok_music_downloader.utils import VideoRef
from web import models
from web import queue as queue_mod
from web.queue import JobWorker, _JobProgress, process_job

_UPLOAD_OK = UploadResult(outcome=UploadOutcome.SUCCESS, file_id="f1", drive_id="d1")
_UPLOAD_FAILED = UploadResult(outcome=UploadOutcome.FAILED, reason="upload trượt")


# ---------------------------------------------------------------------------
# models.py: basic CRUD + FIFO ordering
# ---------------------------------------------------------------------------

def test_create_and_get_job_roundtrip(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 20, "namhd")
    job = models.get_job(db_path, job_id)
    assert job["url"] == "https://www.tiktok.com/music/x-1"
    assert job["trang_thai"] == "pending"
    assert job["tong"] == 20
    assert job["xong"] == 0
    assert job["loi"] == 0
    assert job["nguoi_tao"] == "namhd"
    assert job["tao_luc"] is not None
    assert job["bat_dau_luc"] is None
    assert job["xong_luc"] is None
    assert job["drive_folder_link"] is None


def test_set_job_drive_folder_link_persists_and_is_returned_by_get_job(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")

    models.set_job_drive_folder_link(db_path, job_id, "https://drive.google.com/drive/folders/x")

    job = models.get_job(db_path, job_id)
    assert job["drive_folder_link"] == "https://drive.google.com/drive/folders/x"


def test_init_db_backfills_drive_folder_link_onto_a_preexisting_table(tmp_path):
    """A `jobs.db` created before this column existed must still work after
    an upgrade — `CREATE TABLE IF NOT EXISTS` alone would silently skip it."""
    db_path = tmp_path / "jobs.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, "
            "trang_thai TEXT NOT NULL DEFAULT 'pending', tong INTEGER NOT NULL DEFAULT 0, "
            "xong INTEGER NOT NULL DEFAULT 0, loi INTEGER NOT NULL DEFAULT 0, "
            "tao_luc TEXT NOT NULL, bat_dau_luc TEXT, xong_luc TEXT, "
            "nguoi_tao TEXT NOT NULL DEFAULT 'khach')"
        )
        conn.commit()

    models.init_db(db_path)  # must not raise
    job_id = models.create_job(db_path, "u", 1, "a")
    models.set_job_drive_folder_link(db_path, job_id, "https://drive/x")
    assert models.get_job(db_path, job_id)["drive_folder_link"] == "https://drive/x"


def test_get_job_missing_returns_none(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    assert models.get_job(db_path, 999) is None


def test_list_jobs_orders_newest_first(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    j1 = models.create_job(db_path, "u1", 1, "a")
    j2 = models.create_job(db_path, "u2", 1, "a")
    jobs = models.list_jobs(db_path)
    assert [j["id"] for j in jobs] == [j2, j1]


def test_claim_next_pending_job_is_fifo_and_flips_to_running(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    j1 = models.create_job(db_path, "u1", 1, "a")
    j2 = models.create_job(db_path, "u2", 1, "a")

    claimed = models.claim_next_pending_job(db_path)
    assert claimed["id"] == j1
    assert claimed["trang_thai"] == "running"
    assert claimed["bat_dau_luc"] is not None
    assert models.get_job(db_path, j1)["trang_thai"] == "running"

    # j1 is no longer pending -> next claim must return j2, not j1 again.
    claimed2 = models.claim_next_pending_job(db_path)
    assert claimed2["id"] == j2


def test_claim_next_pending_job_returns_none_when_empty(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    assert models.claim_next_pending_job(db_path) is None


def test_finish_job_rejects_non_terminal_state(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    with pytest.raises(ValueError):
        models.finish_job(db_path, job_id, "running")


# ---------------------------------------------------------------------------
# Invariant (b): boot sweep flips stale 'running' rows to 'interrupted'.
# `KeepAlive` restarts via SIGKILL, so a crashed job's row never gets a
# `finally` to clean up after itself — this sweep is the only thing that
# stops it staying 'running' forever. Bỏ bước quét lúc boot ⇒ test này ĐỎ.
# ---------------------------------------------------------------------------

def test_boot_sweep_marks_stale_running_jobs_interrupted(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 5, "a")
    # Simulate a crash mid-job: force the row to 'running' with no clean exit,
    # bypassing the normal claim path (which the crashed process never got
    # to complete cleanly for this test's purposes).
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE jobs SET trang_thai='running' WHERE id=?", (job_id,))
        conn.commit()

    changed = models.mark_running_as_interrupted(db_path)

    assert changed == 1
    job = models.get_job(db_path, job_id)
    assert job["trang_thai"] == "interrupted"
    assert job["xong_luc"] is not None  # mốc ghi SAU khi quét, không bỏ trống


def test_boot_sweep_leaves_pending_and_done_jobs_alone(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    pending_id = models.create_job(db_path, "u1", 1, "a")
    done_id = models.create_job(db_path, "u2", 1, "a")
    models.finish_job(db_path, done_id, "done")

    changed = models.mark_running_as_interrupted(db_path)

    assert changed == 0
    assert models.get_job(db_path, pending_id)["trang_thai"] == "pending"
    assert models.get_job(db_path, done_id)["trang_thai"] == "done"


def test_worker_start_runs_boot_sweep_before_processing(tmp_path):
    """JobWorker.start() must call the sweep itself — a caller who forgets
    to wire it up should not be able to skip it."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE jobs SET trang_thai='running' WHERE id=?", (job_id,))
        conn.commit()

    worker = JobWorker(db_path, tmp_path / "dl", tmp_path / "ck",
                        poll_interval=0.01, process_job_fn=lambda *a: None)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        job = models.get_job(db_path, job_id)
        while job["trang_thai"] != "interrupted" and time.monotonic() < deadline:
            time.sleep(0.02)
            job = models.get_job(db_path, job_id)
        assert job["trang_thai"] == "interrupted"
    finally:
        worker.stop()


# ---------------------------------------------------------------------------
# Invariant (a): "xong" (done) is only written AFTER video-stream
# verification passes; a stream-less file counts as an error, not a success.
# Bỏ bước xác minh ⇒ test này ĐỎ.
# ---------------------------------------------------------------------------

def _make_progress(db_path, job_id, ref, output_dir, hook, monkeypatch, verified: bool):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ref.filename).write_bytes(b"fake bytes, content irrelevant here")
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda path: verified)
    return _JobProgress(db_path, job_id, [ref], output_dir, hook)


def test_downloaded_video_without_stream_counts_as_error_not_done(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    ref = VideoRef(video_id="1", url="https://www.tiktok.com/@x/video/1")
    hook_calls = []

    progress = _make_progress(db_path, job_id, ref, tmp_path / "out",
                               lambda **kw: hook_calls.append(kw),
                               monkeypatch, verified=False)
    progress.note("downloaded")

    job = models.get_job(db_path, job_id)
    assert job["xong"] == 0, "file không có luồng video KHÔNG được tính là xong"
    assert job["loi"] == 1
    assert hook_calls == [], "lifecycle hook không được gọi cho file chưa qua xác minh"


def test_downloaded_video_with_stream_counts_as_done_and_fires_lifecycle(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    ref = VideoRef(video_id="1", url="https://www.tiktok.com/@x/video/1")
    hook_calls = []

    def _hook(**kw):
        hook_calls.append(kw)
        return _UPLOAD_OK

    progress = _make_progress(db_path, job_id, ref, tmp_path / "out",
                               _hook, monkeypatch, verified=True)
    progress.note("downloaded")

    job = models.get_job(db_path, job_id)
    assert job["xong"] == 1
    assert job["loi"] == 0
    assert len(hook_calls) == 1
    assert hook_calls[0]["ref"] is ref
    assert hook_calls[0]["job_id"] == job_id


def test_downloaded_video_with_stream_but_lifecycle_hook_fails_counts_as_error(tmp_path, monkeypatch):
    """MUTATION target Bước 3: mốc "xong" phải ghi SAU khi biết hook thật sự
    thành công. Bỏ điều kiện `if result.ok:` (coi mọi lời gọi hook là xong)
    phải làm test này ĐỎ."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    ref = VideoRef(video_id="1", url="https://www.tiktok.com/@x/video/1")

    progress = _make_progress(db_path, job_id, ref, tmp_path / "out",
                               lambda **kw: _UPLOAD_FAILED, monkeypatch, verified=True)
    progress.note("downloaded")

    job = models.get_job(db_path, job_id)
    assert job["xong"] == 0, "hook trượt (chưa lên Drive) thì KHÔNG được tính là xong"
    assert job["loi"] == 1


def test_failed_download_counts_as_error_and_skips_verification(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    ref = VideoRef(video_id="1", url="https://www.tiktok.com/@x/video/1")

    def _boom(path):
        raise AssertionError("verify_video_stream must not run for a failed download")

    monkeypatch.setattr(queue_mod, "verify_video_stream", _boom)
    progress = _JobProgress(db_path, job_id, [ref], tmp_path / "out", lambda **kw: None)
    progress.note("failed")

    job = models.get_job(db_path, job_id)
    assert job["xong"] == 0
    assert job["loi"] == 1


def test_skipped_video_counts_toward_neither_done_nor_error(tmp_path):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "u", 1, "a")
    ref = VideoRef(video_id="1", url="https://www.tiktok.com/@x/video/1")

    progress = _JobProgress(db_path, job_id, [ref], tmp_path / "out", lambda **kw: None)
    progress.note("skipped")

    job = models.get_job(db_path, job_id)
    assert job["xong"] == 0
    assert job["loi"] == 0


# ---------------------------------------------------------------------------
# verify_video_stream: real behavior against real ffmpeg stderr shapes.
# ---------------------------------------------------------------------------

def test_verify_video_stream_true_for_a_line_matching_stream_video(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")

    class _Result:
        stderr = ("Stream #0:0[0x1](und): Video: h264 (High), yuv420p, 64x64\n"
                   "Stream #0:1: Audio: aac, 44100 Hz")

    monkeypatch.setattr(queue_mod.subprocess, "run", lambda *a, **kw: _Result())
    assert queue_mod.verify_video_stream(path, ffmpeg_bin="/usr/bin/ffmpeg") is True


def test_verify_video_stream_false_when_only_audio_stream(tmp_path, monkeypatch):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"x")

    class _Result:
        stderr = "Stream #0:0: Audio: mp3, 44100 Hz"

    monkeypatch.setattr(queue_mod.subprocess, "run", lambda *a, **kw: _Result())
    assert queue_mod.verify_video_stream(path, ffmpeg_bin="/usr/bin/ffmpeg") is False


def test_verify_video_stream_false_when_file_missing(tmp_path):
    assert queue_mod.verify_video_stream(
        tmp_path / "missing.mp4", ffmpeg_bin="/usr/bin/ffmpeg"
    ) is False


def test_verify_video_stream_false_when_ffmpeg_unresolvable(tmp_path, monkeypatch):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"x")
    monkeypatch.setattr(queue_mod, "find_ffmpeg", lambda: None)
    assert queue_mod.verify_video_stream(path, ffmpeg_bin=None) is False


def _real_ffmpeg_or_skip() -> str:
    from tiktok_music_downloader.watermark import find_ffmpeg
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("no ffmpeg binary resolvable on this machine")
    return ffmpeg


def test_verify_video_stream_against_real_ffmpeg_on_a_generated_clip(tmp_path):
    """Integration check with the actual bundled binary, not a mocked
    stderr string — proves the regex matches ffmpeg's real output shape."""
    import subprocess

    ffmpeg = _real_ffmpeg_or_skip()
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [ffmpeg, "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5",
         "-y", str(clip), "-loglevel", "error"],
        check=True, timeout=30,
    )
    assert queue_mod.verify_video_stream(clip, ffmpeg_bin=ffmpeg) is True

    audio_only = tmp_path / "audio.mp3"
    subprocess.run(
        [ffmpeg, "-f", "lavfi", "-i", "sine=duration=1", "-y", str(audio_only),
         "-loglevel", "error"],
        check=True, timeout=30,
    )
    assert queue_mod.verify_video_stream(audio_only, ffmpeg_bin=ffmpeg) is False


# ---------------------------------------------------------------------------
# Invariant (c): every scraper call from the web layer passes profile_dir=None.
# launch_persistent_context (profile_dir set) keeps cookies on disk across
# runs -> a cross-user cookie leak on a shared service. Truyền giá trị khác
# ⇒ test này ĐỎ.
# ---------------------------------------------------------------------------

def test_scraper_call_always_passes_profile_dir_none(monkeypatch):
    captured = {}

    def fake_scrape_music_page(url, max_videos=None, cookies_path=None, proxy=None,
                                profile_dir="__NOT_PASSED__"):
        captured["profile_dir"] = profile_dir
        return []

    monkeypatch.setattr(queue_mod, "scrape_music_page", fake_scrape_music_page)
    queue_mod._fetch_refs("https://www.tiktok.com/music/song-123", max_videos=10,
                          cookies_path=None)

    assert captured["profile_dir"] is None


def test_hashtag_urls_never_reach_the_scraper(monkeypatch):
    """A /tag/ URL must go through enumerate_hashtag, which has no
    profile_dir/cookie surface at all — never through the browser scraper."""
    def _boom(*args, **kwargs):
        raise AssertionError("scrape_music_page must not be called for a /tag/ URL")

    monkeypatch.setattr(queue_mod, "scrape_music_page", _boom)
    monkeypatch.setattr(queue_mod, "enumerate_hashtag",
                         lambda tag, max_videos, proxy=None, **kw: [])
    queue_mod._fetch_refs("https://www.tiktok.com/tag/anos80", max_videos=10,
                          cookies_path=None)


# ---------------------------------------------------------------------------
# Invariant (d): two jobs submitted together run SEQUENTIALLY, not in
# parallel — proven by bat_dau_luc/xong_luc timestamps in the DB, not by
# reasoning about the code. Chạy song song ⇒ test này ĐỎ.
# ---------------------------------------------------------------------------

def test_two_jobs_submitted_together_run_sequentially(tmp_path):
    db_path = tmp_path / "jobs.db"
    downloads_dir = tmp_path / "downloads"
    cookies_dir = tmp_path / "cookies"
    models.init_db(db_path)

    def fake_process_job(db_path_, downloads_dir_, cookies_dir_, job):
        # Simulate a slow job (one Chromium session) without touching the
        # network — long enough that two overlapping runs would be visible
        # in the timestamps if the queue were not sequential.
        time.sleep(0.15)
        models.finish_job(db_path_, job["id"], "done")

    job1_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    job2_id = models.create_job(db_path, "https://www.tiktok.com/music/y-2", 1, "b")

    worker = JobWorker(db_path, downloads_dir, cookies_dir, poll_interval=0.01,
                        process_job_fn=fake_process_job)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            j1 = models.get_job(db_path, job1_id)
            j2 = models.get_job(db_path, job2_id)
            if j1["trang_thai"] == "done" and j2["trang_thai"] == "done":
                break
            time.sleep(0.02)
    finally:
        worker.stop()

    j1 = models.get_job(db_path, job1_id)
    j2 = models.get_job(db_path, job2_id)
    assert j1["trang_thai"] == "done"
    assert j2["trang_thai"] == "done"
    assert j1["bat_dau_luc"] is not None and j1["xong_luc"] is not None
    assert j2["bat_dau_luc"] is not None and j2["xong_luc"] is not None
    # job2 cannot have started before job1 fully finished — ISO-8601 UTC
    # strings sort correctly as plain text.
    assert j1["xong_luc"] <= j2["bat_dau_luc"], (
        f"job1 xong_luc={j1['xong_luc']!r} > job2 bat_dau_luc={j2['bat_dau_luc']!r} "
        "=> hai job chồng lấp thời gian, không tuần tự"
    )


def test_process_job_marks_failed_on_exception_without_crashing_caller(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 5, "a")
    job = models.get_job(db_path, job_id)

    def _boom(url, max_videos, cookies_path, proxy=None):
        raise RuntimeError("network exploded")

    monkeypatch.setattr(queue_mod, "_fetch_refs", _boom)
    process_job(db_path, tmp_path / "dl", tmp_path / "ck", job)

    job = models.get_job(db_path, job_id)
    assert job["trang_thai"] == "failed"
    assert job["xong_luc"] is not None


def test_process_job_with_zero_refs_marks_done_with_zero_total(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "https://www.tiktok.com/tag/empty", 20, "a")
    job = models.get_job(db_path, job_id)

    monkeypatch.setattr(queue_mod, "_fetch_refs", lambda *a, **kw: [])
    process_job(db_path, tmp_path / "dl", tmp_path / "ck", job)

    job = models.get_job(db_path, job_id)
    assert job["trang_thai"] == "done"
    assert job["tong"] == 0


def test_process_job_marks_failed_when_every_ref_errors_without_raising(tmp_path, monkeypatch):
    """tong > 0 mà xong == 0 (mọi ref lỗi hoặc chưa lên được Drive) không
    phải là "done" dù download_all không raise gì."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    job = models.get_job(db_path, job_id)
    ref = VideoRef(video_id="1", url="https://www.tiktok.com/@x/video/1")

    monkeypatch.setattr(queue_mod, "_fetch_refs", lambda *a, **kw: [ref])

    def fake_download_all(refs, output_dir, cookies_path=None, progress=None):
        progress.note("failed")

    monkeypatch.setattr(queue_mod, "download_all", fake_download_all)
    process_job(db_path, tmp_path / "dl", tmp_path / "ck", job)

    job = models.get_job(db_path, job_id)
    assert job["trang_thai"] == "failed"
    assert job["tong"] == 1
    assert job["xong"] == 0
    assert job["loi"] == 1


# ---------------------------------------------------------------------------
# MUTATION Bước 3: mốc kết thúc (finish_job) phải ghi SAU khi download_all
# xong, không được dời lên trước. Đảo thứ tự hai lời gọi trong process_job
# phải làm test dưới đây ĐỎ.
# ---------------------------------------------------------------------------

def test_finish_job_is_not_called_before_download_all_completes(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 1, "a")
    job = models.get_job(db_path, job_id)
    ref = VideoRef(video_id="1", url="https://www.tiktok.com/@x/video/1")

    monkeypatch.setattr(queue_mod, "_fetch_refs", lambda *a, **kw: [ref])

    def fake_download_all(refs, output_dir, cookies_path=None, progress=None):
        mid_job = models.get_job(db_path, job_id)
        assert mid_job["trang_thai"] not in ("done", "failed"), (
            "finish_job đã ghi mốc kết thúc TRƯỚC khi download_all xong "
            "— mốc ghi trước việc nó khẳng định"
        )
        progress.note("downloaded")

    monkeypatch.setattr(queue_mod, "download_all", fake_download_all)
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda path: True)

    def _ok_hook(**kw):
        return _UPLOAD_OK

    process_job(db_path, tmp_path / "dl", tmp_path / "ck", job, lifecycle_hook=_ok_hook)

    job = models.get_job(db_path, job_id)
    assert job["trang_thai"] == "done"


# ---------------------------------------------------------------------------
# cookies_path_for_user: per-user path, never another user's, never a
# nonexistent file silently treated as "found".
# ---------------------------------------------------------------------------

def _digest(nguoi_tao: str) -> str:
    return hashlib.sha256(nguoi_tao.encode("utf-8")).hexdigest()


def test_cookies_path_for_user_resolves_existing_file(tmp_path):
    """Ca DƯƠNG cho phép kiểm traversal dưới: một `nguoi_tao` hợp lệ vẫn
    phải resolve ra đúng file trong `cookies_dir` — chứng minh phép kiểm
    traversal có sức phân định (không phải lúc nào cũng trả None)."""
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    (cookies_dir / f"{_digest('namhd')}.json").write_text("[]")
    resolved = queue_mod.cookies_path_for_user(cookies_dir, "namhd")
    assert resolved == str((cookies_dir.resolve() / f"{_digest('namhd')}.json"))
    assert Path(resolved).parent == cookies_dir.resolve()


def test_cookies_path_for_user_returns_none_when_absent(tmp_path):
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    assert queue_mod.cookies_path_for_user(cookies_dir, "khach") is None


def test_cookies_path_for_user_does_not_cross_users(tmp_path):
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    (cookies_dir / f"{_digest('alice')}.json").write_text("[]")
    assert queue_mod.cookies_path_for_user(cookies_dir, "bob") is None


# ---------------------------------------------------------------------------
# Traversal: `nguoi_tao` is attacker-shaped input (removed from the API
# payload in web/app.py, but the function itself must hold the line
# structurally — Phase 05 will feed a real per-user identity through here).
# Bỏ bước hash (dùng nguoi_tao thẳng làm tên file) ⇒ test dưới ĐỎ.
# ---------------------------------------------------------------------------

def test_cookies_path_for_user_blocks_path_traversal(tmp_path):
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    outside_secret = tmp_path / "outside-secret.json"
    outside_secret.write_text('{"leak": true}')

    result = queue_mod.cookies_path_for_user(cookies_dir, "../outside-secret")

    assert result is None


def test_cookies_path_for_user_traversal_never_resolves_outside_cookies_dir(tmp_path):
    """Even when a file matching the RAW traversal payload's target exists,
    the hashed filename never collides with it — the escape has no path to
    a real file, regardless of what that file contains."""
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    (tmp_path / "outside-secret.json").write_text('{"leak": true}')
    (cookies_dir.parent / "x.json").write_text("[]")

    for payload in ("../../../etc/passwd", "../outside-secret", "../x", "..", "/etc/passwd"):
        result = queue_mod.cookies_path_for_user(cookies_dir, payload)
        assert result is None or Path(result).parent == cookies_dir.resolve(), (
            f"nguoi_tao={payload!r} resolved outside cookies_dir: {result!r}"
        )


# ---------------------------------------------------------------------------
# Catalogue metadata read off the hashtag index (15/09). The index response
# carries 31 fields per item; this tool used to read two. Everything below is
# free data that was being discarded, and the grid's market/duration filters
# depend on it.
# ---------------------------------------------------------------------------

def test_clean_int_refuses_bool():
    """`bool` is a subclass of `int` in Python, so an unguarded `isinstance`
    would silently store `True` as a 1-second duration."""
    assert he._clean_int(True) is None
    assert he._clean_int(False) is None
    # Ca dương: số thật vẫn qua, nếu không thì test trên vô nghĩa.
    assert he._clean_int(14) == 14
    assert he._clean_int(14.9) == 14


@pytest.mark.parametrize("value", [None, "", "  ", 12, [], {}])
def test_clean_str_treats_absent_and_blank_alike(value):
    assert he._clean_str(value) is None


def test_clean_int_refuses_negative_and_non_numbers():
    assert he._clean_int(-1) is None
    assert he._clean_int("14") is None
    assert he._clean_int(None) is None


def test_provider_page_carries_catalogue_metadata(monkeypatch):
    """Đột biến: bỏ các trường metadata khỏi `_provider_page` ⇒ ĐỎ."""
    payload = {
        "data": {"videos": [{
            "video_id": "7100",
            "author": {"unique_id": "someone"},
            "title": "  bản 80s  ",
            "region": "MY",
            "duration": 14,
            "play_count": 1200000,
        }], "cursor": 30, "hasMore": True},
    }
    monkeypatch.setattr(he, "_fetch", lambda *a, **kw: json.dumps(payload).encode())

    refs, cursor, has_more, ok = he._provider_page("123", 0)

    assert ok and has_more and cursor == 30
    assert len(refs) == 1
    ref = refs[0]
    assert ref.video_id == "7100"
    assert ref.title == "bản 80s"        # đã trim
    assert ref.author == "someone"
    assert ref.region == "MY"
    assert ref.duration == 14
    assert ref.play_count == 1200000


def test_provider_page_still_works_when_metadata_is_missing(monkeypatch):
    """Ca âm + hồi quy: index là bên thứ ba không chính thức. Ngày nó bỏ một
    trường thì trang vẫn phải dùng được, chỉ mất metadata."""
    payload = {"data": {"videos": [{"video_id": "7101",
                                     "author": {"unique_id": "someone"}}],
                         "cursor": 0, "hasMore": False}}
    monkeypatch.setattr(he, "_fetch", lambda *a, **kw: json.dumps(payload).encode())

    refs, _, _, ok = he._provider_page("123", 0)

    assert ok and len(refs) == 1
    assert refs[0].video_id == "7101"
    assert refs[0].region is None and refs[0].duration is None


def test_provider_page_survives_wrongly_typed_metadata(monkeypatch):
    """A field that changes type must degrade to None, never abort a page that
    is otherwise usable."""
    payload = {"data": {"videos": [{"video_id": "7102",
                                     "author": {"unique_id": "someone"},
                                     "duration": "mười bốn",
                                     "region": 99,
                                     "play_count": True}],
                         "cursor": 0, "hasMore": False}}
    monkeypatch.setattr(he, "_fetch", lambda *a, **kw: json.dumps(payload).encode())

    refs, _, _, ok = he._provider_page("123", 0)

    assert ok and len(refs) == 1
    assert refs[0].duration is None
    assert refs[0].region is None
    assert refs[0].play_count is None


# ---------------------------------------------------------------------------
# Lọc trùng + ghi nguồn, ĐI QUA `_fetch_refs`. Các test model trực tiếp không
# canh được lớp này: schema có thể đúng hoàn toàn mà không ai gọi tới nó, và
# đó chính là trạng thái commit 47e3ee1 để lại — bảng dựng xong, 0 hàng.
# ---------------------------------------------------------------------------

def test_hashtag_listing_skips_videos_the_library_already_has(tmp_path, monkeypatch):
    """ĐỘT BIẾN: bỏ `already_have` khỏi lời gọi enumerate_hashtag ⇒ ĐỎ."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="111", url="u")   # đã có

    pages = [{"data": {"videos": [
        {"video_id": "111", "author": {"unique_id": "a"}},
        {"video_id": "222", "author": {"unique_id": "a"}},
    ], "cursor": 0, "hasMore": False}}]
    monkeypatch.setattr(he, "resolve_challenge_id", lambda tag, proxy=None: "9")
    monkeypatch.setattr(he, "_fetch", lambda *a, **kw: json.dumps(pages[0]).encode())

    refs = queue_mod._fetch_refs("https://www.tiktok.com/tag/anos80", max_videos=10,
                                  cookies_path=None, db_path=db, job_id=2)

    assert [r.video_id for r in refs] == ["222"], "video đã có phải bị loại"


def test_a_skipped_duplicate_still_records_its_source(tmp_path, monkeypatch):
    """Đây là lý do bảng sightings tồn tại: video bị bỏ qua KHÔNG bao giờ đi
    vào đường tải, nên nếu không ghi ở đây thì hashtag thứ hai của nó biến
    mất vĩnh viễn — và thẻ lọc theo nguồn thiếu đúng dữ liệu nó cần."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="111", url="u")

    payload = {"data": {"videos": [{"video_id": "111", "author": {"unique_id": "a"}}],
                         "cursor": 0, "hasMore": False}}
    monkeypatch.setattr(he, "resolve_challenge_id", lambda tag, proxy=None: "9")
    monkeypatch.setattr(he, "_fetch", lambda *a, **kw: json.dumps(payload).encode())

    queue_mod._fetch_refs("https://www.tiktok.com/tag/80ssaudi", max_videos=10,
                           cookies_path=None, db_path=db, job_id=2)

    assert models.sources_for_videos(db, ["111"]) == {"111": ["#80ssaudi"]}


def test_music_page_results_are_deduped_too(tmp_path, monkeypatch):
    """Không chỉ hashtag: chạy lại một music page hôm nay sẽ upload BẢN THỨ
    HAI lên Drive, trong khi `ON CONFLICT DO NOTHING` giữ hàng cũ — nên file
    thứ hai tồn tại mà không gì trỏ tới."""
    db = tmp_path / "jobs.db"
    models.init_db(db)
    models.record_video(db, job_id=1, video_id="333", url="u")
    monkeypatch.setattr(queue_mod, "scrape_music_page",
                         lambda *a, **kw: [VideoRef(video_id="333", url="u1"),
                                            VideoRef(video_id="444", url="u2")])

    refs = queue_mod._fetch_refs("https://www.tiktok.com/music/x-1", max_videos=10,
                                  cookies_path=None, db_path=db, job_id=2)

    assert [r.video_id for r in refs] == ["444"]
    assert models.sources_for_videos(db, ["333"]) == {
        "333": ["https://www.tiktok.com/music/x-1"]}


def test_listing_without_a_db_keeps_every_ref(tmp_path, monkeypatch):
    """Ca âm: CLI và GUI gọi cùng đường này mà không có DB nào. Thiếu db_path
    thì không được lọc mất gì — nếu không, ba test trên có thể xanh chỉ vì
    hàm luôn trả rỗng."""
    monkeypatch.setattr(queue_mod, "scrape_music_page",
                         lambda *a, **kw: [VideoRef(video_id="555", url="u")])

    refs = queue_mod._fetch_refs("https://www.tiktok.com/music/x-1", max_videos=10,
                                  cookies_path=None)

    assert [r.video_id for r in refs] == ["555"]


def test_source_label_shape_is_fixed_before_the_first_row(tmp_path):
    """Đổi hình dạng nhãn sau khi đã ghi hàng là migrate dữ liệu, không phải
    sửa code — nên khoá nó bằng test ngay từ bây giờ."""
    assert queue_mod.source_label("https://www.tiktok.com/tag/anos80") == "#anos80"
    assert queue_mod.source_label("https://www.tiktok.com/music/x-1") == \
        "https://www.tiktok.com/music/x-1"


def test_owned_videos_do_not_stop_the_hashtag_walk_early(tmp_path, monkeypatch):
    """ĐỘT BIẾN: cho "đã có trong thư viện" nuôi bộ đếm stall ⇒ ĐỎ.

    Một hashtag mà team đã tải hết trang đầu vẫn phải duyệt tiếp để tìm video
    mới. Gộp hai khái niệm "mới với lượt này" và "mới với thư viện" làm nó
    dừng sau 2 trang với 0 kết quả, trong khi index vẫn trả dữ liệu tốt.
    """
    db = tmp_path / "jobs.db"
    models.init_db(db)
    for vid in ("1", "2", "3", "4"):
        models.record_video(db, job_id=1, video_id=vid, url="u")

    pages = [
        {"data": {"videos": [{"video_id": "1", "author": {"unique_id": "a"}},
                              {"video_id": "2", "author": {"unique_id": "a"}}],
                   "cursor": 1, "hasMore": True}},
        {"data": {"videos": [{"video_id": "3", "author": {"unique_id": "a"}},
                              {"video_id": "4", "author": {"unique_id": "a"}}],
                   "cursor": 2, "hasMore": True}},
        {"data": {"videos": [{"video_id": "99", "author": {"unique_id": "a"}}],
                   "cursor": 3, "hasMore": False}},
    ]
    calls = {"n": 0}

    def _fake_fetch(*a, **kw):
        i = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return json.dumps(pages[i]).encode()

    monkeypatch.setattr(he, "resolve_challenge_id", lambda tag, proxy=None: "9")
    monkeypatch.setattr(he, "_fetch", _fake_fetch)
    monkeypatch.setattr(he.time, "sleep", lambda *_: None)

    refs = queue_mod._fetch_refs("https://www.tiktok.com/tag/t", max_videos=5,
                                  cookies_path=None, db_path=db, job_id=2)

    assert [r.video_id for r in refs] == ["99"], "phải đi tới trang 3 mới thấy cái mới"


# ---------------------------------------------------------------------------
# Mối nối, không phải cái được nối. Hai vòng liên tiếp tôi đột biến BÊN TRONG
# lớp vừa viết và bỏ sót chỗ nó được gọi — vòng trước là schema không ai gọi,
# vòng này là `_fetch_refs` nhận đúng kwargs mà lời gọi trong `process_job`
# không truyền. Cả hai lần suite vẫn xanh. Hai test dưới canh đúng cái seam đó.
# ---------------------------------------------------------------------------

def _drive_one_job(tmp_path, monkeypatch, url, refs, db_path):
    """Chạy trọn `process_job` với downloader giả: không mạng, không ffmpeg."""
    job_id = models.create_job(db_path, url, 10, "namhd@astronex.ai")
    job = models.get_job(db_path, job_id)
    monkeypatch.setattr(queue_mod, "scrape_music_page", lambda *a, **kw: list(refs))
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **kw: True)

    def _fake_download(refs_, output_dir, cookies_path=None, progress=None, **kw):
        output_dir.mkdir(parents=True, exist_ok=True)
        for r in refs_:
            (output_dir / r.filename).write_bytes(b"x")
            if progress is not None:
                progress.note("downloaded")
        return len(refs_), 0, []

    monkeypatch.setattr(queue_mod, "download_all", _fake_download)
    process_job(db_path, tmp_path / "dl", tmp_path / "ck", job,
                lifecycle_hook=lambda **kw: _UPLOAD_OK)
    return job_id


def test_process_job_passes_the_db_through_so_dedupe_actually_runs(tmp_path, monkeypatch):
    """ĐỘT BIẾN: xoá `db_path=`/`job_id=` khỏi lời gọi `_fetch_refs` trong
    `process_job` ⇒ ĐỎ.

    Không có test này, đột biến đó để lại một suite XANH và một tính năng đã
    TẮT: `_already_have` trả `set()` rỗng nên mọi video trùng lại được tải.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    models.record_video(db_path, job_id=99, video_id="111", url="u")  # đã có

    job_id = _drive_one_job(
        tmp_path, monkeypatch, "https://www.tiktok.com/music/x-1",
        [VideoRef(video_id="111", url="u1"), VideoRef(video_id="222", url="u2")],
        db_path)

    # `tong` được ghi bằng len(refs) SAU khi lọc, nên nó là tín hiệu phân định:
    # dedupe chạy ⇒ 1, dedupe tắt ⇒ 2. (Hàng `videos` không dùng được ở đây —
    # test thay lifecycle_hook bằng stub nên không ai ghi hàng nào.)
    assert models.get_job(db_path, job_id)["tong"] == 1, "chỉ ref MỚI được đưa vào tải"
    # Và video bị bỏ qua phải để lại dấu nguồn của lượt này.
    assert models.sources_for_videos(db_path, ["111"]) == {
        "111": ["https://www.tiktok.com/music/x-1"]}


def test_process_job_names_the_source_so_downloaded_sightings_exist(tmp_path, monkeypatch):
    """ĐỘT BIẾN: bỏ `nguon=` khỏi `_JobProgress(...)` ⇒ ĐỎ.

    `_note_sighting` return sớm khi `nguon` rỗng, nên đột biến đó cho ra 0 hàng
    `da_tai=1` — thẻ lọc theo nguồn trống trơn — mà không test nào kêu.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)

    _drive_one_job(tmp_path, monkeypatch, "https://www.tiktok.com/music/x-1",
                   [VideoRef(video_id="333", url="u")], db_path)

    assert models.sources_for_videos(db_path, ["333"]) == {
        "333": ["https://www.tiktok.com/music/x-1"]}


def test_stop_reason_reaches_the_job_row(tmp_path, monkeypatch):
    """ĐỘT BIẾN: bỏ `on_stop=_note_stop` ⇒ ĐỎ.

    Sau khi có lọc trùng, một hashtag team đã tải nhiều lần sẽ chạm trần trang
    và trả về 0 video mới. Từ ngoài nhìn, ca đó trông Y HỆT "hashtag rỗng" và
    Y HỆT "index chết" — ba ca cần ba phản ứng khác nhau. Nếu lý do chỉ nằm
    trong log thì UI không phân biệt được.
    """
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "https://www.tiktok.com/tag/t", 200, "a")

    same = {"data": {"videos": [{"video_id": "1", "author": {"unique_id": "a"}}],
                      "cursor": 1, "hasMore": True}}
    monkeypatch.setattr(he, "resolve_challenge_id", lambda tag, proxy=None: "9")
    monkeypatch.setattr(he, "_fetch", lambda *a, **kw: json.dumps(same).encode())
    monkeypatch.setattr(he.time, "sleep", lambda *_: None)

    queue_mod._fetch_refs("https://www.tiktok.com/tag/t", max_videos=200,
                           cookies_path=None, db_path=db_path, job_id=job_id)

    assert models.get_job(db_path, job_id)["ly_do_dung"] == he.STOP_STALLED


def test_a_job_that_got_what_it_asked_for_has_no_stop_reason(tmp_path, monkeypatch):
    """Ca âm: không được dán lý do dừng lên một lượt chạy trọn vẹn."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job_id = models.create_job(db_path, "https://www.tiktok.com/tag/t", 1, "a")

    page = {"data": {"videos": [{"video_id": "1", "author": {"unique_id": "a"}}],
                      "cursor": 0, "hasMore": False}}
    monkeypatch.setattr(he, "resolve_challenge_id", lambda tag, proxy=None: "9")
    monkeypatch.setattr(he, "_fetch", lambda *a, **kw: json.dumps(page).encode())

    queue_mod._fetch_refs("https://www.tiktok.com/tag/t", max_videos=1,
                           cookies_path=None, db_path=db_path, job_id=job_id)

    assert models.get_job(db_path, job_id)["ly_do_dung"] is None


def test_repeated_sightings_of_the_same_pair_collapse(tmp_path):
    """Một lượt gặp lại cùng video dưới cùng nguồn nhiều lần là chuyện thường;
    bảng phải phình theo số SỰ VIỆC, không theo số lần chạy."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    for _ in range(3):
        models.record_sighting(db_path, video_id="1", job_id=7,
                                nguon="#t", da_tai=False)

    assert models.sources_for_videos(db_path, ["1"]) == {"1": ["#t"]}


# ---------------------------------------------------------------------------
# Phase 05 — cookie của người nào đi theo job người đó.
#
# Tiêu chí CŨ ("grep log/DB không thấy cookie của A trong job B") là XANH TRÁ
# HÌNH: theo thiết kế cookie KHÔNG BAO GIỜ vào DB hay log, nên grep luôn rỗng
# dù dây nối có lẫn hay không. Phép đo có sức phân định là bắt giá trị
# `cookies_path` THỰC SỰ tới `download_all`.
# ---------------------------------------------------------------------------

def _jar_for(cookies_dir: Path, nguoi_tao: str) -> Path:
    """Một jar TRÔNG NHƯ THẬT: có cookie đăng nhập và chưa hết hạn.

    Jar rỗng `[]` không dùng được ở đây nữa — tiền-kiểm trong `process_job`
    loại nó trước khi job chạy, đúng như phase-05 yêu cầu. Giá trị dưới đây là
    giả, chỉ cần đúng HÌNH DẠNG."""
    cookies_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(nguoi_tao.encode("utf-8")).hexdigest()
    jar = cookies_dir / f"{digest}.json"
    jar.write_text(json.dumps([
        {"name": "sessionid", "value": "gia-lap-khong-phai-cookie-that",
         "domain": ".tiktok.com", "path": "/", "expires": 0},
    ]), encoding="utf-8")
    return jar


def _drive_job_as(tmp_path, monkeypatch, db_path, nguoi_tao, cookies_dir):
    """Chạy trọn một job của `nguoi_tao`, trả về cookies_path mà downloader nhận."""
    bat_duoc = {}
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 10, nguoi_tao)
    job = models.get_job(db_path, job_id)
    monkeypatch.setattr(queue_mod, "scrape_music_page", lambda *a, **kw: [VideoRef(video_id="900", url="u")])
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **kw: True)

    def _fake_download(refs_, output_dir, cookies_path=None, progress=None, **kw):
        bat_duoc["cookies_path"] = cookies_path
        output_dir.mkdir(parents=True, exist_ok=True)
        for r in refs_:
            (output_dir / r.filename).write_bytes(b"x")
            if progress is not None:
                progress.note("downloaded")
        return len(refs_), 0, []

    monkeypatch.setattr(queue_mod, "download_all", _fake_download)
    process_job(db_path, tmp_path / "dl", cookies_dir, job,
                lifecycle_hook=lambda **kw: _UPLOAD_OK)
    return bat_duoc.get("cookies_path", "__KHONG_TRUYEN__")


def test_job_of_b_downloads_with_bs_cookie_not_as(tmp_path, monkeypatch):
    """ĐỘT BIẾN: bỏ `job["nguoi_tao"]` khỏi lời gọi `cookies_path_for_user`
    trong `process_job` (ví dụ ghim cứng "khach") ⇒ ĐỎ."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    cookies_dir = tmp_path / "ck"
    jar_a = _jar_for(cookies_dir, "a@astronex.ai")
    jar_b = _jar_for(cookies_dir, "b@astronex.ai")

    duoc_nhan = _drive_job_as(tmp_path, monkeypatch, db_path, "b@astronex.ai", cookies_dir)

    assert duoc_nhan == str(jar_b), "job của B phải chạy bằng jar của B"
    assert duoc_nhan != str(jar_a), "không được dùng jar của người khác"


def test_a_user_with_no_jar_downloads_anonymous_never_someone_elses(tmp_path, monkeypatch):
    """Ca âm: không có jar thì phải là None (ẩn danh), KHÔNG được rơi sang jar
    của người đang có. Không có ca này thì test trên vẫn xanh trong khi code
    'lấy đại jar đầu tiên tìm thấy'."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    cookies_dir = tmp_path / "ck"
    _jar_for(cookies_dir, "a@astronex.ai")

    duoc_nhan = _drive_job_as(tmp_path, monkeypatch, db_path, "chua-co@astronex.ai", cookies_dir)

    assert duoc_nhan is None


# ---------------------------------------------------------------------------
# Phase 05 — cookie hỏng/hết hạn phải làm job FAIL, KHÔNG được âm thầm chạy
# ẩn danh. `download_all` nuốt lỗi cookie thành một dòng log rồi chạy tiếp
# không cookie; với thư viện dùng chung, job sẽ báo "xong" mà ra ít video hơn
# hẳn và không ai biết vì sao.
#
# ĐỘT BIẾN: xoá khối tiền-kiểm trong `process_job` ⇒ ba test đầu ĐỎ.
# ---------------------------------------------------------------------------

def _chay_job_voi_jar(tmp_path, monkeypatch, db_path, noi_dung_jar: str | None):
    """Dựng jar (hoặc không), chạy job, trả về (job sau khi chạy, có gọi download_all không)."""
    cookies_dir = tmp_path / "ck"
    cookies_dir.mkdir(parents=True, exist_ok=True)
    nguoi_tao = "ai-do@astronex.ai"
    if noi_dung_jar is not None:
        digest = hashlib.sha256(nguoi_tao.encode("utf-8")).hexdigest()
        (cookies_dir / f"{digest}.json").write_text(noi_dung_jar, encoding="utf-8")

    da_goi = {"download_all": False}
    job_id = models.create_job(db_path, "https://www.tiktok.com/music/x-1", 10, nguoi_tao)
    job = models.get_job(db_path, job_id)
    monkeypatch.setattr(queue_mod, "scrape_music_page", lambda *a, **kw: [VideoRef(video_id="900", url="u")])
    monkeypatch.setattr(queue_mod, "verify_video_stream", lambda *a, **kw: True)

    def _fake_download(refs_, output_dir, cookies_path=None, progress=None, **kw):
        da_goi["download_all"] = True
        output_dir.mkdir(parents=True, exist_ok=True)
        for r in refs_:
            (output_dir / r.filename).write_bytes(b"x")
            if progress is not None:
                progress.note("downloaded")
        return len(refs_), 0, []

    monkeypatch.setattr(queue_mod, "download_all", _fake_download)
    process_job(db_path, tmp_path / "dl", cookies_dir, job,
                lifecycle_hook=lambda **kw: _UPLOAD_OK)
    return models.get_job(db_path, job_id), da_goi["download_all"]


def _het_han():
    return json.dumps([{"name": "sessionid", "value": "gia", "domain": ".tiktok.com",
                        "path": "/", "expires": 1000000000}])  # 2001


def test_a_corrupt_cookie_file_fails_the_job_instead_of_going_anonymous(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job, da_tai = _chay_job_voi_jar(tmp_path, monkeypatch, db_path, "khong-phai-json-gi-ca")

    assert job["trang_thai"] == "failed"
    assert job["ly_do_dung"] and "cookie" in job["ly_do_dung"]
    assert da_tai is False, "không được tải một video nào bằng phiên ẩn danh"


def test_an_expired_login_cookie_fails_the_job(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job, da_tai = _chay_job_voi_jar(tmp_path, monkeypatch, db_path, _het_han())

    assert job["trang_thai"] == "failed"
    assert "hết hạn" in job["ly_do_dung"]
    assert da_tai is False


def test_a_jar_without_any_login_cookie_fails_the_job(tmp_path, monkeypatch):
    """Jar có cookie nhưng KHÔNG có cookie đăng nhập = phiên khách. Job sẽ
    chạy tới trần khách (~28 video) rồi báo "xong" — ca hỏng âm thầm nhất."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    jar = json.dumps([{"name": "tt_csrf_token", "value": "gia", "domain": ".tiktok.com",
                       "path": "/", "expires": 0}])
    job, da_tai = _chay_job_voi_jar(tmp_path, monkeypatch, db_path, jar)

    assert job["trang_thai"] == "failed"
    assert "chưa đăng nhập" in job["ly_do_dung"]
    assert da_tai is False


def test_no_jar_at_all_is_not_an_error(tmp_path, monkeypatch):
    """CA ÂM bắt buộc: không có jar là chạy ẩn danh CÓ CHỦ ĐÍCH, không phải
    lỗi. Thiếu ca này thì một tiền-kiểm "chặn tất" vẫn xanh cả ba test trên."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    job, da_tai = _chay_job_voi_jar(tmp_path, monkeypatch, db_path, None)

    assert job["trang_thai"] == "done"
    assert da_tai is True


def test_the_failure_reason_never_quotes_the_cookie_file(tmp_path, monkeypatch):
    """`_load_cookies` nhúng `raw[:80]` vào thông điệp lỗi (scraper.py:82,91).
    Với bản xuất "Header String", 80 ký tự đầu CHÍNH LÀ token. Lý do hỏng đi
    vào `ly_do_dung` rồi lên UI, nên nó không được mang một ký tự nào của tệp."""
    db_path = tmp_path / "jobs.db"
    models.init_db(db_path)
    bi_mat = "sessionid=TOKEN_RAT_BI_MAT_9x8y7z; sid_tt=CUNG_BI_MAT_abc"
    job, _ = _chay_job_voi_jar(tmp_path, monkeypatch, db_path, bi_mat)

    assert job["trang_thai"] == "failed"
    assert "TOKEN_RAT_BI_MAT" not in job["ly_do_dung"]
    assert "CUNG_BI_MAT" not in job["ly_do_dung"]
