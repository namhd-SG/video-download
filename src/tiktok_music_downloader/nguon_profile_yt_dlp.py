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
"""
from __future__ import annotations

import logging
import os
import re
from typing import Callable

from yt_dlp import YoutubeDL

from tiktok_music_downloader import downloader
from tiktok_music_downloader.utils import VideoRef

log = logging.getLogger("ttmd")

ENV_PROFILE_YT_DLP = "VIDEODL_PROFILE_YT_DLP"
SO_MUC_MOI_TRANG = 15
TRAN_MUC_KEO = 300
HE_SO_TRAN_KEO = 5

_MAU_ID_TIKTOK = re.compile(r"^\d{15,25}$")
_MAU_HANDLE_URL = re.compile(r"https?://(?:www\.)?tiktok\.com/@([\w.\-]+)", re.I)
_MAU_URL_TIKTOK = re.compile(r"https?://(?:[\w\-]+\.)*tiktok\.com/", re.I)

def profile_yt_dlp_dang_bat() -> bool:
    """Công tắc `VIDEODL_PROFILE_YT_DLP`: mặc định BẬT; `"0"` (hoặc false/no/off) ⇒ TẮT."""
    gia_tri = os.environ.get(ENV_PROFILE_YT_DLP, "").strip().lower()
    return gia_tri not in ("0", "false", "no", "off")


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
    opts: dict = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "logger": downloader._YtdlpLog(),
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

    with YoutubeDL(opts) as ydl:
        try:
            ie = ydl.extract_info(url, download=False, process=False)
        except Exception as exc:  # noqa: BLE001 — rơi về trình duyệt
            log.info(
                "profile yt-dlp: keo=0 hop_le=0 moi=0 da_co=0 ket_thuc=loi_extract (%s)",
                type(exc).__name__,
            )
            return None
        entries = ie.get("entries") if isinstance(ie, dict) else None
        if entries is None:
            log.info("profile yt-dlp: keo=0 hop_le=0 moi=0 da_co=0 ket_thuc=khong_co_entries")
            return None
        try:
            it = iter(entries)
        except Exception as exc:  # noqa: BLE001
            log.info(
                "profile yt-dlp: keo=0 hop_le=0 moi=0 da_co=0 ket_thuc=loi_iter (%s)",
                type(exc).__name__,
            )
            return None

        while len(moi) < max_videos and da_keo < tran_keo:
            try:
                muc = next(it)
            except StopIteration:
                ly_do_ket_thuc = "het_danh_sach"
                break
            except Exception as exc:  # noqa: BLE001 — giữ những mục hợp lệ đã kéo được
                ly_do_ket_thuc = f"loi_giua_chung:{type(exc).__name__}"
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
        log.info(
            "profile yt-dlp: keo=%d hop_le=0 moi=0 da_co=0 ket_thuc=%s",
            da_keo,
            ly_do_ket_thuc,
        )
        return None

    log.info(
        "profile yt-dlp: keo=%d hop_le=%d moi=%d da_co=%d ket_thuc=%s",
        da_keo,
        so_hop_le,
        len(moi),
        da_bo_vi_da_co,
        ly_do_ket_thuc,
    )
    return moi
