"""Chuyển trạng thái DB của job trong luồng giải captcha (`cho_xac_minh` → … → `running`/`failed`).

Mỗi bước là MỘT câu UPDATE có điều kiện trạng thái đi (`WHERE trang_thai IN (...)`): hai bên
cùng muốn đổi một job (nút bấm / hết hạn / worker) thì đúng một bên thắng (`rowcount == 1`),
bên kia nhận False và phải bỏ. Không đọc-rồi-ghi. Các hàm đụng cột `vao_trang_thai_luc` /
`so_lan_giai_ngay` (thêm ở `models.init_db`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from web import giai_captcha as gc
from web.models import _connect, _now

# Giá trị mặc định "đừng đụng cột lý do" (khác `None` = đặt về NULL).
GIU_LY_DO = object()

_KET_THUC = ("done", "failed", "interrupted", "cancelled")


def chuyen_trang_thai(db_path: Path, job_id: int, tu: str | tuple[str, ...], den: str, *,
                      ly_do: object = GIU_LY_DO) -> bool:
    """Lật `trang_thai` từ MỘT trong `tu` sang `den`; True nếu đã đổi.

    `den` là trạng thái trung gian ⇒ ghi `vao_trang_thai_luc = now`; `den` là trạng thái kết thúc
    ⇒ ghi `xong_luc`. `ly_do`: chuỗi ⇒ đặt `ly_do_dung`; `None` ⇒ xoá về NULL (vd quay lại
    `running` không được mang lý do cũ "feed_rong"); bỏ trống ⇒ giữ nguyên.

    Chỉ nhận trạng thái kết thúc `failed` ở đây (`done` đi qua `finish_job`).
    """
    tu = (tu,) if isinstance(tu, str) else tuple(tu)
    sets, tham_so = ["trang_thai = ?"], [den]
    if den in _KET_THUC:
        sets.append("xong_luc = ?")
        tham_so.append(_now())
    else:
        sets.append("vao_trang_thai_luc = ?")
        tham_so.append(_now())
    if ly_do is not GIU_LY_DO:
        sets.append("ly_do_dung = ?")
        tham_so.append(ly_do)
    cho = ",".join("?" * len(tu))
    with _connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE id = ? AND trang_thai IN ({cho})",
            (*tham_so, job_id, *tu),
        )
        return cur.rowcount == 1


def yeu_cau_giai_ngay(db_path: Path, job_id: int) -> str:
    """"Tôi giải ngay": `cho_xac_minh` → `cho_giai`, tăng bộ đếm, trần `TRAN_GIAI_NGAY`.

    Một câu UPDATE: điều kiện trạng thái VÀ trần nằm trong WHERE nên hai lần bấm đua nhau không
    vượt trần. Trả "ok" | "het_luot" | "sai_trang_thai" | "khong_co" — rowcount 0 có ba nghĩa
    khác nhau và người dùng cần nghe ba câu khác nhau.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE jobs SET trang_thai = 'cho_giai', vao_trang_thai_luc = ?, "
            "so_lan_giai_ngay = so_lan_giai_ngay + 1 "
            "WHERE id = ? AND trang_thai = 'cho_xac_minh' AND so_lan_giai_ngay < ?",
            (_now(), job_id, gc.TRAN_GIAI_NGAY),
        )
        if cur.rowcount == 1:
            return "ok"
        row = conn.execute(
            "SELECT trang_thai, so_lan_giai_ngay FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    if row is None:
        return "khong_co"
    if row["trang_thai"] == "cho_xac_minh":
        return "het_luot"
    return "sai_trang_thai"


def giai_con_luot(job: dict) -> int:
    return max(0, gc.TRAN_GIAI_NGAY - int(job.get("so_lan_giai_ngay") or 0))


def vao_luc(db_path: Path, job_id: int) -> str | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT vao_trang_thai_luc FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row["vao_trang_thai_luc"] if row is not None else None


def quet_qua_han(db_path: Path, bay_gio: datetime | None = None) -> int:
    """`cho_xac_minh` quá `CHO_XAC_MINH_QUA_HAN_GIO` giờ ⇒ `failed` lý do `xac_minh_qua_han`.
    Trả số job đã đổi. Mốc đếm từ `vao_trang_thai_luc` (rơi về `bat_dau_luc`/`tao_luc` nếu NULL).
    Thư mục profile của job vừa `failed` do bộ quét mồ côi dọn ngay sau đó (cùng nhịp)."""
    gioi_han = ((bay_gio or datetime.now(timezone.utc))
                - timedelta(hours=gc.CHO_XAC_MINH_QUA_HAN_GIO)).isoformat(timespec="microseconds")
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE jobs SET trang_thai = 'failed', ly_do_dung = ?, xong_luc = ? "
            "WHERE trang_thai = 'cho_xac_minh' "
            "AND COALESCE(vao_trang_thai_luc, bat_dau_luc, tao_luc) < ?",
            (gc.LD_QUA_HAN, _now(), gioi_han),
        )
        return cur.rowcount
