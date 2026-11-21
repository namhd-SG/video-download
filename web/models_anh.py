"""Dữ liệu BÀI ẢNH: ghi K tệp của một bài trong một giao dịch, liệt kê/đếm gom theo bài.

Mỗi TỆP ảnh là một hàng `videos` (`loai='anh'`, `video_id` = `file_id_anh(bai_id, thu_tu)`), nên máy vào bộ / Creative
Desk / dọn ngày 7 / thumb chạy nguyên trên một-hàng-một-tệp. Module này chỉ thêm hai thứ mà một hàng không đủ:
ghi CẢ bài hoặc không gì (`ghi_bai_anh`), và nhìn các hàng theo bài (`list_bai_anh`, `count_bai_anh`).

Bộ lọc ở MỨC TỆP (đúng như `models.list_videos`: chưa loại, chưa dọn khỏi Drive, chip "Đã vào bộ", chủ job) rồi MỚI gom:
một bài còn hiện chừng nào còn ≥ 1 tệp qua bộ lọc, và `files` chỉ gồm các tệp đã qua. Lệch một trong hai thì tổng của
`count_bai_anh` không khớp số bài các trang của `list_bai_anh`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from tiktok_music_downloader.tai_anh_cau_hinh import LOAI_ANH, file_id_anh
from web.models import _connect, _loc_vao_bo, _now
from web.vi_tu_con_song import CON_SONG_CHUNG, LA_ANH

_COT_GHI = ("video_id", "job_id", "url", "title", "author", "region", "duration", "play_count", "music_id",
            "drive_file_id", "tao_luc", "description", "track", "artist", "bai_id", "thu_tu", "bai_thu_muc_id")
_COT_BAT_BUOC = ("video_id", "job_id", "url", "bai_id", "thu_tu")


def _kiem_hang(rows: list[dict]) -> None:
    """Một bài trọn vẹn: cùng `bai_id`, `thu_tu` 1..K không trùng, `video_id` đúng `file_id_anh`. Ném `ValueError`
    TRƯỚC khi chạm DB — hàng sai hình không được ghi dở một nửa."""
    if not rows:
        raise ValueError("bài ảnh phải có ít nhất một tệp")
    for r in rows:
        thieu = [c for c in _COT_BAT_BUOC if r.get(c) in (None, "")]
        if thieu:
            raise ValueError(f"hàng ảnh thiếu {', '.join(thieu)}")
        la = set(r) - set(_COT_GHI)
        if la:
            raise ValueError(f"hàng ảnh có cột lạ: {', '.join(sorted(la))}")
    bai = {r["bai_id"] for r in rows}
    if len(bai) != 1:
        raise ValueError("mọi tệp của một lượt ghi phải cùng một bài")
    thu_tu = sorted(r["thu_tu"] for r in rows)
    if thu_tu != list(range(1, len(rows) + 1)):
        raise ValueError("thu_tu của bài phải là 1..K liên tục, không trùng")
    for r in rows:
        if r["video_id"] != file_id_anh(r["bai_id"], r["thu_tu"]):
            raise ValueError("video_id không khớp bai_id + thu_tu")


def ghi_bai_anh(db_path_or_conn: Path | str | sqlite3.Connection, rows: list[dict]) -> int:
    """Ghi K hàng `videos` (một bài) trong MỘT giao dịch: hoặc đủ K hàng hoặc không hàng nào. Trả số hàng MỚI.

    `rows`: mỗi phần tử có `video_id`, `job_id`, `url`, `bai_id`, `thu_tu` (bắt buộc) và tuỳ chọn `title`, `author`,
    `region`, `duration`, `play_count`, `music_id`, `drive_file_id`, `tao_luc`, `description`, `track`, `artist`,
    `bai_thu_muc_id`. Mọi hàng được ép `loai='anh'`. `ON CONFLICT DO NOTHING` như `models.record_video`: gặp lại
    cùng tệp thì giữ lần thấy đầu (`job_id`/`tao_luc` là thứ bộ lọc "ai tải / khi nào" đọc), không ghi đè.

    Gọi SAU khi cả K tệp đã lên Drive — hàng ở đây nghĩa là "tệp này nằm trong Shared Drive", không yếu hơn."""
    _kiem_hang(rows)
    cot = ", ".join(_COT_GHI)
    cau = (f"INSERT INTO videos ({cot}, loai) VALUES ({', '.join('?' * len(_COT_GHI))}, '{LOAI_ANH}') "
           "ON CONFLICT(video_id) DO NOTHING")
    gia_tri = [tuple((r.get("tao_luc") or _now()) if c == "tao_luc" else r.get(c) for c in _COT_GHI) for r in rows]

    def ghi(conn: sqlite3.Connection) -> int:
        truoc = conn.total_changes
        conn.executemany(cau, gia_tri)
        return conn.total_changes - truoc

    if isinstance(db_path_or_conn, sqlite3.Connection):
        with db_path_or_conn:        # commit khi xong, rollback khi lỗi — người gọi không phải nhớ
            return ghi(db_path_or_conn)
    with _connect(Path(db_path_or_conn)) as conn:
        return ghi(conn)


_TU_CHU = ("FROM videos v LEFT JOIN jobs j ON j.id = v.job_id "
           f"WHERE {CON_SONG_CHUNG} AND {LA_ANH} AND v.bai_id IS NOT NULL AND (? IS NULL OR j.nguoi_tao = ?) ")


def list_bai_anh(db_path: Path, chi_cua: str | None, limit: int = 500, offset: int = 0,
                 vao_bo: bool | None = None) -> list[dict]:
    """Bài ảnh mới nhất trước, chỉ của `chi_cua` (`None` = tất cả, dành cho admin; KHÔNG có mặc định, cùng lý do
    như `models.list_videos`). Mỗi bài: `bai_id`, `thumb_id` (= `video_id` của tệp thu_tu 1 — thumb luôn cắt từ ảnh 01),
    `file_ids` (theo thu_tu), `so_anh`, `tao_luc`, `nguoi_tao`, và `files`: các hàng `videos` (cùng hình một video
    của `GET /videos`: `v.*` + `nguoi_tao`) đã qua bộ lọc, theo thu_tu."""
    loc = _loc_vao_bo(vao_bo)
    with _connect(db_path) as conn:
        bai = conn.execute(
            f"SELECT v.bai_id {_TU_CHU}{loc}GROUP BY v.bai_id "
            "ORDER BY MAX(v.tao_luc) DESC, v.bai_id DESC LIMIT ? OFFSET ?",
            (chi_cua, chi_cua, limit, offset)).fetchall()
        ids = [r["bai_id"] for r in bai]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        hang = conn.execute(
            f"SELECT v.*, j.nguoi_tao {_TU_CHU}{loc}AND v.bai_id IN ({marks}) "
            "ORDER BY v.bai_id, v.thu_tu",
            (chi_cua, chi_cua, *ids)).fetchall()
    theo_bai: dict[str, list[dict]] = {i: [] for i in ids}
    for r in hang:
        theo_bai[r["bai_id"]].append(dict(r))
    ra = []
    for bai_id in ids:        # giữ thứ tự bài đã sắp ở truy vấn đầu
        files = theo_bai[bai_id]
        if not files:         # hai truy vấn cùng một bộ lọc; trống chỉ khi có ai đó vừa bỏ ảnh giữa hai lượt
            continue
        ra.append({
            "bai_id": bai_id,
            "thumb_id": file_id_anh(bai_id, 1),
            "file_ids": [f["video_id"] for f in files],
            "so_anh": len(files),
            "tao_luc": max(f["tao_luc"] for f in files),
            "nguoi_tao": files[0]["nguoi_tao"],
            "files": files,
        })
    return ra


def count_bai_anh(db_path: Path, chi_cua: str | None, vao_bo: bool | None = None) -> int:
    """Số BÀI ảnh qua đúng bộ lọc của `list_bai_anh` (UI dùng số này để quyết định xin thêm trang)."""
    with _connect(db_path) as conn:
        return int(conn.execute(
            f"SELECT COUNT(DISTINCT v.bai_id) {_TU_CHU}{_loc_vao_bo(vao_bo)}",
            (chi_cua, chi_cua)).fetchone()[0])
