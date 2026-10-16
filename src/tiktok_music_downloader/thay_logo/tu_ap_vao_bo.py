"""Tự trả video Đạt về BỘ GỐC (USER CHỐT 16/10: "Sau khi tôi bấm Đạt" + "Chấp nhận (5 phút)") — lớp lịch trên `ap_vao_bo`.

Worker gọi `thu_tu_ap` ở ĐẦU mỗi vòng (trước cổng đĩa / nhường lane tải: việc này chỉ gọi Drive, không tốn CPU). Một lượt "Đã vào bộ"
được tự áp khi ĐỦ mọi điều kiện (chốt L1 agy R2b + review độc lập PR2):
  0. lượt TẠO SAU lúc tính năng chạy lần đầu (`tl_tu_ap_moc.bat_dau`) — bật cờ KHÔNG được tự áp hàng loạt lượt cũ mà người dùng có thể
     đã cố ý để yên;
  1. lượt CHƯA TỪNG được xét: không có dòng `tl_tu_ap_da_xet` (máy đã tự áp / người dùng đã áp tay / Hoàn tác / lỗi cố định) VÀ không có
     dòng `tl_ap_bo` mang job này. Mốc `tl_tu_ap_da_xet` theo LƯỢT và không bao giờ dời: dòng `tl_ap_bo` thì CÓ THỂ dời sang lượt khác
     (UNIQUE theo bản trong bộ, nhánh "dùng lại" ghi đè `job_id`) — chỉ dựa vào nó thì một lượt cũ đã Hoàn tác có thể "trông như chưa áp"
     và bị máy áp lại;
  2. MỌI video của lượt đã kết thúc: `cho_nguoi` / `loi`, hoặc `xong` VÀ đã chấm;
  3. có ít nhất một video `xong` mà lần chấm MỚI NHẤT là Đạt;
  4. đã qua `CHO_GIAY` kể từ mốc cuối = max(lần chấm mới nhất, lần cập nhật video mới nhất) — cửa sổ sửa chấm nhầm trước khi bản mới vào
     bộ đang chạy quảng cáo.
Lỗi TẠM (`LoiAp.tam`: bộ đang khoá, hoàn tác/hàng của lượt khác đang dở; 503; hoặc lỗi bất ngờ như sqlite bận) ⇒ vòng sau thử lại. Lỗi CỐ
ĐỊNH (sai chủ — vd admin tạo lượt hộ; không còn gì để áp) ⇒ ghi mốc `tl_tu_ap_da_xet` (bền qua khởi động lại) — người dùng vẫn có nút áp tay.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterable

from tiktok_music_downloader.thay_logo import ap_vao_bo

log = logging.getLogger(__name__)

CHO_GIAY = 300  # 5 phút — USER CHỐT 16/10 "Chấp nhận (5 phút)" (pane lane UX 90519 ttys000)

SCHEMA = """
CREATE TABLE IF NOT EXISTS tl_tu_ap_da_xet (job_id INTEGER PRIMARY KEY, luc REAL NOT NULL, ly_do TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tl_tu_ap_moc (khoa TEXT PRIMARY KEY, gia_tri REAL NOT NULL);
"""

# Lượt "Đã vào bộ": cột `nguon` là JSON `sort_keys=True` (`hang_doi.tao_job`) ⇒ chuỗi `"kieu": "vao_bo"` có khuôn cố định. Dùng
# `instr`, không `LIKE` (`_` trong "vao_bo" là ký tự đại diện của LIKE).
_SQL_UNG_VIEN = """
SELECT j.id AS job_id, j.nguoi_tao,
       -- `max(a, b)` HAI tham số là hàm THƯỜNG (theo dòng) ⇒ bọc `max(...)` MỘT tham số bên ngoài để gộp trên MỌI video của lượt.
       max(max(coalesce((SELECT max(d.luc) FROM tl_danh_gia d WHERE d.video_id = v.video_log_id), 0), v.cap_nhat_luc)) AS moc
FROM tl_job j JOIN tl_job_video v ON v.job_id = j.id
WHERE j.tao_luc >= (SELECT gia_tri FROM tl_tu_ap_moc WHERE khoa = 'bat_dau')
  AND NOT EXISTS (SELECT 1 FROM tl_tu_ap_da_xet x WHERE x.job_id = j.id)
  AND NOT EXISTS (SELECT 1 FROM tl_ap_bo a WHERE a.job_id = j.id){loc_job}
GROUP BY j.id
HAVING sum(instr(v.nguon, '"kieu": "vao_bo"') > 0) > 0
   AND sum(v.trang_thai IN ('cho', 'cho_agy', 'dang_chay')) = 0
   AND sum(v.trang_thai = 'xong' AND (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id ORDER BY luc DESC LIMIT 1) IS NULL) = 0
   AND sum(v.trang_thai = 'xong' AND (SELECT ket_qua FROM tl_danh_gia d WHERE d.video_id = v.video_log_id ORDER BY luc DESC LIMIT 1) = 'dat') > 0
"""


def khoi_tao(conn) -> None:
    """Bảng của lớp tự áp (+ bảng `ap_vao_bo`). Lần đầu chạy ghi mốc `bat_dau` = bây giờ (chỉ lượt tạo sau mốc này được tự áp)."""
    ap_vao_bo.khoi_tao(conn)
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO tl_tu_ap_moc (khoa, gia_tri) VALUES ('bat_dau', ?)", (time.time(),))
    conn.commit()


def danh_dau(conn, job_id: int, ly_do: str) -> None:
    """Lượt `job_id` đã được xét — máy KHÔNG BAO GIỜ tự áp nó nữa (áp tay / hoàn tác / máy đã tự áp / lỗi cố định)."""
    khoi_tao(conn)
    conn.execute("INSERT OR IGNORE INTO tl_tu_ap_da_xet (job_id, luc, ly_do) VALUES (?,?,?)", (job_id, time.time(), ly_do[:200]))
    conn.commit()


def moc_cac_luot(conn, job_ids: Iterable[int] | None = None) -> dict[int, tuple[str, float]]:
    """{job_id: (chủ lượt, mốc cuối)} của các lượt thoả điều kiện 0–3 (chưa xét cửa sổ chờ). `job_ids` giới hạn tập xét (route /bo chỉ
    hỏi các lượt nó đang trả). Chỉ đọc DB (ngoài `khoi_tao`)."""
    khoi_tao(conn)
    ids = None if job_ids is None else list(job_ids)
    loc = "" if ids is None else f"\n  AND j.id IN ({','.join('?' * len(ids))})"
    return {r["job_id"]: (r["nguoi_tao"], float(r["moc"] or 0))
            for r in conn.execute(_SQL_UNG_VIEN.format(loc_job=loc), ids or [])}


def luot_den_han(conn, bay_gio: float, cho: float | None = None) -> list[tuple[int, str]]:
    """Các lượt đủ mọi điều kiện tại `bay_gio` — [(job_id, chủ lượt)], cũ trước. `cho` mặc định = `CHO_GIAY` đọc LÚC GỌI."""
    cho = CHO_GIAY if cho is None else cho
    return [(j, chu) for j, (chu, moc) in sorted(moc_cac_luot(conn).items()) if bay_gio - moc >= cho]


def thu_tu_ap(conn, chu_cua: Callable[[list[str]], dict], khoi_chay: Callable[[int], object],
              bay_gio: float | None = None, cho: float | None = None) -> list[int]:
    """Đặt lịch áp (`dat_lich_ap`: chiều ý định + khoá bộ trong một giao dịch) rồi `khoi_chay(job_id)` cho từng lượt đến hạn. Trả các job
    đã khởi chạy. Không ném: lỗi của một lượt (kể cả lỗi bất ngờ) chỉ ghi log và không chặn lượt khác."""
    da_chay: list[int] = []
    for job_id, chu in luot_den_han(conn, time.time() if bay_gio is None else bay_gio, cho):
        try:
            ap_vao_bo.dat_lich_ap(conn, job_id, chu, chu_cua)
        except ap_vao_bo.LoiAp as e:
            if e.tam or e.ma == 503:
                log.info("thay logo tự áp: lượt %s chưa áp được lúc này (%s) — vòng sau thử lại", job_id, e.ma)
            else:  # cố định: sai chủ / không còn gì để áp — không thử lại (kể cả sau khởi động lại); nút áp tay trên thẻ vẫn còn
                danh_dau(conn, job_id, f"loi {e.ma}: {e}")
                log.info("thay logo tự áp: bỏ qua lượt %s (%s %s)", job_id, e.ma, e)
            continue
        except Exception:  # sqlite bận, Drive adapter hỏng… ⇒ lỗi tạm, vòng sau thử lại
            log.exception("thay logo tự áp: lượt %s lỗi bất ngờ — vòng sau thử lại", job_id)
            continue
        danh_dau(conn, job_id, "tu_ap")  # đã có chiều ý định trong tl_ap_bo; mốc này giữ lượt KHÔNG bị tự áp lại sau Hoàn tác
        try:
            khoi_chay(job_id)
        except Exception:  # thread không khởi được ⇒ nhả khoá; chiều ý định đã ghi ⇒ `quet_do_dang` / nút "Tiếp tục" chạy tiếp
            log.exception("thay logo tự áp: không khởi chạy được lượt %s", job_id)
            ap_vao_bo.nha_khoa(conn, job_id)
            continue
        log.info("thay logo tự áp: đã đặt lịch trả lượt %s về bộ gốc", job_id)
        da_chay.append(job_id)
    return da_chay
