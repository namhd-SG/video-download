"""Sổ "đã vào bộ tự tìm": ẩn video ngay khi có bằng chứng, dọn tệp nguồn sau 7 ngày.

Hai bảng (`web/models.py::init_db`):
  * `video_vao_bo`      — MỘT hàng mỗi video: mốc ẩn `an_luc`, mốc dọn
                          `drive_don_luc`, và bộ đếm dọn trượt.
  * `video_vao_bo_ban`  — mỗi bản sao đạt bằng chứng là MỘT hàng (bộ nào).

Mọi mốc ghi bằng `UPDATE … WHERE <mốc> IS NULL` (hoặc `ON CONFLICT … WHERE`)
trong `BEGIN IMMEDIATE`: hai lượt chồng nhau (bộ kiểm chạy đúng lúc tiến trình
thứ hai khởi động) chạy nối tiếp, lượt sau thấy mốc của lượt trước và KHÔNG dời
nó. Không có cờ khoá "đang dọn": một cờ như vậy kẹt vĩnh viễn nếu tiến trình bị
giết giữa lượt.

Không có hàm nào ở đây gọi Drive — Drive là việc của `vao_bo_kiem`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from web.models import _connect, _now
from web.vi_tu_con_song import CHUA_LOAI, CON_SONG_CHUNG

# Đồng hồ 7 ngày tính từ `an_luc` (lần xác minh ĐẦU; với backfill là lúc ghi
# backfill) — user chốt 26/09, plan 29/09.
SO_NGAY_DEN_KHI_DON = 7


def _doc_luc(iso: str) -> datetime:
    d = datetime.fromisoformat(iso)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def ngay_se_don(an_luc: str) -> str:
    """Lúc dự kiến dọn tệp nguồn = `an_luc` + 7 ngày (ISO, để trang hiện ngày)."""
    return (_doc_luc(an_luc) + timedelta(days=SO_NGAY_DEN_KHI_DON)).isoformat()


def ung_vien_can_kiem(db_path: Path) -> list[dict]:
    """Video còn sống, có tệp nguồn trên Drive và CHƯA bị ẩn: `[{video_id,
    drive_file_id, chu}]`, mới nhất trước (video vừa tải là video vừa được
    copy vào bộ nhiều khả năng nhất)."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT v.video_id, v.drive_file_id, j.nguoi_tao AS chu FROM videos v "
            "LEFT JOIN jobs j ON j.id = v.job_id "
            f"WHERE v.drive_file_id IS NOT NULL AND {CON_SONG_CHUNG} "
            "AND NOT EXISTS (SELECT 1 FROM video_vao_bo b WHERE b.video_id = v.video_id "
            "                AND b.an_luc IS NOT NULL) "
            "ORDER BY v.tao_luc DESC, v.video_id DESC").fetchall()
    return [dict(r) for r in rows]


def ghi_da_vao_bo(db_path: Path, video_id: str, chu: str | None, ban: list[dict],
                  luc: str | None = None) -> bool:
    """Ghi các bản sao đạt bằng chứng + mốc ẩn. CHỈ gọi SAU khi bằng chứng đạt.

    `ban`: `[{ban_copy_id, folder_id, ma_bo, bang_chung}]`, không rỗng. Trả True
    nếu lần gọi NÀY đặt `an_luc`; False nếu video đã có mốc ẩn (mốc không dời —
    video vào bộ nhiều lần vẫn giữ mốc đầu) hoặc đã dọn xong.
    """
    if not ban:
        raise ValueError("không có bản sao nào — không được ghi mốc ẩn")
    luc = luc or _now()
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO video_vao_bo (video_id, chu, an_luc) VALUES (?, ?, ?) "
            "ON CONFLICT(video_id) DO UPDATE SET an_luc = excluded.an_luc, "
            "chu = COALESCE(video_vao_bo.chu, excluded.chu) "
            "WHERE video_vao_bo.an_luc IS NULL AND video_vao_bo.drive_don_luc IS NULL",
            (video_id, chu, luc))
        da_dat_moc = cur.rowcount == 1
        # Hàng bản sao ghi kể cả khi mốc ẩn đã có: một bộ MỚI của cùng video
        # (29 video nằm ở 2 bộ) phải hiện thêm mã, `ban_copy_id` UNIQUE chặn ghi đôi.
        conn.executemany(
            "INSERT OR IGNORE INTO video_vao_bo_ban "
            "(video_id, ban_copy_id, folder_id, ma_bo, bang_chung, thay_luc) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(video_id, b["ban_copy_id"], b["folder_id"], b["ma_bo"], b["bang_chung"], luc)
             for b in ban])
    return da_dat_moc


def bo_an(db_path: Path, video_id: str, an_luc_da_doc: str) -> bool:
    """Bằng chứng ĐO RA ÂM ở ngày 7 ⇒ hiện lại video: xoá hàng sổ + các bản sao.

    Chỉ xoá khi mốc ẩn vẫn đúng giá trị lượt này đã đọc và chưa dọn — nếu lượt
    khác đã dọn/đổi trong lúc đo thì không đụng.
    """
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "DELETE FROM video_vao_bo WHERE video_id = ? AND an_luc = ? "
            "AND drive_don_luc IS NULL", (video_id, an_luc_da_doc))
        if cur.rowcount != 1:
            return False
        conn.execute("DELETE FROM video_vao_bo_ban WHERE video_id = ?", (video_id,))
    return True


def ban_cua_video(db_path: Path, video_id: str) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ban_copy_id, folder_id, ma_bo, bang_chung FROM video_vao_bo_ban "
            "WHERE video_id = ? ORDER BY thay_luc, ban_copy_id", (video_id,)).fetchall()
    return [dict(r) for r in rows]


def vao_bo_cho_videos(db_path: Path, video_ids: list[str]) -> dict[str, dict]:
    """`{video_id: {an_luc, se_don_luc, ma_bo: [...]}}` cho video ĐANG ẨN (có
    `an_luc`, chưa dọn) — một truy vấn cho cả trang. Video không ẩn không có khoá."""
    if not video_ids:
        return {}
    marks = ",".join("?" * len(video_ids))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT video_id, an_luc FROM video_vao_bo WHERE video_id IN ({marks}) "
            f"AND an_luc IS NOT NULL AND drive_don_luc IS NULL", video_ids).fetchall()
        ma = conn.execute(
            f"SELECT video_id, ma_bo FROM video_vao_bo_ban WHERE video_id IN ({marks}) "
            f"ORDER BY thay_luc, ma_bo", video_ids).fetchall()
    ma_theo_video: dict[str, list[str]] = {}
    for r in ma:
        if r["ma_bo"] not in ma_theo_video.setdefault(r["video_id"], []):
            ma_theo_video[r["video_id"]].append(r["ma_bo"])
    return {r["video_id"]: {"an_luc": r["an_luc"], "se_don_luc": ngay_se_don(r["an_luc"]),
                            "ma_bo": ma_theo_video.get(r["video_id"], [])}
            for r in rows}


def ung_vien_don(db_path: Path, bay_gio: datetime | None = None) -> list[dict]:
    """Video đã ẩn đủ 7 ngày mà chưa dọn: `[{video_id, drive_file_id, an_luc,
    da_loai}]`. KHÔNG lọc theo `da_loai_luc`: video người dùng đã Loại tay trong 7
    ngày vẫn phải được ghi mốc dọn (lý do `da_loai`, không gọi Drive) — nếu không nó
    ở lại sổ vĩnh viễn."""
    bay_gio = bay_gio or datetime.now(timezone.utc)
    han = bay_gio - timedelta(days=SO_NGAY_DEN_KHI_DON)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT b.video_id, v.drive_file_id, b.an_luc, NOT ({CHUA_LOAI}) AS da_loai "
            "FROM video_vao_bo b JOIN videos v ON v.video_id = b.video_id "
            "WHERE b.an_luc IS NOT NULL AND b.drive_don_luc IS NULL "
            "ORDER BY b.an_luc, b.video_id").fetchall()
    return [dict(r) for r in rows if _doc_luc(r["an_luc"]) <= han]


def ghi_don_drive(db_path: Path, video_id: str, ly_do: str, luc: str | None = None) -> bool:
    """Ghi mốc dọn. CHỈ gọi SAU khi Drive đã ok (hoặc ca không cần gọi Drive).

    True nếu lần gọi này đặt mốc; False nếu lượt khác đã đặt trước — không dời.
    """
    luc = luc or _now()
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE video_vao_bo SET drive_don_luc = ?, ly_do_don = ?, loi_cuoi = NULL "
            "WHERE video_id = ? AND drive_don_luc IS NULL", (luc, ly_do, video_id))
        return cur.rowcount == 1


def ghi_truot_don(db_path: Path, video_id: str, loi: str) -> int:
    """Dọn trượt một lần: tăng bộ đếm, lưu lỗi cuối. Trả số lần trượt sau khi
    tăng (0 nếu video đã dọn xong — không có gì để đếm). Không đụng `drive_don_luc`."""
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE video_vao_bo SET so_lan_truot = so_lan_truot + 1, loi_cuoi = ? "
            "WHERE video_id = ? AND drive_don_luc IS NULL", (loi[:200], video_id))
        row = conn.execute(
            "SELECT so_lan_truot FROM video_vao_bo WHERE video_id = ? "
            "AND drive_don_luc IS NULL", (video_id,)).fetchone()
    return int(row["so_lan_truot"]) if row else 0
