"""SQLite-backed job state — the only place job progress lives.

State is never held in RAM across requests: every call opens a short-lived
connection, does one transaction, closes. That is deliberate — the worker
process can die (KeepAlive restarts it with SIGKILL) and the web process can
be a different process entirely; only the file on disk is common ground.

Schema: jobs(id, url, trang_thai, tong, xong, loi, tao_luc, xong_luc,
nguoi_tao) per the phase-02 spec, plus `bat_dau_luc` (started-at) — needed to
*prove* two jobs ran sequentially rather than assert it (see
`test_web_queue.py::test_two_jobs_submitted_together_run_sequentially`) — and
`drive_folder_link` (Bước 6 of the 14/09 fix chain): the per-job Shared Drive
folder link, so the user gets ONE link per job instead of nothing (Drive
uploads happened but the link was logged and thrown away).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

VALID_END_STATES = ("done", "failed")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    trang_thai TEXT NOT NULL DEFAULT 'pending',
    tong INTEGER NOT NULL DEFAULT 0,
    xong INTEGER NOT NULL DEFAULT 0,
    loi INTEGER NOT NULL DEFAULT 0,
    tao_luc TEXT NOT NULL,
    bat_dau_luc TEXT,
    xong_luc TEXT,
    nguoi_tao TEXT NOT NULL DEFAULT 'khach',
    drive_folder_link TEXT
)
"""


_VIDEOS_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    job_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    author TEXT,
    region TEXT,
    duration INTEGER,
    play_count INTEGER,
    tao_luc TEXT NOT NULL
)
"""

# One row per video that reached Drive — the index the library grid reads.
# `video_id` is the PRIMARY KEY, not an autoincrement id: the same TikTok video
# legitimately shows up under two hashtags, and it is one video on Drive, so it
# must be one row. That also makes re-running a job idempotent here.
#
# Deliberately NO `thumb_path` column. The thumbnail lives at a path derived
# from `video_id`, so its presence on disk IS the fact; a column would be a
# second copy of that fact, written in a separate step, and a crash between
# the two would leave an orphan file no DB-driven sweep could ever find.


def _now() -> str:
    """ISO-8601 UTC with microseconds — sorts correctly as plain TEXT, and is
    fine-grained enough to order two jobs claimed a few ms apart."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@contextmanager
def _connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        # WAL: worker thread writes progress while a request thread reads the
        # same row without either side blocking on a file lock.
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(_SCHEMA)
        conn.execute(_VIDEOS_SCHEMA)
        # `CREATE TABLE IF NOT EXISTS` above does nothing for a `jobs.db`
        # that already existed before `drive_folder_link` was added — this
        # ad hoc migration is the only thing that backfills the column onto
        # a pre-existing table. sqlite3.OperationalError (duplicate column)
        # means it is already there; that is the expected steady state.
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN drive_folder_link TEXT")
        except sqlite3.OperationalError:
            pass


def create_job(db_path: Path, url: str, so_luong: int, nguoi_tao: str) -> int:
    """Insert a pending job. `so_luong` (user's requested count) seeds `tong`;
    `process_job` overwrites `tong` with the *actual* ref count once the
    scrape/enumerate step returns, since that is the real progress-bar
    denominator, not the ceiling the user asked for."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO jobs (url, trang_thai, tong, xong, loi, tao_luc, nguoi_tao) "
            "VALUES (?, 'pending', ?, 0, 0, ?, ?)",
            (url, so_luong, _now(), nguoi_tao),
        )
        job_id = cur.lastrowid
    assert job_id is not None
    return job_id


def get_job(db_path: Path, job_id: int) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row is not None else None


def list_jobs(db_path: Path) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY tao_luc DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def claim_next_pending_job(db_path: Path) -> dict | None:
    """Atomically take the oldest pending job and flip it to 'running'.

    `BEGIN IMMEDIATE` takes the write lock before the SELECT, so a second
    caller (there is only ever one worker thread today, but this stays
    correct if that ever changes) cannot read the same pending row and claim
    it twice.
    """
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM jobs WHERE trang_thai = 'pending' "
            "ORDER BY tao_luc ASC, id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return None
        job = dict(row)
        started = _now()
        conn.execute(
            "UPDATE jobs SET trang_thai = 'running', bat_dau_luc = ? WHERE id = ?",
            (started, job["id"]),
        )
        job["trang_thai"] = "running"
        job["bat_dau_luc"] = started
        return job


def set_job_total(db_path: Path, job_id: int, tong: int) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE jobs SET tong = ? WHERE id = ?", (tong, job_id))


def increment_job_counts(db_path: Path, job_id: int, xong_delta: int = 0,
                          loi_delta: int = 0) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET xong = xong + ?, loi = loi + ? WHERE id = ?",
            (xong_delta, loi_delta, job_id),
        )


def set_job_drive_folder_link(db_path: Path, job_id: int, link: str) -> None:
    """Persist the per-job Shared Drive folder link (Bước 6). Called once,
    the first time a job's folder is created — see
    `web/lifecycle.py::_ensure_job_folder`."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET drive_folder_link = ? WHERE id = ?",
            (link, job_id),
        )


def finish_job(db_path: Path, job_id: int, trang_thai: str) -> None:
    if trang_thai not in VALID_END_STATES:
        raise ValueError(f"trang_thai kết thúc không hợp lệ: {trang_thai!r}")
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET trang_thai = ?, xong_luc = ? WHERE id = ?",
            (trang_thai, _now(), job_id),
        )


def record_video(db_path: Path, job_id: int, video_id: str, url: str,
                  title: str | None = None, author: str | None = None,
                  region: str | None = None, duration: int | None = None,
                  play_count: int | None = None) -> None:
    """Index one video that is now on Drive.

    Called only after the upload reported success, so a row here means "this
    video is in the Shared Drive" and nothing weaker. `INSERT OR REPLACE`
    because the same video can be reached through two different hashtags:
    that is one file on Drive, so it is one row, and the second sighting
    refreshes the metadata rather than raising.
    """
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO videos "
            "(video_id, job_id, url, title, author, region, duration, play_count, tao_luc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (video_id, job_id, url, title, author, region, duration, play_count, _now()),
        )


def list_videos(db_path: Path, limit: int = 500, offset: int = 0) -> list[dict]:
    """Newest first. Paged because the grid renders every row it is handed."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM videos ORDER BY tao_luc DESC, video_id DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def count_videos(db_path: Path) -> int:
    with _connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0])


def mark_running_as_interrupted(db_path: Path) -> int:
    """Boot-time sweep — call once, before the worker starts pulling jobs.

    `KeepAlive` restarts this process with SIGKILL, so any row still
    'running' from before the crash never got a `finally` to clean up after
    itself. Leaving it 'running' forever hides a dead job; marking it 'done'
    would lie about a job that never finished. 'interrupted' says exactly
    what happened and nothing more.

    Returns the number of rows changed (0 on a clean boot is normal).
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE jobs SET trang_thai = 'interrupted', xong_luc = ? "
            "WHERE trang_thai = 'running'",
            (_now(),),
        )
        return cur.rowcount
