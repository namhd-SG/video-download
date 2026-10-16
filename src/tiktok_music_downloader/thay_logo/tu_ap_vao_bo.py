"""Tự trả video Đạt về BỘ GỐC (USER CHỐT 16/10: "Sau khi tôi bấm Đạt" + "Chấp nhận (5 phút)") — lớp lịch trên `ap_vao_bo`.

Worker gọi `thu_tu_ap` ở ĐẦU mỗi vòng (trước cổng đĩa / nhường lane tải: việc này chỉ gọi Drive, không tốn CPU). Một lượt "Đã vào bộ"
được tự áp khi ĐỦ cả bốn điều kiện (chốt L1 của agy R2b, `~/agy-ws/exchange/ux-thay-logo-R2b-agy.md`):
  1. lượt CHƯA TỪNG có dòng `tl_ap_bo` — người dùng đã áp tay hay đã Hoàn tác thì máy KHÔNG tự áp lại (Hoàn tác phải có hiệu lực);
  2. MỌI video của lượt đã kết thúc: `cho_nguoi` / `loi`, hoặc `xong` VÀ đã chấm;
  3. có ít nhất một video `xong` mà lần chấm MỚI NHẤT là Đạt;
  4. đã qua `CHO_GIAY` kể từ mốc cuối = max(lần chấm mới nhất, lần cập nhật video mới nhất) — cửa sổ sửa chấm nhầm trước khi bản mới
     vào bộ đang chạy quảng cáo; tính cả cập nhật video để video cuối kết thúc muộn vẫn được 5 phút sau khi lượt xong.
Lỗi TẠM (bộ đang khoá 409, jobs.db 503) ⇒ vòng sau thử lại (lượt vẫn thoả điều kiện 1). Lỗi CỐ ĐỊNH (403 sai chủ — vd admin tạo lượt hộ;
409 không còn gì để áp) ⇒ ghi log MỘT lần và bỏ qua lượt đó tới khi worker khởi động lại; người dùng vẫn có nút áp tay trên thẻ.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from tiktok_music_downloader.thay_logo import ap_vao_bo

log = logging.getLogger(__name__)

CHO_GIAY = 300  # 5 phút — USER CHỐT 16/10 "Chấp nhận (5 phút)" (pane lane UX 90519 ttys000)

# Lượt "Đã vào bộ": cột `nguon` là JSON `sort_keys=True` (`hang_doi.tao_job`) ⇒ chuỗi `"kieu": "vao_bo"` có khuôn cố định. Dùng
# `instr`, không `LIKE` (`_` trong "vao_bo" là ký tự đại diện của LIKE).
_SQL_UNG_VIEN = """
SELECT j.id AS job_id, j.nguoi_tao,
       -- `max(a, b)` HAI tham số là hàm THƯỜNG (theo dòng) ⇒ bọc `max(...)` MỘT tham số bên ngoài để gộp trên MỌI video của lượt.
       max(max(coalesce((SELECT max(d.luc) FROM tl_danh_gia d WHERE d.video_id = v.video_log_id), 0), v.cap_nhat_luc)) AS moc
FROM tl_job j JOIN tl_job_video v ON v.job_id = j.id
WHERE NOT EXISTS (SELECT 1 FROM tl_ap_bo a WHERE a.job_id = j.id)
GROUP BY j.id
HAVING sum(instr(v.nguon, '"kieu": "vao_bo"') > 0) > 0
   AND sum(v.trang_thai IN ('cho', 'cho_agy', 'dang_chay')) = 0
   AND sum(v.trang_thai = 'xong' AND (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id ORDER BY luc DESC LIMIT 1) IS NULL) = 0
   AND sum(v.trang_thai = 'xong' AND (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id ORDER BY luc DESC LIMIT 1) = 'dat') > 0
"""


def moc_cac_luot(conn) -> dict[int, tuple[str, float]]:
    """{job_id: (chủ lượt, mốc cuối)} của các lượt thoả điều kiện 1–3 (chưa xét cửa sổ chờ). Chỉ đọc DB."""
    ap_vao_bo.khoi_tao(conn)
    return {r["job_id"]: (r["nguoi_tao"], float(r["moc"] or 0)) for r in conn.execute(_SQL_UNG_VIEN)}


def luot_den_han(conn, bay_gio: float, cho: float = CHO_GIAY) -> list[tuple[int, str]]:
    """Các lượt đủ cả bốn điều kiện tại `bay_gio` — [(job_id, chủ lượt)], cũ trước."""
    return [(j, chu) for j, (chu, moc) in sorted(moc_cac_luot(conn).items()) if bay_gio - moc >= cho]


def thu_tu_ap(conn, chu_cua: Callable[[list[str]], dict], khoi_chay: Callable[[int], object], bo_qua: set[int],
              bay_gio: float | None = None, cho: float = CHO_GIAY) -> list[int]:
    """Đặt lịch áp (ghi chiều ý định + khoá bộ trong `dat_lich_ap`) rồi `khoi_chay(job_id)` cho từng lượt đến hạn. Trả các job đã khởi
    chạy. `bo_qua`: tập (của worker) các lượt lỗi CỐ ĐỊNH đã báo — không thử lại mỗi vòng. Không ném: lỗi một lượt không chặn lượt khác."""
    da_chay: list[int] = []
    for job_id, chu in luot_den_han(conn, time.time() if bay_gio is None else bay_gio, cho):
        if job_id in bo_qua:
            continue
        try:
            ap_vao_bo.dat_lich_ap(conn, job_id, chu, chu_cua)
        except ap_vao_bo.LoiAp as e:
            if e.ma == 403 or (e.ma == 409 and "đang có một lượt áp" not in str(e)):
                bo_qua.add(job_id)  # cố định: sai chủ / không còn gì để áp — nút áp tay trên thẻ vẫn còn
                log.info("thay logo tự áp: bỏ qua lượt %s (%s %s)", job_id, e.ma, e)
            else:
                log.info("thay logo tự áp: lượt %s chưa áp được lúc này (%s) — vòng sau thử lại", job_id, e.ma)
            continue
        try:
            khoi_chay(job_id)
        except Exception:  # thread không khởi được ⇒ nhả khoá; chiều ý định đã ghi ⇒ `quet_do_dang` / nút "Tiếp tục" chạy tiếp
            log.exception("thay logo tự áp: không khởi chạy được lượt %s", job_id)
            ap_vao_bo.nha_khoa(conn, job_id)
            continue
        log.info("thay logo tự áp: đã đặt lịch trả lượt %s về bộ gốc", job_id)
        da_chay.append(job_id)
    return da_chay
