"""Liệt kê video trang TikTok `@profile` qua yt-dlp (`TikTokUserIE`, không trình duyệt, không cookie).

Trên trình duyệt (cả headless lẫn headful), `/api/post/item_list` trả HTTP 200 thân 0 byte trước khi
hộp captcha hiện ra. Trong khi đó `TikTokUserIE` của yt-dlp lấy `secUid` rồi gọi `/api/creator/item_list/`
(`count=15`) không cần cookie.

Hàm `liet_ke_profile_yt_dlp` mở một phiên `YoutubeDL` với `extract_info(download=False, process=False)`
và duyệt LƯỜI generator `entries` ngay TRONG khối `with`:
  - Lọc trùng trong lượt chạy và lọc `already_have` trên từng mục (gọi `on_skip` cho mục đã có).
  - Dừng kéo ngay khi đủ `max_videos` video MỚI hoặc chạm trần `TRAN_MUC_KEO = max(300, max_videos * 5)`.
  - Gọi `dem_trang()` mỗi 15 mục kéo từ generator (gồm mục đầu tiên).
  - Trả `None` để rơi về nhánh trình duyệt khi công tắc `VIDEODL_PROFILE_YT_DLP=0`, khi `extract_info`
    ném lỗi, hoặc khi kéo được 0 mục hợp lệ. Lỗi giữa chừng sau khi đã có mục hợp lệ ⇒ trả những gì đã có.

BẤT BIẾN (agy R1b ĐK-R09-1): 0 mục hợp lệ ⇒ LUÔN `None`, không bao giờ `[]`. `[]` nghĩa là "mọi video đã có trong
thư viện" (`nguon.py` ⇒ `STOP_ALREADY_OWNED` ⇒ job `done`); `het_danh_sach` với 0 mục là chặn mềm `item_list`,
không phải tài khoản rỗng (tài khoản rỗng/riêng tư ném lỗi ngay ở `extract_info`).

Log (R-09 #2, bật luôn): MỌI lối ra ghi đúng 1 dòng tĩnh
`profile yt-dlp: thu=T keo=K hop_le=H moi=M da_co=D ket_thuc=<lý do> loi=<nhãn>` — nhãn ở
`phan_loai_loi_profile_yt_dlp`, 0 thông điệp/URL/handle.

Thử lại (ĐK-R09-4, cờ `VIDEODL_PROFILE_YT_DLP_THU_LAI` mặc định TẮT): lượt 1 hỏng với `loi=timeout` khi CHƯA kéo
được mục nào (`keo=0` ⇒ chưa gọi `dem_trang`/`on_skip`) ⇒ nghỉ ngắn, mở phiên `YoutubeDL` mới chạy lượt 2 (`thu=2`).
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Callable

from yt_dlp import YoutubeDL

from tiktok_music_downloader import phan_loai_loi_profile_yt_dlp as pl
from tiktok_music_downloader.utils import VideoRef

log = logging.getLogger("ttmd")

ENV_PROFILE_YT_DLP = "VIDEODL_PROFILE_YT_DLP"
ENV_PROFILE_YT_DLP_THU_LAI = "VIDEODL_PROFILE_YT_DLP_THU_LAI"
SO_MUC_MOI_TRANG = 15
TRAN_MUC_KEO = 300
HE_SO_TRAN_KEO = 5
# Trần chờ mỗi request (giây): 1 trang video lùi lấy secUid treo không kéo dài lượt quá lâu (ĐK-R09-4).
SOCKET_TIMEOUT = 15
GIAY_NGHI_THU_LAI = 1.0

_MAU_ID_TIKTOK = re.compile(r"^\d{15,25}$")
_MAU_HANDLE_URL = re.compile(r"https?://(?:www\.)?tiktok\.com/@([\w.\-]+)", re.I)
_MAU_URL_TIKTOK = re.compile(r"https?://(?:[\w\-]+\.)*tiktok\.com/", re.I)

def profile_yt_dlp_dang_bat() -> bool:
    """Công tắc `VIDEODL_PROFILE_YT_DLP`: mặc định BẬT; `"0"` (hoặc false/no/off) ⇒ TẮT."""
    gia_tri = os.environ.get(ENV_PROFILE_YT_DLP, "").strip().lower()
    return gia_tri not in ("0", "false", "no", "off")


def thu_lai_dang_bat() -> bool:
    """Cờ `VIDEODL_PROFILE_YT_DLP_THU_LAI`: mặc định TẮT; `"1"` (hoặc true/yes/on) ⇒ BẬT."""
    return os.environ.get(ENV_PROFILE_YT_DLP_THU_LAI, "").strip().lower() in ("1", "true", "yes", "on")


def _tinh_tran_muc_keo(max_videos: int) -> int:
    """Trần số mục kéo từ generator: đủ chỗ lướt qua video thư viện đã có, nhưng không kéo vô hạn."""
    return max(TRAN_MUC_KEO, max_videos * HE_SO_TRAN_KEO)


def _trich_handle(url: str) -> str | None:
    m = _MAU_HANDLE_URL.match((url or "").strip())
    return m.group(1) if m else None


def _ref_tu_muc_phang(muc: dict, handle_url: str | None) -> VideoRef | None:
    """Chuyển một mục phẳng của `TikTokUserIE` thành `VideoRef` (id số trần `^\\d{15,25}$`), hoặc `None`."""
    vid = muc.get("id")
    if not isinstance(vid, str) or not _MAU_ID_TIKTOK.match(vid):
        return None
    url_muc = muc.get("url")
    if isinstance(url_muc, str) and _MAU_URL_TIKTOK.match(url_muc.strip()):
        link_video = url_muc.strip()
    else:
        handle = handle_url or muc.get("uploader") or muc.get("author") or "_"
        link_video = f"https://www.tiktok.com/@{handle}/video/{vid}"
    tieu_de = muc.get("title")
    title = tieu_de.strip() if isinstance(tieu_de, str) and tieu_de.strip() else None
    tac_gia = muc.get("author") or muc.get("uploader") or muc.get("channel") or muc.get("uploader_id")
    author = tac_gia.strip() if isinstance(tac_gia, str) and tac_gia.strip() else None
    thoi_luong = muc.get("duration")
    duration = (
        int(thoi_luong)
        if isinstance(thoi_luong, (int, float)) and not isinstance(thoi_luong, bool) and thoi_luong > 0
        else None
    )
    return VideoRef(video_id=vid, url=link_video, title=title, author=author, duration=duration)


def liet_ke_profile_yt_dlp(
    url: str,
    *,
    max_videos: int,
    proxy: str | None = None,
    already_have: Callable[[list[str]], set[str]] | None = None,
    on_skip: Callable[[VideoRef], None] | None = None,
    dem_trang: Callable[[], None] | None = None,
) -> list[VideoRef] | None:
    """Liệt kê tối đa `max_videos` video MỚI từ trang `@profile` qua yt-dlp; hỏng/0 mục hợp lệ ⇒ `None`."""
    if not profile_yt_dlp_dang_bat():
        return None
    refs, loi, da_keo = _mot_luot(url, 1, max_videos=max_videos, proxy=proxy, already_have=already_have,
                                  on_skip=on_skip, dem_trang=dem_trang)
    if refs is None and loi == pl.LOI_TIMEOUT and da_keo == 0 and thu_lai_dang_bat():
        time.sleep(GIAY_NGHI_THU_LAI)
        refs, _loi, _keo = _mot_luot(url, 2, max_videos=max_videos, proxy=proxy, already_have=already_have,
                                     on_skip=on_skip, dem_trang=dem_trang)
    return refs


def _ghi_log(thu: int, keo: int, hop_le: int, moi: int, da_co: int, ket_thuc: str, loi: str) -> None:
    log.info("profile yt-dlp: thu=%d keo=%d hop_le=%d moi=%d da_co=%d ket_thuc=%s loi=%s",
             thu, keo, hop_le, moi, da_co, ket_thuc, loi)


def _mot_luot(
    url: str,
    thu: int,
    *,
    max_videos: int,
    proxy: str | None,
    already_have: Callable[[list[str]], set[str]] | None,
    on_skip: Callable[[VideoRef], None] | None,
    dem_trang: Callable[[], None] | None,
) -> tuple[list[VideoRef] | None, str, int]:
    """Một phiên `YoutubeDL`. Trả `(refs | None, nhãn loi, số mục đã kéo)`; ghi đúng 1 dòng log."""
    co = pl.LogBatCo()
    opts: dict = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "socket_timeout": SOCKET_TIMEOUT,
        "logger": co,
    }
    if proxy:
        opts["proxy"] = proxy

    handle_url = _trich_handle(url)
    tran_keo = _tinh_tran_muc_keo(max_videos)
    moi: list[VideoRef] = []
    thay: set[str] = set()
    da_keo = 0
    so_hop_le = 0
    da_bo_vi_da_co = 0
    ly_do_ket_thuc = "rong"
    loi: str | None = None

    with YoutubeDL(opts) as ydl:
        try:
            ie = ydl.extract_info(url, download=False, process=False)
        except Exception as exc:  # noqa: BLE001 — rơi về trình duyệt
            loi = pl.phan_loai(exc, co)
            _ghi_log(thu, 0, 0, 0, 0, "loi_extract", loi)
            return None, loi, 0
        entries = ie.get("entries") if isinstance(ie, dict) else None
        if entries is None:
            _ghi_log(thu, 0, 0, 0, 0, "khong_co_entries", pl.LOI_KHAC)
            return None, pl.LOI_KHAC, 0
        try:
            it = iter(entries)
        except Exception:  # noqa: BLE001
            _ghi_log(thu, 0, 0, 0, 0, "loi_iter", pl.LOI_KHAC)
            return None, pl.LOI_KHAC, 0

        while len(moi) < max_videos and da_keo < tran_keo:
            try:
                muc = next(it)
            except StopIteration:
                ly_do_ket_thuc = "het_danh_sach"
                break
            except Exception as exc:  # noqa: BLE001 — giữ những mục hợp lệ đã kéo được
                # Chưa có mục hợp lệ ⇒ lỗi trang ĐẦU `item_list` (ĐK-R09-2 ii), không phải "giữa chừng".
                ly_do_ket_thuc = "loi_giua_chung" if so_hop_le > 0 else "loi_trang_dau"
                loi = pl.phan_loai(exc, co)
                break
            if da_keo % SO_MUC_MOI_TRANG == 0 and dem_trang is not None:
                dem_trang()
            da_keo += 1
            if not isinstance(muc, dict):
                continue
            ref = _ref_tu_muc_phang(muc, handle_url)
            if ref is None or ref.video_id in thay:
                continue
            thay.add(ref.video_id)
            so_hop_le += 1
            if already_have is not None and ref.video_id in already_have([ref.video_id]):
                da_bo_vi_da_co += 1
                if on_skip is not None:
                    on_skip(ref)
                continue
            moi.append(ref)
        else:
            ly_do_ket_thuc = "du" if len(moi) >= max_videos else "tran_keo"

    if so_hop_le == 0:
        # Bất biến ĐK-R09-1: KHÔNG trả `[]` (sẽ thành "đã có hết" giả) ⇒ rơi về trình duyệt.
        loi = loi or pl.LOI_RONG_ITEM_LIST
        _ghi_log(thu, da_keo, 0, 0, 0, ly_do_ket_thuc, loi)
        return None, loi, da_keo

    loi = loi or pl.LOI_KHONG
    _ghi_log(thu, da_keo, so_hop_le, len(moi), da_bo_vi_da_co, ly_do_ket_thuc, loi)
    return moi, loi, da_keo
