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
    drive_folder_link TEXT,
    ly_do_dung TEXT,
    so_trang INTEGER NOT NULL DEFAULT 0
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
    music_id TEXT,
    drive_file_id TEXT,
    tao_luc TEXT NOT NULL
)
"""

# Every time a video is SEEN under some source, including the times it is
# skipped because we already have it. Append-only, and the reason it exists:
#
# `videos` answers "what do we have"; it holds first-seen `job_id` and
# `tao_luc`, which is what the "who downloaded" and "when" filters must mean.
# But one video legitimately appears under several hashtags, and the source
# filter has to list all of them. Putting that on `videos` cost us one or the
# other — the first version used INSERT OR REPLACE, which quietly rewrote
# `job_id` and `tao_luc` to the LAST re-sighting, breaking both filters.
#
# Sightings also have to be written when a video is skipped as a duplicate:
# a skipped video never reaches the download path at all, so that is the only
# moment its second hashtag is ever observable.
_SIGHTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS video_sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    job_id INTEGER NOT NULL,
    nguon TEXT NOT NULL,
    da_tai INTEGER NOT NULL DEFAULT 0,
    thay_luc TEXT NOT NULL
)
"""

_SIGHTINGS_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_sightings_video ON video_sightings(video_id)",
    "CREATE INDEX IF NOT EXISTS idx_sightings_nguon ON video_sightings(nguon)",
    # Một lượt chạy gặp lại cùng video dưới cùng nguồn nhiều lần là chuyện
    # thường; không có ràng buộc này thì mỗi lượt lại đắp thêm một hàng giống
    # hệt, và bảng phình theo số lần chạy chứ không theo số sự việc.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sightings_unique "
    "ON video_sightings(video_id, job_id, nguon)",
)

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


def _add_column_if_missing(conn, table: str, column: str, decl: str) -> None:
    """ALTER TABLE ADD COLUMN, tolerating only the already-there case.

    A bare `except sqlite3.OperationalError: pass` swallows "database is
    locked" and "disk I/O error" alongside "duplicate column". That is the
    dangerous shape: a migration that failed for a real reason passes
    silently, then every later INSERT dies on `no such column` — and those
    INSERTs are themselves inside a swallow (`_record_video_quietly`), so
    the library would simply stop recording anything, without a sound.
    """
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


def init_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(_SCHEMA)
        conn.execute(_VIDEOS_SCHEMA)
        conn.execute(_SIGHTINGS_SCHEMA)
        for statement in _SIGHTINGS_INDEX:
            conn.execute(statement)
        # `videos` shipped before `music_id`/`drive_file_id` existed, so an
        # already-created table needs them added. Same ad hoc migration the
        # jobs table uses above; duplicate-column means it is already done.
        for column, decl in (("music_id", "TEXT"), ("drive_file_id", "TEXT")):
            _add_column_if_missing(conn, "videos", column, decl)
        # `CREATE TABLE IF NOT EXISTS` above does nothing for a `jobs.db`
        # that already existed before `drive_folder_link` was added — this
        # ad hoc migration is the only thing that backfills the column onto
        # a pre-existing table. sqlite3.OperationalError (duplicate column)
        # means it is already there; that is the expected steady state.
        _add_column_if_missing(conn, "jobs", "drive_folder_link", "TEXT")
        _add_column_if_missing(conn, "jobs", "ly_do_dung", "TEXT")
        _add_column_if_missing(conn, "jobs", "so_trang", "INTEGER NOT NULL DEFAULT 0")


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


def set_job_pages(db_path: Path, job_id: int, so_trang: int) -> None:
    """Số trang index lượt này đã đọc. Tiêu vào trần liệt kê KỂ CẢ khi không ra
    video nào — đó chính là ca cần bó: quét một hashtag đã cạn vẫn tốn ~40 lượt
    gọi index mà `tong` bằng 0."""
    with _connect(db_path) as conn:
        conn.execute("UPDATE jobs SET so_trang = ? WHERE id = ?", (so_trang, job_id))


def sum_pages_since_by_creator(db_path: Path, since: str) -> dict[str, int]:
    """Số trang index mỗi người đã đọc kể từ `since`."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT nguoi_tao, COALESCE(SUM(so_trang), 0) AS n FROM jobs "
            "WHERE tao_luc >= ? GROUP BY nguoi_tao",
            (since,),
        ).fetchall()
    return {row["nguoi_tao"]: row["n"] for row in rows}


def count_jobs_since_by_creator(db_path: Path, since: str) -> dict[str, int]:
    """How many jobs each creator has started since `since`, for the daily cap.

    Grouped rather than totalled because the cap counts per *cookie*, and one
    cookie jar can belong to several creators once Phase 05 wires real
    identities. The caller maps creator -> jar and sums the matching rows.

    `since` is ISO-8601 UTC in the shape `_now()` writes, so `>=` compares
    correctly as plain TEXT — the same property that lets `tao_luc` sort.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            # `already_owned` KHÔNG tính: người dùng không làm gì sai khi quét
            # một hashtag team đã tải hết (user chốt 16/09). Lưu lượng của lượt
            # đó vẫn bị bó — bởi trần LIỆT KÊ, không phải trần này.
            # Chỉ ca NÀY được miễn; `index_failed` vẫn tính, nếu không thì ép
            # lỗi là một đường lách trần.
            "SELECT nguoi_tao, COUNT(*) AS n FROM jobs "
            "WHERE tao_luc >= ? AND COALESCE(ly_do_dung, '') != 'already_owned' "
            "GROUP BY nguoi_tao",
            (since,),
        ).fetchall()
    return {row["nguoi_tao"]: row["n"] for row in rows}


def sum_videos_since_by_creator(db_path: Path, since: str) -> dict[str, int]:
    """How many videos each creator's jobs account for since `since`.

    Sums `tong`, which is the requested count until `process_job` replaces it
    with the real ref count — i.e. the best number known for each job at the
    moment it is asked for. That is what the video cap rations: calls actually
    made to TikTok, not jobs started.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT nguoi_tao, COALESCE(SUM(tong), 0) AS n FROM jobs "
            "WHERE tao_luc >= ? GROUP BY nguoi_tao",
            (since,),
        ).fetchall()
    return {row["nguoi_tao"]: row["n"] for row in rows}


def get_job(db_path: Path, job_id: int) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row is not None else None


def list_jobs(db_path: Path, chi_cua: str | None) -> list[dict]:
    """Hàng đợi. `chi_cua=None` là THẤY HẾT — chỉ dành cho admin.

    Tham số BẮT BUỘC, không có mặc định: hàm này quyết định ai thấy gì, và một
    mặc định im lặng ở đây nghĩa là "thấy hết" — tức phơi URL, email và trạng
    thái cookie của đồng nghiệp cho bất kỳ ai gọi thiếu tham số. Quên truyền
    bây giờ là TypeError, không phải một lỗ.
    """
    with _connect(db_path) as conn:
        if chi_cua is None:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY tao_luc DESC, id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE nguoi_tao = ? ORDER BY tao_luc DESC, id DESC",
                (chi_cua,),
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
                  play_count: int | None = None, music_id: str | None = None,
                  drive_file_id: str | None = None,
                  tao_luc: str | None = None) -> None:
    """Index one video that is now on Drive. First sighting wins.

    Called only after the upload reported success, so a row here means "this
    video is in the Shared Drive" and nothing weaker.

    `ON CONFLICT DO NOTHING`, NOT `INSERT OR REPLACE`. REPLACE is a DELETE
    plus an INSERT, so meeting the same video under a second hashtag rewrote
    `job_id` and `tao_luc` — and those two columns are exactly what the
    "who downloaded it" and "when" filters read. The filters would have shown
    the most recent RE-download instead of the original, which is a wrong
    answer that looks like a right one. Later sightings go to
    `video_sightings`, which is what that table is for.
    """
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO videos "
            "(video_id, job_id, url, title, author, region, duration, play_count, "
            " music_id, drive_file_id, tao_luc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(video_id) DO NOTHING",
            (video_id, job_id, url, title, author, region, duration, play_count,
             music_id, drive_file_id, tao_luc or _now()),
        )


def record_sighting(db_path: Path, video_id: str, job_id: int, nguon: str,
                     da_tai: bool, thay_luc: str | None = None) -> None:
    """Note that this job saw this video under `nguon`, downloaded or not.

    `da_tai=False` is the duplicate case, and it is the whole point: a video
    skipped as already-owned never reaches the download path, so this is the
    only place its second hashtag is ever recorded.
    """
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO video_sightings "
            "(video_id, job_id, nguon, da_tai, thay_luc) VALUES (?, ?, ?, ?, ?)",
            (video_id, job_id, nguon, 1 if da_tai else 0, thay_luc or _now()),
        )


def sources_for_videos(db_path: Path, video_ids: list[str]) -> dict[str, list[str]]:
    """`{video_id: [nguồn, …]}` — every source each video has been seen under."""
    if not video_ids:
        return {}
    marks = ",".join("?" * len(video_ids))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT DISTINCT video_id, nguon FROM video_sightings "
            f"WHERE video_id IN ({marks}) ORDER BY nguon",
            video_ids,
        ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["video_id"], []).append(r["nguon"])
    return out


def known_video_ids(db_path: Path, video_ids: list[str]) -> set[str]:
    """Which of these do we already have? Drives the duplicate skip.

    Takes the candidate list rather than loading the whole table: the library
    is meant to grow without bound, and a per-job SELECT of every row would
    quietly become the slowest part of enumerating.
    """
    if not video_ids:
        return set()
    marks = ",".join("?" * len(video_ids))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT video_id FROM videos WHERE video_id IN ({marks})", video_ids
        ).fetchall()
    return {r["video_id"] for r in rows}


def list_videos(db_path: Path, limit: int = 500, offset: int = 0) -> list[dict]:
    """Newest first. Paged because the grid renders every row it is handed."""
    with _connect(db_path) as conn:
        # Kèm `nguoi_tao` của job đã tải video này. Thư viện là của CẢ TEAM
        # (chốt #2) và có bộ lọc "Người tải" (chốt #7), nên quy kết ai-tải-gì
        # thuộc về thư viện. Trước đây UI dựng nó từ `/jobs`; từ 16/09 `/jobs`
        # chỉ trả lượt của chính mình, nên nếu không mang theo đây thì bộ lọc
        # #7 sẽ hiện "không rõ" cho mọi video của người khác — gãy một tính
        # năng đã chốt mà không ai thấy.
        # LEFT JOIN: hàng job có thể vắng, video vẫn phải hiện.
        rows = conn.execute(
            "SELECT v.*, j.nguoi_tao FROM videos v "
            "LEFT JOIN jobs j ON j.id = v.job_id "
            "ORDER BY v.tao_luc DESC, v.video_id DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def count_videos(db_path: Path) -> int:
    with _connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0])


def set_job_stop_reason(db_path: Path, job_id: int, ly_do: str) -> None:
    """Vì sao lượt liệt kê dừng sớm. Rỗng/None = lấy đủ số đã xin.

    Sống trên hàng job chứ không chỉ trong log: sau khi có lọc trùng, một
    hashtag đã tải nhiều lần sẽ chạm trần trang và trả về 0 video mới. Từ bên
    ngoài, ca đó trông y hệt "hashtag rỗng" và y hệt "index chết" — ba ca cần
    ba phản ứng khác nhau, nên UI phải phân biệt được.
    """
    with _connect(db_path) as conn:
        conn.execute("UPDATE jobs SET ly_do_dung = ? WHERE id = ?", (ly_do, job_id))


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
