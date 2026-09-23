"""Cụm của tôi — nhóm video gán tay, mỗi cụm thành một (hay vài) bộ tự tìm
bên Creative Desk. Bảng sống trong `web/models.py` (`init_db`); đây là các
câu hỏi/ghi trên chúng.

Luật quyền sở hữu, giống `models.video_de_loai`: mọi hàm nhận `chu` KHÔNG có
mặc định, và lọc theo nó NGAY TRONG câu SQL. Một id cụm hay danh sách id video
do client gửi là đầu vào không tin được; cách duy nhất để "cụm của người khác"
không bao giờ đi tiếp là để câu SQL tự loại nó.

`chu` luôn là email người gọi — kể cả admin. Admin thấy cả kho video, nhưng
cụm là bàn làm việc riêng; không có "cụm của cả team".
"""
from __future__ import annotations

import math
from pathlib import Path

from web.models import _connect, _now

# Trần `items` của một lần bàn giao — trùng `HANDOFF_MAX` (web/static/app.js)
# và `MAX_ITEMS` bên meta-ads (hợp đồng `nhan`, quy tắc 7).
LO_TOI_DA = 30
USECASE_TOI_DA = 80
INSIGHT_CON_TOI_DA = 120


def chuan_hoa_chu(s: str) -> str:
    """Bỏ khoảng trắng hai đầu, gộp mọi dải khoảng trắng về một dấu cách."""
    return " ".join((s or "").split())


def ten_insight_con(insight_goc: str, kieu: str) -> str:
    """Tên insight con gửi sang Creative Desk: `"<insight gốc> <kiểu>"`.

    MỘT hàm cho cả hiển thị lẫn payload (hợp đồng `nhan`, quy tắc 4). Hai
    chỗ tự ghép riêng là hai cách viết, và lệch một dấu cách thì bên nhận tạo
    ra một insight trùng tên mà không ai thấy.
    """
    return chuan_hoa_chu(f"{insight_goc} {kieu}")


def so_lo(so_video: int) -> int:
    """Cụm N video tách thành bao nhiêu lô 30/30/…/dư. 0 video ⇒ 0 lô."""
    return math.ceil(max(so_video, 0) / LO_TOI_DA)


def kiem_nhan(usecase: str, insight_goc: str, kieu: str) -> tuple[str, str, str]:
    """Chuẩn hoá ba ô nhãn và kiểm biên theo hợp đồng. Sai ⇒ `ValueError`."""
    u, g, k = chuan_hoa_chu(usecase), chuan_hoa_chu(insight_goc), chuan_hoa_chu(kieu)
    if not (1 <= len(u) <= USECASE_TOI_DA):
        raise ValueError(f"usecase phải 1..{USECASE_TOI_DA} ký tự")
    if not g:
        raise ValueError("insight gốc không được trống")
    if not k:
        raise ValueError("kiểu không được trống")
    if len(ten_insight_con(g, k)) > INSIGHT_CON_TOI_DA:
        raise ValueError(f"tên insight con (insight gốc + kiểu) quá {INSIGHT_CON_TOI_DA} ký tự")
    return u, g, k


def _cum_cua_toi(conn, cum_id: int, chu: str):
    return conn.execute(
        "SELECT * FROM cum WHERE id = ? AND chu = ?", (cum_id, chu)).fetchone()


def _dang_ra(row, so_video: int, lo_mo: list[dict]) -> dict:
    return {
        "id": row["id"],
        "usecase": row["usecase"],
        "insight_goc": row["insight_goc"],
        "kieu": row["kieu"],
        "insight": ten_insight_con(row["insight_goc"], row["kieu"]),
        "tao_luc": row["tao_luc"],
        "so_video": so_video,
        "so_lo": so_lo(so_video),
        "lo_mo": lo_mo,
    }


# Video được đếm trong cụm chỉ khi nó còn trong thư viện của người đó: chưa bị
# loại, và (trừ admin) thuộc job người đó tạo. Cùng điều kiện `list_videos`,
# để số trên thanh bên khớp số thẻ lưới hiện ra.
_VIDEO_CON_THAY = (
    "JOIN videos v ON v.video_id = vc.video_id "
    "LEFT JOIN jobs j ON j.id = v.job_id "
    "WHERE v.da_loai_luc IS NULL AND (? IS NULL OR j.nguoi_tao = ?) "
)


def liet_ke_cum(db_path: Path, chu: str, chi_cua: str | None) -> list[dict]:
    """Mọi cụm của `chu`, kèm số video, số lô và mốc đã mở từng lô.

    `chi_cua` là phạm vi thư viện (None = admin) — dùng để đếm video còn thấy.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM cum WHERE chu = ? ORDER BY usecase, insight_goc, kieu, id",
            (chu,)).fetchall()
        dem = {r["cum_id"]: r["n"] for r in conn.execute(
            "SELECT vc.cum_id, COUNT(*) AS n FROM video_cum vc " + _VIDEO_CON_THAY +
            "AND vc.chu = ? GROUP BY vc.cum_id",
            (chi_cua, chi_cua, chu)).fetchall()}
        mo: dict[int, list[dict]] = {}
        for r in conn.execute(
                "SELECT m.cum_id, m.thu, m.mo_luc FROM cum_lo_mo m "
                "JOIN cum c ON c.id = m.cum_id WHERE c.chu = ? ORDER BY m.cum_id, m.thu",
                (chu,)).fetchall():
            mo.setdefault(r["cum_id"], []).append({"thu": r["thu"], "mo_luc": r["mo_luc"]})
    return [_dang_ra(r, dem.get(r["id"], 0), mo.get(r["id"], [])) for r in rows]


def dem_da_vao_cum(db_path: Path, chu: str, chi_cua: str | None) -> int:
    """Bao nhiêu video trong thư viện này đã nằm trong một cụm của `chu`."""
    with _connect(db_path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM video_cum vc " + _VIDEO_CON_THAY + "AND vc.chu = ?",
            (chi_cua, chi_cua, chu)).fetchone()[0])


def lay_cum(db_path: Path, cum_id: int, chu: str, chi_cua: str | None) -> dict | None:
    """Một cụm nếu nó của `chu`; ngược lại None (route trả 404)."""
    for c in liet_ke_cum(db_path, chu, chi_cua):
        if c["id"] == cum_id:
            return c
    return None


def tao_cum(db_path: Path, chu: str, usecase: str, insight_goc: str, kieu: str) -> int:
    u, g, k = kiem_nhan(usecase, insight_goc, kieu)
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO cum (chu, usecase, insight_goc, kieu, tao_luc) VALUES (?, ?, ?, ?, ?)",
            (chu, u, g, k, _now()))
        return int(cur.lastrowid)


def doi_kieu(db_path: Path, cum_id: int, chu: str, kieu: str) -> bool:
    """Đổi kiểu của cụm `chu`. False ⇒ không phải cụm của người này."""
    with _connect(db_path) as conn:
        row = _cum_cua_toi(conn, cum_id, chu)
        if row is None:
            return False
        _, _, k = kiem_nhan(row["usecase"], row["insight_goc"], kieu)
        cur = conn.execute("UPDATE cum SET kieu = ? WHERE id = ? AND chu = ?",
                           (k, cum_id, chu))
        return cur.rowcount == 1


def xoa_cum(db_path: Path, cum_id: int, chu: str) -> bool:
    """Xoá cụm của `chu`; video trong nó về "chưa vào cụm" (ON DELETE CASCADE
    — cần `PRAGMA foreign_keys=ON`, bật trong `models._connect`)."""
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM cum WHERE id = ? AND chu = ?", (cum_id, chu))
        return cur.rowcount == 1


def gan_video(db_path: Path, cum_id: int, chu: str, chi_cua: str | None,
              video_ids: list[str]) -> list[str] | None:
    """Đưa các video vào cụm `cum_id` của `chu`. Trả id đã gán; None ⇒ cụm
    không phải của người này.

    Video đang ở cụm khác của cùng người thì CHUYỂN (ghi đè theo khoá
    `(video_id, chu)`), không nằm hai cụm. Id không thuộc thư viện của người
    gọi (hoặc đã loại) bị câu SELECT tự bỏ, không bao giờ tới câu INSERT.
    """
    ids = list(dict.fromkeys(video_ids))
    with _connect(db_path) as conn:
        if _cum_cua_toi(conn, cum_id, chu) is None:
            return None
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        hop_le = [r["video_id"] for r in conn.execute(
            f"SELECT v.video_id FROM videos v LEFT JOIN jobs j ON j.id = v.job_id "
            f"WHERE v.video_id IN ({marks}) AND v.da_loai_luc IS NULL "
            f"AND (? IS NULL OR j.nguoi_tao = ?)",
            [*ids, chi_cua, chi_cua]).fetchall()]
        conn.executemany(
            "INSERT INTO video_cum (video_id, chu, cum_id) "
            "SELECT ?, c.chu, c.id FROM cum c WHERE c.id = ? AND c.chu = ? "
            "ON CONFLICT(video_id, chu) DO UPDATE SET cum_id = excluded.cum_id",
            [(vid, cum_id, chu) for vid in hop_le])
    return hop_le


def go_video(db_path: Path, cum_id: int, chu: str,
             video_ids: list[str]) -> list[str] | None:
    """Gỡ video khỏi cụm `cum_id` của `chu` (về "chưa vào cụm"). Trả id đã gỡ;
    None ⇒ cụm không phải của người này."""
    ids = list(dict.fromkeys(video_ids))
    with _connect(db_path) as conn:
        if _cum_cua_toi(conn, cum_id, chu) is None:
            return None
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        da_go = [r["video_id"] for r in conn.execute(
            f"SELECT video_id FROM video_cum WHERE chu = ? AND cum_id = ? "
            f"AND video_id IN ({marks})", [chu, cum_id, *ids]).fetchall()]
        conn.execute(
            f"DELETE FROM video_cum WHERE chu = ? AND cum_id = ? AND video_id IN ({marks})",
            [chu, cum_id, *ids])
    return da_go


def cum_cho_videos(db_path: Path, video_ids: list[str], chu: str) -> dict[str, int]:
    """`{video_id: cum_id}` theo cụm CỦA `chu` — một truy vấn cho cả trang."""
    if not video_ids:
        return {}
    marks = ",".join("?" * len(video_ids))
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT video_id, cum_id FROM video_cum WHERE chu = ? AND video_id IN ({marks})",
            [chu, *video_ids]).fetchall()
    return {r["video_id"]: r["cum_id"] for r in rows}


def ghi_lo_da_mo(db_path: Path, cum_id: int, chu: str, thu: int) -> str | None:
    """Ghi (hoặc làm mới — "Mở lại") mốc đã mở Creative Desk cho lô `thu`.

    Người gọi chỉ được gọi SAU khi tab đã mở thật. Trả mốc đã ghi; None ⇒
    cụm không phải của người này. `thu` ngoài 1..số lô do route kiểm.
    """
    luc = _now()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO cum_lo_mo (cum_id, thu, mo_luc) "
            "SELECT c.id, ?, ? FROM cum c WHERE c.id = ? AND c.chu = ? "
            "ON CONFLICT(cum_id, thu) DO UPDATE SET mo_luc = excluded.mo_luc",
            (thu, luc, cum_id, chu))
        return luc if cur.rowcount == 1 else None
