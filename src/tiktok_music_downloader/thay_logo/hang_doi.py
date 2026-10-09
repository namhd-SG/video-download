"""Hàng đợi job thay logo — bảng RIÊNG trong `thay_logo_log.db` (ĐP-1508: không đụng `jobs.db` của 2 lane tải).

Mỗi video một dòng `tl_job_video`, máy trạng thái:
  cho → (tải nguồn + đặt việc agy) → cho_agy → (agy nộp) → dang_chay → xong | cho_nguoi | loi
Boot: `dang_chay` ⇒ về `cho_agy` (+1 lần thử; hết lượt ⇒ `loi`) — tiến trình con chết theo tiến trình chủ, việc dở làm lại từ đầu.
"""
from __future__ import annotations

import json
import sqlite3
import time

SO_LAN_THU_TOI_DA = 3
TRANG_THAI = frozenset({'cho', 'cho_agy', 'dang_chay', 'xong', 'cho_nguoi', 'loi'})

SCHEMA = """
CREATE TABLE IF NOT EXISTS tl_job (
  id INTEGER PRIMARY KEY, nguoi_tao TEXT NOT NULL, tao_luc REAL NOT NULL, ghi_chu TEXT, ten_bo TEXT, thu_muc_ra_id TEXT);
CREATE TABLE IF NOT EXISTS tl_job_video (
  id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES tl_job(id), nguon TEXT NOT NULL,
  trang_thai TEXT NOT NULL DEFAULT 'cho'
    CHECK (trang_thai IN ('cho', 'cho_agy', 'dang_chay', 'xong', 'cho_nguoi', 'loi')),
  so_lan_thu INTEGER NOT NULL DEFAULT 0, cho_agy_tu REAL, cap_nhat_luc REAL NOT NULL, video_log_id INTEGER,
  duong_dan_goc TEXT, thong_so TEXT, drive_file_id_ra TEXT, loi_text TEXT);
CREATE INDEX IF NOT EXISTS ix_tl_job_video_tt ON tl_job_video(trang_thai, id);
CREATE INDEX IF NOT EXISTS ix_tl_job_nguoi_tao ON tl_job(nguoi_tao);
"""


# Cột thêm SAU khi bảng đã có trên máy chạy thật: `CREATE TABLE IF NOT EXISTS` không thêm cột vào bảng cũ ⇒ ALTER có kiểm.
_COT_THEM_SAU = (("ten_bo", "TEXT"), ("thu_muc_ra_id", "TEXT"))


def khoi_tao(conn) -> None:
    conn.executescript(SCHEMA)
    co = {r[1] for r in conn.execute("PRAGMA table_info(tl_job)")}
    for cot, kieu in _COT_THEM_SAU:
        if cot not in co:
            try:
                conn.execute(f"ALTER TABLE tl_job ADD COLUMN {cot} {kieu}")
            except sqlite3.OperationalError as e:  # tiến trình khác (web/worker) vừa thêm giữa lúc kiểm và ALTER
                if "duplicate column" not in str(e).lower():
                    raise
    conn.commit()


def ten_bo_hien_thi(job_id: int, ten_bo: str | None) -> str:
    """Job cũ (trước khi có tên bộ) không có tên ⇒ `Lượt #<id>`."""
    return ten_bo if ten_bo else f"Lượt #{job_id}"


def tao_job(conn, nguoi_tao: str, nguon: list[dict], ghi_chu: str = "", ten_bo: str | None = None) -> int:
    """`nguon`: mỗi phần tử một video, vd {"kieu": "drive", "file_id": "..."} — lưu nguyên dạng JSON."""
    if not nguon:
        raise ValueError("job cần ít nhất 1 video")
    now = time.time()
    cur = conn.execute("INSERT INTO tl_job (nguoi_tao, tao_luc, ghi_chu, ten_bo) VALUES (?,?,?,?)",
                       (nguoi_tao, now, ghi_chu[:500], ten_bo))
    conn.executemany("INSERT INTO tl_job_video (job_id, nguon, cap_nhat_luc) VALUES (?,?,?)",
                     [(cur.lastrowid, json.dumps(n, sort_keys=True), now) for n in nguon])
    conn.commit()
    return cur.lastrowid


def dat(conn, vid: int, trang_thai: str, **truong) -> None:
    cot = {"trang_thai": trang_thai, "cap_nhat_luc": time.time(), **truong}
    conn.execute(f"UPDATE tl_job_video SET {','.join(f'{k}=?' for k in cot)} WHERE id=?", [*cot.values(), vid])
    conn.commit()


def lay_mot(conn, trang_thai: str):
    return conn.execute("SELECT * FROM tl_job_video WHERE trang_thai=? ORDER BY id LIMIT 1", (trang_thai,)).fetchone()


def danh_sach(conn, trang_thai: str) -> list:
    return conn.execute("SELECT * FROM tl_job_video WHERE trang_thai=? ORDER BY id", (trang_thai,)).fetchall()


def quet_khoi_dong(conn) -> dict:
    """Gọi MỘT lần lúc boot, trước khi worker nhặt việc."""
    lam_lai = het_luot = 0
    for r in danh_sach(conn, "dang_chay"):
        if r["so_lan_thu"] + 1 >= SO_LAN_THU_TOI_DA:
            dat(conn, r["id"], "loi", so_lan_thu=r["so_lan_thu"] + 1, loi_text="dừng giữa chừng quá số lần thử (khởi động lại)")
            het_luot += 1
        else:
            dat(conn, r["id"], "cho_agy", so_lan_thu=r["so_lan_thu"] + 1)
            lam_lai += 1
    return {"lam_lai": lam_lai, "het_luot": het_luot}


def tuoi_cho_agy_cu_nhat(conn, bay_gio: float | None = None) -> float | None:
    r = conn.execute("SELECT min(cho_agy_tu) FROM tl_job_video WHERE trang_thai='cho_agy'").fetchone()[0]
    return None if r is None else round((bay_gio or time.time()) - r, 1)


def dem_dang_cho_cua(conn, nguoi_tao: str) -> int:
    """Số video chưa xong (`cho`/`cho_agy`/`dang_chay`) của một người — trần lượt chờ mỗi người."""
    return conn.execute("SELECT count(*) FROM tl_job_video v JOIN tl_job j ON j.id = v.job_id "
                        "WHERE j.nguoi_tao = ? AND v.trang_thai IN ('cho', 'cho_agy', 'dang_chay')", (nguoi_tao,)).fetchone()[0]
