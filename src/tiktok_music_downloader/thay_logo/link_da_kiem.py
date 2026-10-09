"""Sổ "id file Drive mà CHÍNH member này đã kiểm qua `POST /api/thay-logo/kiem-link`" (bảng `tl_link_kiem` trong `thay_logo_log.db`).

Vì sao có sổ: lượt Thay logo của member chỉ được dùng video trong thư viện của họ — TRỪ file/thư mục họ dán link vào. Nếu `POST /jobs` nhận
id thô bất kỳ thì ai biết một id Drive cũng lấy được bản copy video của người khác (tài khoản máy đọc được mọi thứ nó được chia sẻ). Bắt
buộc đi qua bước kiểm ⇒ có dấu vết ai đã thêm gì lúc nào, và mỗi id chỉ dùng được bởi đúng người đã kiểm, trong cửa sổ `CUA_SO_GIAY`.
"""
from __future__ import annotations

import time

CUA_SO_GIAY = 24 * 3600
_GIU_DONG_GIAY = 7 * 24 * 3600  # dọn dòng cũ hơn mức này mỗi lần ghi — bảng không phình mãi

SCHEMA = """
CREATE TABLE IF NOT EXISTS tl_link_kiem (
  email TEXT NOT NULL, file_id TEXT NOT NULL, luc REAL NOT NULL, PRIMARY KEY (email, file_id));
CREATE INDEX IF NOT EXISTS ix_tl_link_kiem_luc ON tl_link_kiem(luc);
"""


def khoi_tao(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def ghi_da_kiem(conn, email: str, file_ids: list[str], luc: float | None = None) -> None:
    """Ghi/làm mới mốc `luc` cho từng id (kiểm lại ⇒ cửa sổ 24 h tính lại)."""
    if not file_ids:
        return
    luc = time.time() if luc is None else luc
    conn.executemany("INSERT OR REPLACE INTO tl_link_kiem (email, file_id, luc) VALUES (?,?,?)", [(email, f, luc) for f in dict.fromkeys(file_ids)])
    conn.execute("DELETE FROM tl_link_kiem WHERE luc < ?", (luc - _GIU_DONG_GIAY,))
    conn.commit()


def con_han(conn, email: str, file_ids: list[str], bay_gio: float | None = None) -> set[str]:
    """Trong `file_ids`, những id CHÍNH `email` đã kiểm trong `CUA_SO_GIAY` gần nhất. Người khác kiểm ⇒ KHÔNG tính."""
    if not file_ids:
        return set()
    bay_gio = time.time() if bay_gio is None else bay_gio
    out: set[str] = set()
    for i in range(0, len(file_ids), 500):
        lo = file_ids[i:i + 500]
        out |= {r[0] for r in conn.execute(
            f"SELECT file_id FROM tl_link_kiem WHERE email = ? AND luc >= ? AND file_id IN ({','.join('?' * len(lo))})",
            [email, bay_gio - CUA_SO_GIAY, *lo])}
    return out
