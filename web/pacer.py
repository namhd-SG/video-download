"""Bộ điều tốc IP toàn hệ thống cho lane nền tảng khác (link lẻ qua yt-dlp).

Vì sao theo IP chứ không theo người: Video Desk, Promax và máy văn phòng ra Internet CÙNG một IP. Nền tảng gắn
cờ IP đó thì mọi người chịu chung, nên trần ở đây đếm lượt của MỌI job trên một nền tảng, không phân biệt ai tạo.

Ba thứ sống trong `jobs.db` (không trong RAM — tiến trình chết/khởi động lại không được xoá sổ đếm):

  * `luot_tai(nen_tang, luc, job_id)` — mỗi lời gọi tới nền tảng (liệt kê VÀ tải, kể cả lần thử lại) là MỘT
    hàng, ghi TRƯỚC khi gọi và đếm cả lượt lỗi. Đây là ngoại lệ CÓ CHỦ ĐÍCH của luật "mốc ghi SAU việc nó khẳng
    định": bộ canh IP hỏng nguy hiểm ở chiều ĐẾM THIẾU (tiến trình chết giữa lời gọi mà sổ chưa có hàng nào ⇒
    nền tảng đã bị gọi mà ta không biết). Đếm dư một lượt chỉ làm trần đến sớm hơn một nhịp.
  * `nen_tang_tat(nen_tang, luc, ly_do)` — nền tảng đang bị TẮT sau tín hiệu chặn. Không tự bật lại theo giờ:
    chỉ admin bật (`bat_lai`). Mốc này ghi SAU khi đã thấy tín hiệu chặn (không phải trước).
  * Cửa sổ giờ trượt 60 phút; "ngày" tính theo giờ VN (như trần ngày TikTok), cùng hàm `vn_day_start_utc`.

Chạm trần giờ ⇒ job DỪNG với `tran_gio` (không ngủ giữ lane: một job YouTube ngủ 1 giờ sẽ chặn mọi job Instagram/
Facebook/Drive đứng sau nó). Lane nhận job dùng `nen_tang_loai_tru` để bỏ qua nền tảng đang tắt/hết trần.
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tiktok_music_downloader.nguon import NEN_TANG_LINK_LE, nen_tang_bat
from tiktok_music_downloader.phan_loai_loi import phat_hien_chan
from tiktok_music_downloader.utils import STOP_BI_CHAN, STOP_TRAN_GIO, STOP_TRAN_NGAY
from web import models
from web.lifecycle import vn_day_start_utc

log = logging.getLogger("videodl.web")

# (lượt/giờ, lượt/ngày) — MỘT chỗ duy nhất. Số khởi điểm bảo thủ, CHƯA có số đo nền: YouTube =
# 1/5 mức khách ẩn danh (~300/giờ); nền tảng khác chưa có số riêng nên dùng mức thấp hơn. Chỉ NỚI sau ≥7 ngày
# smoke không gặp tín hiệu chặn, mỗi lần nới phải qua phản biện. Một video tốn ≥2 lượt (liệt kê + tải).
TRAN_YOUTUBE = (60, 300)
TRAN_KHAC = (30, 100)
# TikTok KHÔNG nằm đây: lane TikTok y nguyên, có trần ngày theo cookie riêng của nó.
TRAN: dict[str, tuple[int, int]] = {
    nt: (TRAN_YOUTUBE if nt == "youtube" else TRAN_KHAC)
    for nt in sorted(NEN_TANG_LINK_LE - {"tiktok"})
}
# Nghỉ giữa hai lời gọi liên tiếp của cùng một job (giây, thấp–cao). Ngủ NGẮN trong job là chấp nhận được; ngủ chờ
# cửa sổ trần giờ thì không (xem docstring đầu file).
NGHI_GIUA_LUOT = (10.0, 20.0)
CUA_SO_GIO = timedelta(hours=1)


def bay_gio() -> datetime:
    """Đồng hồ của pacer. Test thay hàm này (hoặc truyền `now=`) thay vì chờ thật."""
    return datetime.now(timezone.utc)


def nghi_giua_luot() -> None:
    """Ngủ ngắn giữa hai lời gọi liên tiếp của một job (jitter, không đều đặn)."""
    time.sleep(random.uniform(*NGHI_GIUA_LUOT))


def _iso(dt: datetime) -> str:
    """Dạng chuỗi của `models._now()` — so sánh được như TEXT với `luc`."""
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _dem_tu(conn, nen_tang: str, tu: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM luot_tai WHERE nen_tang = ? AND luc >= ?",
                        (nen_tang, tu)).fetchone()[0]


def ghi_truoc_khi_goi(db_path: Path, nen_tang: str, job_id: int | None,
                      now: datetime | None = None) -> str | None:
    """Xin phép MỘT lời gọi tới `nen_tang`. Trả None = được phép VÀ lượt đã ghi vào sổ (trước khi gọi);
    trả mã (`bi_chan` / `tran_ngay` / `tran_gio`) = từ chối, KHÔNG ghi gì.

    Kiểm và ghi nằm trong MỘT giao dịch `BEGIN IMMEDIATE`: hai luồng cùng xin không cùng đọc "còn 1 lượt"."""
    gio, ngay = TRAN[nen_tang]
    now = now or bay_gio()
    with models._connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM nen_tang_tat WHERE nen_tang = ?", (nen_tang,)).fetchone():
            conn.execute("ROLLBACK")
            return STOP_BI_CHAN
        if _dem_tu(conn, nen_tang, vn_day_start_utc(now)) >= ngay:
            conn.execute("ROLLBACK")
            return STOP_TRAN_NGAY
        if _dem_tu(conn, nen_tang, _iso(now - CUA_SO_GIO)) >= gio:
            conn.execute("ROLLBACK")
            return STOP_TRAN_GIO
        conn.execute("INSERT INTO luot_tai (nen_tang, luc, job_id) VALUES (?, ?, ?)",
                     (nen_tang, _iso(now), job_id))
    return None


def tat_nen_tang(db_path: Path, nen_tang: str, ly_do: str, now: datetime | None = None) -> bool:
    """Tắt `nen_tang` (giữ NGUYÊN mốc đầu nếu đã tắt). Trả True nếu vừa tắt lần này."""
    with models._connect(db_path) as conn:
        cur = conn.execute("INSERT OR IGNORE INTO nen_tang_tat (nen_tang, luc, ly_do) VALUES (?, ?, ?)",
                           (nen_tang, _iso(now or bay_gio()), ly_do))
        return cur.rowcount == 1


def bat_lai(db_path: Path, nen_tang: str) -> bool:
    """Bật lại `nen_tang` (admin). Trả True nếu nó đang tắt."""
    with models._connect(db_path) as conn:
        return conn.execute("DELETE FROM nen_tang_tat WHERE nen_tang = ?", (nen_tang,)).rowcount == 1


def nen_tang_dang_tat(db_path: Path) -> dict[str, dict]:
    """`{nen_tang: {"luc": …, "ly_do": …}}` cho các nền tảng đang tắt (badge quản trị)."""
    with models._connect(db_path) as conn:
        return {r["nen_tang"]: {"luc": r["luc"], "ly_do": r["ly_do"]}
                for r in conn.execute("SELECT nen_tang, luc, ly_do FROM nen_tang_tat ORDER BY nen_tang")}


def nen_tang_loai_tru(db_path: Path, now: datetime | None = None) -> tuple[str, ...]:
    """Nền tảng lane nhận job PHẢI bỏ qua: TẮT (bị chặn) ∪ hết trần GIỜ ∪ hết trần NGÀY, cộng nền tảng không nằm
    trong cấu hình `VIDEODL_NEN_TANG_BAT` (tắt bằng cấu hình thì job đã xếp hàng cũng không được chạy).
    Gọi MỖI vòng nhận job: hai câu đếm có chỉ mục, không ghi gì."""
    now = now or bay_gio()
    bat = nen_tang_bat()
    ra = {nt for nt in TRAN if nt not in bat}
    with models._connect(db_path) as conn:
        ra |= {r[0] for r in conn.execute("SELECT nen_tang FROM nen_tang_tat")}
        ngay = dict(conn.execute("SELECT nen_tang, COUNT(*) FROM luot_tai WHERE luc >= ? GROUP BY nen_tang",
                                 (vn_day_start_utc(now),)).fetchall())
        gio = dict(conn.execute("SELECT nen_tang, COUNT(*) FROM luot_tai WHERE luc >= ? GROUP BY nen_tang",
                                (_iso(now - CUA_SO_GIO),)).fetchall())
    for nt, (tran_gio, tran_ngay) in TRAN.items():
        if gio.get(nt, 0) >= tran_gio or ngay.get(nt, 0) >= tran_ngay:
            ra.add(nt)
    return tuple(sorted(ra))


class CongNenTang:
    """Cổng của MỘT job trên MỘT nền tảng, đưa cho bước liệt kê và bước tải (`nguon.LinkLe.liet_ke`,
    `downloader.download_all`) để mọi lời gọi tới nền tảng đi qua cùng một chỗ.

    `ly_do_dung`: lý do đầu tiên khiến cổng bảo job dừng (None = chưa dừng); `process_job` đọc nó sau khi bước
    liệt kê/tải trả về để ghi lý do dừng và kết thúc job."""

    def __init__(self, db_path: Path, job_id: int | None, nen_tang: str):
        if nen_tang not in TRAN:
            raise ValueError(f"nền tảng không có bộ điều tốc: {nen_tang!r}")
        self._db_path = db_path
        self._job_id = job_id
        self._nen_tang = nen_tang
        self.ly_do_dung: str | None = None

    def truoc_goi(self) -> str | None:
        """Gọi NGAY TRƯỚC mỗi lời gọi nền tảng. None = được gọi (lượt đã ghi); mã = dừng."""
        ly_do = ghi_truoc_khi_goi(self._db_path, self._nen_tang, self._job_id)
        if ly_do and self.ly_do_dung is None:
            self.ly_do_dung = ly_do
        return ly_do

    def xu_ly_loi(self, exc: BaseException) -> str | None:
        """Lỗi vừa nổ có phải TÍN HIỆU CHẶN không (`phan_loai_loi.phat_hien_chan`)? Phải ⇒ tắt nền tảng và trả
        `bi_chan`. Không phải (kể cả "sign in" của video riêng tư) ⇒ None: chỉ là lỗi của video."""
        ma = phat_hien_chan(exc)
        if ma is None:
            return None
        if tat_nen_tang(self._db_path, self._nen_tang, ma):
            log.warning("nền tảng %s bị chặn (%s): tạm tắt cho tới khi admin bật lại", self._nen_tang, ma)
        if self.ly_do_dung is None:
            self.ly_do_dung = STOP_BI_CHAN
        return STOP_BI_CHAN
