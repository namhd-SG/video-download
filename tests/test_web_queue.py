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
                         lambda tag, max_videos, proxy=None: [])
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
