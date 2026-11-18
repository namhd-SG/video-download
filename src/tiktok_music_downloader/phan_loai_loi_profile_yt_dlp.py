"""Phân loại lỗi đường yt-dlp liệt kê TikTok `@profile` thành NHÃN TĨNH cho log (R-09 #2, agy R1b ĐK-R09-2/3).

Nhãn là tập đóng, không bao giờ chứa thông điệp gốc (thông điệp yt-dlp có URL/handle khách) ⇒ đếm phân bố trên
ca-n bằng 1 grep `profile yt-dlp:`.

Ba tầng bóc lỗi của yt-dlp 2026.08.19:
  (i)  `ydl.extract_info` bọc mọi `ExtractorError` thành `DownloadError(msg, exc_info)`; lỗi mạng gốc
       (`HTTPError` có `.status`, `TransportError`) nằm ở `exc_info[1].cause`. `next(it)` (trang `item_list`)
       ném thẳng `ExtractorError` có `.cause`. ⇒ `chuoi_loi` duyệt cả chuỗi.
  (ii) Lỗi `next(it)` khi chưa có mục hợp lệ là lỗi trang ĐẦU, không phải "giữa chừng" — do người gọi phân biệt.
  (iii) `TikTokUserIE` lấy `secUid` qua 3 trang với `fatal=False`: 403/429/timeout chỉ thành WARNING rồi ném chung
       "Unable to extract secondary user ID" (`cause=None`). ⇒ `LogBatCo` ghi cờ từ warning để phân loại ca này.
"""
from __future__ import annotations

import socket

from yt_dlp.networking.exceptions import HTTPError, TransportError

from tiktok_music_downloader import downloader

# Tập nhãn đóng `loi=` (agy R1b ĐK-R09-3).
LOI_KHONG = "khong"
LOI_RONG_ITEM_LIST = "rong_item_list"
LOI_HTTP_403 = "http_403"
LOI_HTTP_429 = "http_429"
LOI_HTTP_KHAC = "http_khac"
LOI_TIMEOUT = "timeout"
LOI_KHONG_SECUID = "khong_secuid"
LOI_TK_RIENG_TU = "tk_rieng_tu"
LOI_TK_KHONG_VIDEO = "tk_khong_video"
LOI_LAP_TRANG = "lap_trang"
LOI_KHAC = "khac"

TAP_NHAN_LOI = frozenset({
    LOI_KHONG, LOI_RONG_ITEM_LIST, LOI_HTTP_403, LOI_HTTP_429, LOI_HTTP_KHAC, LOI_TIMEOUT,
    LOI_KHONG_SECUID, LOI_TK_RIENG_TU, LOI_TK_KHONG_VIDEO, LOI_LAP_TRANG, LOI_KHAC,
})

_MAU_KHONG_SECUID = "unable to extract secondary user id"
_MAU_RIENG_TU = ("account is private", "likely either private")
_MAU_KHONG_VIDEO = "does not have any videos posted"
_MAU_LAP_TRANG = "keeps sending the same page"
_MAU_TIMEOUT = ("timed out", "curl: (28)")
_MAU_403 = "http error 403"
_MAU_429 = ("http error 429", "too many requests")


def _co_mau(chuoi: str, mau: str | tuple[str, ...]) -> bool:
    return any(m in chuoi for m in ((mau,) if isinstance(mau, str) else mau))


class LogBatCo(downloader._YtdlpLog):
    """Đích log yt-dlp như `_YtdlpLog` (mọi mức xuống DEBUG) + ghi cờ 403/429/timeout từ WARNING `fatal=False`.
    Mỗi lượt liệt kê dùng MỘT instance mới (cờ không được rò giữa các lượt)."""

    def __init__(self) -> None:
        self.co_403 = False
        self.co_429 = False
        self.co_timeout = False

    def warning(self, msg: str) -> None:
        thap = str(msg).lower()
        if _MAU_403 in thap:
            self.co_403 = True
        if _co_mau(thap, _MAU_429):
            self.co_429 = True
        if _co_mau(thap, _MAU_TIMEOUT):
            self.co_timeout = True
        super().warning(msg)


def chuoi_loi(exc: BaseException) -> list[BaseException]:
    """Chuỗi lỗi: `exc` → `DownloadError.exc_info[1]` / `ExtractorError.cause` / `__cause__`, không lặp, ≤ 8 mắt."""
    ra: list[BaseException] = []
    hang: list[BaseException | None] = [exc]
    while hang and len(ra) < 8:
        e = hang.pop(0)
        if e is None or not isinstance(e, BaseException) or any(e is x for x in ra):
            continue
        ra.append(e)
        exc_info = getattr(e, "exc_info", None)
        if isinstance(exc_info, tuple) and len(exc_info) >= 2:
            hang.append(exc_info[1])
        hang.append(getattr(e, "cause", None))
        hang.append(e.__cause__)
    return ra


def phan_loai(exc: BaseException, co: LogBatCo | None = None) -> str:
    """Nhãn tĩnh cho lỗi `exc` của 1 lượt liệt kê; `co` = cờ warning của lượt đó (tầng iii)."""
    chuoi = chuoi_loi(exc)
    for e in chuoi:
        if isinstance(e, HTTPError):
            status = getattr(e, "status", None)
            if status == 403:
                return LOI_HTTP_403
            if status == 429:
                return LOI_HTTP_429
            return LOI_HTTP_KHAC
    van_ban = " | ".join(str(e).lower() for e in chuoi)
    if _MAU_KHONG_SECUID in van_ban:
        if co is not None:
            if co.co_429:
                return LOI_HTTP_429
            if co.co_timeout:
                return LOI_TIMEOUT
            if co.co_403:
                return LOI_HTTP_403
        return LOI_KHONG_SECUID
    if _co_mau(van_ban, _MAU_RIENG_TU):
        return LOI_TK_RIENG_TU
    if _MAU_KHONG_VIDEO in van_ban:
        return LOI_TK_KHONG_VIDEO
    if _MAU_LAP_TRANG in van_ban:
        return LOI_LAP_TRANG
    if any(isinstance(e, (TransportError, TimeoutError, socket.timeout)) for e in chuoi):
        return LOI_TIMEOUT
    if _co_mau(van_ban, _MAU_TIMEOUT):
        return LOI_TIMEOUT
    if _co_mau(van_ban, _MAU_429):
        return LOI_HTTP_429
    if _MAU_403 in van_ban:
        return LOI_HTTP_403
    return LOI_KHAC
