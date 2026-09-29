"""Dọn ảnh thumb của video đã được dọn khỏi Drive — HỆ QUẢ của mốc `drive_don_luc`.

Ảnh sống ở `thumbs/<id>.webp` (poster) và `thumbs/khung/<id>-<phần trăm>.webp` (khung
phụ). Luật:
  * CHỈ xoá ảnh của video ĐÃ có `drive_don_luc` — không xoá lúc ẩn (7 ngày đầu còn
    ảnh để người dùng xem lại). Không có mốc riêng cho ảnh: lượt nào cũng dọn ảnh của
    video có `drive_don_luc` mà ảnh còn trên đĩa; xoá trượt ⇒ log, lượt sau thử lại,
    KHÔNG đảo mốc Drive.
  * KHÔNG xoá ảnh của video đang nằm trong một lượt chia CHƯA XONG (`video_cum_nhap` của
    `chia_lan` khác `da_duyet`/`huy`) — tầng hình còn cần.
  * So TÊN ĐẦY ĐỦ `<id>-<số>.webp`, không glob `<id>*`: xoá ảnh của `70` không được
    lấy nhầm ảnh của `7009`.
  * Chỉ động tới tệp ảnh. Không đụng hàng `videos` (né trùng còn nguyên).
  * Trần `toi_da` video mỗi lượt để một lượt không quét cả kho.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from web.models import _connect

log = logging.getLogger("videodl.web.vao_bo")

TOI_DA_VIDEO_MOI_LUOT = 100


@dataclass
class KetQuaThumbs:
    video_da_xu_ly: int = 0
    tep_da_xoa: int = 0
    tep_truot: int = 0


def _video_can_don_anh(db_path: Path) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT b.video_id FROM video_vao_bo b WHERE b.drive_don_luc IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM video_cum_nhap vcn "
            "                JOIN chia_lan cl ON cl.id = vcn.chia_lan_id "
            "                WHERE vcn.video_id = b.video_id "
            "                AND cl.trang_thai NOT IN ('da_duyet', 'huy')) "
            "ORDER BY b.drive_don_luc, b.video_id").fetchall()
    return [r["video_id"] for r in rows]


def don_thumbs(db_path: Path, thumbs_dir: Path, *,
               toi_da: int = TOI_DA_VIDEO_MOI_LUOT) -> KetQuaThumbs:
    kq = KetQuaThumbs()
    khung_dir = thumbs_dir / "khung"
    ten_khung = [p.name for p in khung_dir.iterdir()] if khung_dir.is_dir() else []
    for vid in _video_can_don_anh(db_path):
        if kq.video_da_xu_ly >= toi_da:
            break
        mau_khung = re.compile(re.escape(vid) + r"-\d+\.webp")
        tep = [thumbs_dir / f"{vid}.webp"] + [
            khung_dir / n for n in ten_khung if mau_khung.fullmatch(n)]
        con_lai = [p for p in tep if p.is_file()]
        if not con_lai:
            continue
        kq.video_da_xu_ly += 1
        for p in con_lai:
            try:
                p.unlink()
                kq.tep_da_xoa += 1
            except OSError as exc:
                kq.tep_truot += 1
                log.warning("không xoá được ảnh %s (%s) — lượt sau thử lại", p.name,
                            type(exc).__name__)
    return kq
