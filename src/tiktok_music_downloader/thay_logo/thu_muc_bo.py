"""Thư mục đầu ra THEO BỘ: `<ten_bo> (#<job_id>)` dưới thư mục đầu ra gốc trên Shared Drive.

Id thư mục lưu ở `tl_job.thu_muc_ra_id` ⇒ các video của cùng bộ luôn vào MỘT thư mục, kể cả sau khi khởi động lại. Chưa có id thì
tìm theo tên trong thư mục gốc (phòng lượt tạo trước đó đã tạo được nhưng chưa kịp ghi id), không thấy mới tạo.

Drive đi qua `drive_tl.DriveTL` (test thay bằng bản giả) — module này KHÔNG tự gọi mạng.
"""
from __future__ import annotations

import logging

from tiktok_music_downloader.thay_logo.drive_tl import DriveTL, DriveTLKhongThay

log = logging.getLogger(__name__)


class CongCreativeCam(RuntimeError):
    """Thư mục ra nằm trong cây `Creative`: KHÔNG tạo thư mục bộ mới (video bị đánh `loi`, worker bị đặt về CẤM)."""


def ten_thu_muc(job_id: int, ten_bo: str | None) -> str:
    """Tên thư mục trên Drive. Bỏ ký tự điều khiển; tên bộ rỗng (job cũ) ⇒ `Lượt #<id>`."""
    sach = "".join(c for c in (ten_bo or "") if c.isprintable()).strip()
    return f"{sach or f'Lượt #{job_id}'} (#{job_id})"


def _con_dung_duoc(drive: DriveTL, fid: str, goc_id: str) -> bool:
    """Id đã lưu còn là thư mục sống và còn nằm dưới thư mục ra? Lỗi Drive khác 404 ném lên (chưa đo được ≠ đã mất)."""
    try:
        m = drive.lay_muc(fid)
    except DriveTLKhongThay:
        return False
    return not m.get("trashed") and goc_id in (m.get("parents") or [])


def tim_hoac_tao(conn, job_id: int, goc_id: str, drive: DriveTL, kiem_creative=None) -> str:
    """Trả id thư mục đầu ra của bộ `job_id`; lỗi Drive ⇒ ném lên (worker đánh video `loi`, không im lặng đổ vào thư mục gốc).
    `kiem_creative() -> str | None` (cùng hàm cổng Creative) chạy MỖI KHI sắp tạo thư mục bộ mới: có lý do ⇒ `CongCreativeCam`;
    nó ném (Drive lỗi tạm) ⇒ ném nguyên, không tạo/không upload lượt này."""
    r = conn.execute("SELECT ten_bo, thu_muc_ra_id FROM tl_job WHERE id=?", (job_id,)).fetchone()
    if r is None:
        raise LookupError(f"không có job {job_id}")
    if r["thu_muc_ra_id"]:
        if _con_dung_duoc(drive, r["thu_muc_ra_id"], goc_id):
            return r["thu_muc_ra_id"]
        log.warning("thay logo: thư mục bộ %s (job %s) đã bị xoá/thùng rác/dời khỏi thư mục ra — tạo lại", r["thu_muc_ra_id"], job_id)
        conn.execute("UPDATE tl_job SET thu_muc_ra_id=NULL WHERE id=?", (job_id,))
        conn.commit()
    if kiem_creative is not None:
        ly_do = kiem_creative()
        if ly_do:
            raise CongCreativeCam(ly_do)
    ten = ten_thu_muc(job_id, r["ten_bo"])
    co = drive.tim_con_theo_ten(goc_id, ten)
    fid = co[0]["id"] if co else drive.tao_thu_muc(ten, goc_id)
    # Ghi mốc SAU khi thư mục đã chắc chắn tồn tại (không ghi trước rồi mới tạo).
    conn.execute("UPDATE tl_job SET thu_muc_ra_id=? WHERE id=?", (fid, job_id))
    conn.commit()
    return fid
