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


_NGUOI_DUNG_SCHEMA = """
CREATE TABLE IF NOT EXISTS nguoi_dung (
    email TEXT PRIMARY KEY,
    la_admin INTEGER NOT NULL DEFAULT 0,
    tran_luot INTEGER,
    tran_video INTEGER,
    -- NULL = có job từ trước khi bảng này tồn tại, chưa thấy đăng nhập lần nào.
    -- Điền một mốc thời gian ở đây sẽ là một con số bịa.
    lan_dau_thay TEXT,
    lan_cuoi_thay TEXT,
    cap_boi TEXT,
    cap_luc TEXT
)
"""

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
        conn.execute(_NGUOI_DUNG_SCHEMA)
        # Bổ khuyết người đã có job từ trước khi bảng này tồn tại. Không có
        # bước này thì ngay sau khi nâng cấp, trang Quản trị gần như TRỐNG và
        # admin **không đặt được trần cho ai** cho tới khi từng người tự ghé
        # trang — mà `jobs.nguoi_tao` là nguồn danh tính duy nhất đang có.
        # `lan_dau_thay` để NULL: chưa "thấy" họ đăng nhập bao giờ, nên một mốc
        # thời gian ở đây sẽ là một con số bịa.
        conn.execute(
            "INSERT OR IGNORE INTO nguoi_dung "
            "(email, la_admin, lan_dau_thay, lan_cuoi_thay) "
            "SELECT DISTINCT LOWER(TRIM(nguoi_tao)), 0, NULL, NULL FROM jobs "
            "WHERE nguoi_tao IS NOT NULL AND TRIM(nguoi_tao) <> ''"
        )
        for statement in _SIGHTINGS_INDEX:
            conn.execute(statement)
        # `videos` shipped before `music_id`/`drive_file_id` existed, so an
        # already-created table needs them added. Same ad hoc migration the
        # jobs table uses above; duplicate-column means it is already done.
        # `da_loai_luc`/`loai_boi`: ai đã bỏ video này khỏi thư viện CỦA HỌ, lúc
        # nào. Theo NGƯỜI chứ không phải một cờ chung — user chốt 17/09 rằng
        # loại là việc riêng: "không ảnh hưởng gì đến chung cả, vì đó là bộ của
        # tôi". Một cờ chung sẽ biến phán xét của một người thành lệnh chặn cho
        # cả team.
        for column, decl in (("music_id", "TEXT"), ("drive_file_id", "TEXT"),
                             ("da_loai_luc", "TEXT"), ("loai_boi", "TEXT")):
            _add_column_if_missing(conn, "videos", column, decl)
        # `CREATE TABLE IF NOT EXISTS` above does nothing for a `jobs.db`
        # that already existed before `drive_folder_link` was added — this
        # ad hoc migration is the only thing that backfills the column onto
        # a pre-existing table. sqlite3.OperationalError (duplicate column)
        # means it is already there; that is the expected steady state.
        _add_column_if_missing(conn, "jobs", "drive_folder_link", "TEXT")
        _add_column_if_missing(conn, "jobs", "ly_do_dung", "TEXT")
        _add_column_if_missing(conn, "jobs", "so_trang", "INTEGER NOT NULL DEFAULT 0")


def ghi_nhan_nguoi_dung(db_path: Path, email: str) -> None:
    """Người này vừa đăng nhập. Gọi mỗi lượt, rẻ và bắt buộc.

    Không có bảng này thì KHÔNG CÓ CÁCH NÀO liệt kê người dùng: danh tính chỉ
    tồn tại dưới dạng `jobs.nguoi_tao` (chỉ có ai đã TẠO JOB, không có ai mới
    chỉ đăng nhập) và tên tệp cookie `sha256(email)` — một chiều, không lật
    ngược được. Trang Quản trị mà không liệt kê được người thì không quản gì.

    `INSERT … ON CONFLICT DO UPDATE` chỉ chạm `lan_cuoi_thay`: `la_admin` và
    hai cột trần là thứ quản trị đặt, một lượt đăng nhập không được đụng vào.
    """
    luc = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO nguoi_dung (email, lan_dau_thay, lan_cuoi_thay) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET lan_cuoi_thay = excluded.lan_cuoi_thay",
            (email.strip().lower(), luc, luc),
        )


def danh_sach_nguoi_dung(db_path: Path) -> list[dict]:
    """Mọi người đã từng đăng nhập, kèm số đã dùng hôm nay để admin nhìn là biết."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT email, la_admin, tran_luot, tran_video, lan_dau_thay, "
            "lan_cuoi_thay, cap_boi, cap_luc FROM nguoi_dung ORDER BY email"
        ).fetchall()
    return [dict(r) for r in rows]


def dem_admin(db_path: Path) -> int:
    with _connect(db_path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM nguoi_dung WHERE la_admin = 1").fetchone()[0])


def dat_quyen_admin(db_path: Path, email: str, la_admin: bool,
                    cap_boi: str) -> bool:
    """Phong hoặc bỏ quyền admin. Trả `False` khi lượt bỏ bị TỪ CHỐI.

    Việc "còn admin nào khác không" nằm **trong chính câu UPDATE**, không phải
    ở một lần đọc trước đó. Kiểm-rồi-ghi bằng hai lượt đọc-ghi rời nhau có hai
    đường vỡ, cả hai đã được dựng lại và đo:

      * **Đua.** Hai admin bỏ quyền của nhau cùng lúc: cả hai đọc "còn 2" trước
        khi ai kịp ghi ⇒ cả hai lượt qua cửa ⇒ **còn 0 admin**.
      * **Fail-open.** Người gọi hỏi "người này có phải admin không" qua một
        hàm trả `False` khi DB lỗi thoáng qua; `False` làm điều kiện canh bị
        bỏ qua hoàn toàn (short-circuit) ⇒ lượt bỏ đi thẳng ⇒ **còn 0 admin**.

    `WHERE` có điều kiện con nên SQLite đánh giá nó trong cùng giao dịch với
    phép ghi; không còn khe nào giữa "đếm" và "ghi". Trả `bool` thay vì `None`
    vì người gọi PHẢI phân biệt được "đã đổi" với "bị từ chối" — một hàm im
    lặng ở đây là một khoá không ai biết đã mở hay chưa.
    """
    luc = datetime.now(timezone.utc).isoformat()
    e = email.strip().lower()
    with _connect(db_path) as conn:
        if la_admin:
            cur = conn.execute(
                "UPDATE nguoi_dung SET la_admin = 1, cap_boi = ?, cap_luc = ? "
                "WHERE email = ?", (cap_boi, luc, e))
        else:
            # Chỉ hạ quyền khi VẪN CÒN admin khác sau lượt này.
            cur = conn.execute(
                "UPDATE nguoi_dung SET la_admin = 0, cap_boi = ?, cap_luc = ? "
                "WHERE email = ? AND la_admin = 1 "
                "AND (SELECT COUNT(*) FROM nguoi_dung WHERE la_admin = 1) > 1",
                (cap_boi, luc, e))
        return cur.rowcount > 0


def dat_tran_nguoi_dung(db_path: Path, email: str, **truong) -> bool:
    """Đặt trần riêng. Chỉ ghi những cột ĐƯỢC TRUYỀN, trả `False` nếu không ai khớp.

    Nhận `**truong` chứ không nhận hai tham số cố định, vì `None` ở đây có HAI
    nghĩa không được lẫn: "không gửi trường này" và "đặt về mặc định hệ thống".
    Ghi cả hai cột mỗi lượt biến một lượt sửa `tran_luot` thành lượt **xoá**
    `tran_video` — mất cấu hình, không một lời cảnh báo. Đã dựng lại và đo.

    `None` **có truyền** vẫn nghĩa là "về mặc định hệ thống" — không phải
    "không giới hạn".
    """
    cho_phep = {"tran_luot", "tran_video"}
    dat = {k: v for k, v in truong.items() if k in cho_phep}
    if not dat:
        return False
    gan = ", ".join(f"{k} = ?" for k in dat)
    with _connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE nguoi_dung SET {gan} WHERE email = ?",
            (*dat.values(), email.strip().lower()),
        )
        return cur.rowcount > 0


def tran_rieng_cua(db_path: Path, email: str) -> tuple[int | None, int | None]:
    """Trần riêng của người này, `(None, None)` nếu chưa đặt hoặc chưa có hàng."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT tran_luot, tran_video FROM nguoi_dung WHERE email = ?",
            (email.strip().lower(),)).fetchone()
    return (row["tran_luot"], row["tran_video"]) if row else (None, None)


def moi_admin_tu_env(db_path: Path, emails: list[str]) -> int:
    """Mồi admin từ env — CHỈ khi bảng chưa có admin nào. Trả số đã mồi.

    "Một lần" định nghĩa bằng TRẠNG THÁI, không bằng cờ: có admin rồi thì bỏ
    qua env hoàn toàn. Nếu để env thắng mãi thì admin cấp từ env không bỏ được
    ở giao diện, và nút "Bỏ quyền admin" thành một nút bấm-không-làm-gì — đúng
    loại nút chết đã bị phàn nàn.

    Bài toán mồi này không mở thêm cửa nào: người sửa được tệp env là người có
    shell trên máy, vốn đã toàn quyền với cả dịch vụ lẫn cơ sở dữ liệu.
    """
    if dem_admin(db_path) > 0:
        return 0
    luc = datetime.now(timezone.utc).isoformat()
    da_moi = 0
    with _connect(db_path) as conn:
        for email in emails:
            e = email.strip().lower()
            if not e:
                continue
            conn.execute(
                "INSERT INTO nguoi_dung (email, la_admin, lan_dau_thay, lan_cuoi_thay, "
                "cap_boi, cap_luc) VALUES (?, 1, ?, ?, 'mồi từ cấu hình máy', ?) "
                "ON CONFLICT(email) DO UPDATE SET la_admin = 1, "
                "cap_boi = 'mồi từ cấu hình máy', cap_luc = excluded.cap_luc",
                (e, luc, luc, luc),
            )
            da_moi += 1
    return da_moi


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


def sources_for_videos(db_path: Path, video_ids: list[str],
                       chi_cua: str | None) -> dict[str, list[str]]:
    """`{video_id: [nguồn, …]}` — the sources each video was seen under, as
    seen by ONE person. `chi_cua=None` means every source, admins only.

    `chi_cua` has no default on purpose: `nguon` is the whole URL for search
    and profile jobs, i.e. the words somebody typed. That is the same class of
    data as `jobs.url`, which `/jobs` already filters. A caller that forgets
    the argument must break loudly here rather than quietly serve one person
    the search terms of another.

    LEFT JOIN for the same reason `list_videos` uses one: a sighting whose job
    row is missing keeps `nguoi_tao = NULL`, so it drops out for every member
    and only an admin still sees it. An inner join would drop it for admins
    too, and drop it silently.
    """
    if not video_ids:
        return {}
    marks = ",".join("?" * len(video_ids))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT DISTINCT s.video_id, s.nguon FROM video_sightings s "
            f"LEFT JOIN jobs j ON j.id = s.job_id "
            f"WHERE s.video_id IN ({marks}) AND (? IS NULL OR j.nguoi_tao = ?) "
            f"ORDER BY s.nguon",
            [*video_ids, chi_cua, chi_cua],
        ).fetchall()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r["video_id"], []).append(r["nguon"])
    return out


def video_de_loai(db_path: Path, video_ids: list[str],
                  chi_cua: str | None) -> list[dict]:
    """Những video trong danh sách này mà `chi_cua` thật sự sở hữu và chưa loại.

    Trả cả `drive_file_id` vì người gọi cần nó để bỏ file vào thùng rác. Lọc
    quyền sở hữu Ở ĐÂY, không ở tầng route: một danh sách id do client gửi lên
    là đầu vào không tin được, và cách duy nhất khiến "id của người khác" không
    bao giờ đi tiếp là để câu SQL tự loại nó.
    """
    if not video_ids:
        return []
    marks = ",".join("?" * len(video_ids))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT v.video_id, v.drive_file_id FROM videos v "
            f"LEFT JOIN jobs j ON j.id = v.job_id "
            f"WHERE v.video_id IN ({marks}) AND v.da_loai_luc IS NULL "
            f"AND (? IS NULL OR j.nguoi_tao = ?)",
            [*video_ids, chi_cua, chi_cua],
        ).fetchall()
    return [dict(r) for r in rows]


def danh_dau_da_loai(db_path: Path, video_id: str, nguoi_loai: str) -> None:
    """Ghi mốc "đã loại". Gọi SAU khi file đã vào thùng rác, không bao giờ trước.

    Thứ tự đó là toàn bộ điểm của hàm này. Ghi mốc trước rồi trash trượt thì
    video biến khỏi thư viện trong khi file còn nguyên trên Drive, và không có
    gì báo — chủ tưởng đã dọn, kho thì vẫn giữ. Hỏng theo chiều ngược lại (trash
    xong mà chưa kịp ghi mốc) thì lượt sau chỉ đơn giản loại lại: ồn, nhưng
    thấy được.
    """
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE videos SET da_loai_luc = ?, loai_boi = ? WHERE video_id = ?",
            (datetime.now(timezone.utc).isoformat(), nguoi_loai, video_id),
        )


def video_nay_cua_toi(db_path: Path, video_id: str, chi_cua: str | None) -> bool:
    """Is this one video in `chi_cua`'s library? `None` = admin, always True
    for a video that exists at all.

    Exists so `/thumbs` can ask the same question `/videos` answers, instead
    of trusting that an id is hard to come by. It is not: this repo's own
    `hashtag_enumerator` harvests a real `video_id` for every item in a feed,
    so anyone can hand the endpoint a list of genuine ids. Without this, the
    200-vs-404 pair tells a member which videos the team already has — the
    aggregate that `sources_for_videos` was just filtered to hide.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM videos v "
            "LEFT JOIN jobs j ON j.id = v.job_id "
            "WHERE v.video_id = ? AND (? IS NULL OR j.nguoi_tao = ?)",
            (video_id, chi_cua, chi_cua),
        ).fetchone()
    return row is not None


def known_video_ids(db_path: Path, video_ids: list[str]) -> set[str]:
    """Which of these do we already have? Drives the duplicate skip.

    Takes the candidate list rather than loading the whole table: the library
    is meant to grow without bound, and a per-job SELECT of every row would
    quietly become the slowest part of enumerating.

    ⚠ KHÔNG thêm `WHERE da_loai_luc IS NULL` vào đây. Câu hỏi của hàm này là
    "kho đã có file này chưa", không phải "ai còn muốn thấy nó". Lọc theo cột
    loại sẽ làm lượt quét sau tải LẠI đúng video mà chủ vừa bỏ — tốn một lượt
    TikTok và dựng lại thứ họ vừa dọn. Thư viện lọc ở `list_videos`; chỗ này
    thì không.
    """
    if not video_ids:
        return set()
    marks = ",".join("?" * len(video_ids))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT video_id FROM videos WHERE video_id IN ({marks})", video_ids
        ).fetchall()
    return {r["video_id"] for r in rows}


def list_videos(db_path: Path, chi_cua: str | None,
                limit: int = 500, offset: int = 0) -> list[dict]:
    """Newest first, showing only what `chi_cua` downloaded. `None` = all,
    which is for admins.

    `chi_cua` has no default, deliberately. This is a function that decides
    who sees what, and the repo already paid for one of those having a quiet
    default (`prepare_data_dir` reached into production). A caller that
    forgets the argument gets a TypeError, not everyone else's library.

    Ownership is `jobs.nguoi_tao` of the job that downloaded the video —
    "whoever pressed download owns it", user's decision on 17/09. A video
    skipped as a duplicate never gets a `videos` row, so it belongs to
    nobody but the first downloader, and there is no second claimant.

    LEFT JOIN, not JOIN: a video whose job row is gone would otherwise vanish
    from the count as well as the grid. It keeps `nguoi_tao = NULL`, so it
    falls out for every member and only an admin (`chi_cua=None`) still sees
    it. That is the safe direction to fail.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT v.*, j.nguoi_tao FROM videos v "
            "LEFT JOIN jobs j ON j.id = v.job_id "
            "WHERE v.da_loai_luc IS NULL AND (? IS NULL OR j.nguoi_tao = ?) "
            "ORDER BY v.tao_luc DESC, v.video_id DESC "
            "LIMIT ? OFFSET ?",
            (chi_cua, chi_cua, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows]


def count_videos(db_path: Path, chi_cua: str | None) -> int:
    """Must filter exactly like `list_videos`: the UI uses this number to
    decide whether to ask for another page, and prints it as "N video". A
    total taken over the whole warehouse would both over-page and tell each
    member a number that is not theirs.
    """
    with _connect(db_path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM videos v "
            "LEFT JOIN jobs j ON j.id = v.job_id "
            "WHERE v.da_loai_luc IS NULL AND (? IS NULL OR j.nguoi_tao = ?)",
            (chi_cua, chi_cua),
        ).fetchone()[0])


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
