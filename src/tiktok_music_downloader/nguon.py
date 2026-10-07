"""Bảng NGUỒN: mỗi nền tảng một lớp biết nhận URL nào và liệt kê video của URL đó ra sao.

Trước đây hai chỗ khoá cứng TikTok (cổng URL ở `web/app.py`, nhánh liệt kê ở `web/queue.py`).
Giờ cả hai hỏi bảng này; thêm nền tảng = thêm một lớp vào `NGUON`, không sửa hai chỗ đó.

`TikTokCollection` bọc NGUYÊN hành vi cũ — cùng hàm, cùng kwargs, cùng thứ tự. `FbAdsLibrary` và
`DriveFolder` nối lại hai đường tool GUI đã chạy thật. Bước tải (`tai`) vẫn chưa nằm trong giao
thức: `download_all` chọn cách tải theo tiền tố id (`fb-` luồng HTTP trực tiếp, `gd-` từng file Drive
theo id, còn lại yt-dlp), nên thêm nguồn cùng kiểu tải không phải sửa bảng này.

Module này KHÔNG import `web.*` (lớp `src/` không được phụ thuộc lớp web): mọi thứ cần DB hay
cờ môi trường do người gọi dựng sẵn rồi truyền vào qua tham số.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Protocol

from tiktok_music_downloader import gdrive
from tiktok_music_downloader.hashtag_enumerator import enumerate_hashtag
from tiktok_music_downloader.scraper import scrape_music_page_multi
from tiktok_music_downloader.scraper_fb import scrape_ads_library
from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED,
    STOP_SOURCE_EMPTY,
    VideoRef,
    is_fb_ads_library,
    is_gdrive_folder,
    is_tiktok_collection,
    loai_nguon,
    parse_tag_slug,
)

log = logging.getLogger("ttmd")


class Nguon(Protocol):
    """Một nền tảng. `ten` là mã bền ghi vào `jobs.nen_tang` (chữ thường, không dấu)."""

    ten: str
    mo_ta_url: str

    def nhan(self, url: str) -> bool:
        """URL này thuộc nguồn này không (không chạm mạng)."""

    def loai_log(self, url: str) -> str:
        """Nhãn ngắn thay cho URL khi ghi log (URL/handle không được vào log)."""

    def liet_ke(self, url: str, **kw) -> list[VideoRef]:
        """Liệt kê video của URL. Tham số cụ thể do từng nguồn định nghĩa."""


class TikTokCollection:
    """Trang music / tag / search / profile của TikTok — đúng tập `is_tiktok_collection`."""

    ten = "tiktok"
    mo_ta_url = "trang TikTok music/tag/search/profile"

    def nhan(self, url: str) -> bool:
        return is_tiktok_collection(url)

    def loai_log(self, url: str) -> str:
        return loai_nguon(url)

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None,
                cookies_path: str | None, already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                on_pages: Callable[[int], None], dem_trang: Callable[[], None],
                passes: int, max_seconds: float | None,
                kw_profile: dict) -> list[VideoRef]:
        tag = parse_tag_slug(url)
        if tag is not None:
            # Hashtag đi đường chỉ mục bên thứ ba, không có cookie/profile; lọc từng trang
            # nên "đào sâu tới khi đủ N mới" chạy được.
            return enumerate_hashtag(tag, max_videos=max_videos, proxy=proxy,
                                     already_have=already_have, on_skip=on_skip,
                                     on_stop=on_stop, on_pages=on_pages)
        # music/search/profile: đào sâu nhiều lượt (`scrape_music_page_multi`); `kw_profile`
        # do người gọi dựng (cờ TẮT ⇒ chỉ `profile_dir=None`).
        return scrape_music_page_multi(
            url,
            passes=passes,
            max_videos=max_videos,
            max_seconds=max_seconds,
            already_have=already_have,
            on_skip=on_skip,
            on_stop=on_stop,
            cookies_path=cookies_path,
            proxy=proxy,
            dem_trang=dem_trang,
            **kw_profile,
        )


def _loc_da_co(refs: list[VideoRef], max_videos: int, *, ten_nguon: str,
               already_have: Callable[[list[str]], set[str]],
               on_skip: Callable[[VideoRef], None],
               on_stop: Callable[[str], None]) -> list[VideoRef]:
    """Lọc một lần cho nguồn liệt kê TRỌN danh sách (FB Ads, thư mục Drive): bỏ trùng id, bỏ video
    thư viện đã có (mỗi cái gọi `on_skip` để còn dấu nguồn), rồi cắt `max_videos` video MỚI.

    Rỗng KHÔNG im lặng: nguồn không đưa ra gì ⇒ `source_empty` (job báo lỗi, kèm một dòng log có
    TÊN nguồn — Ads Library đổi DOM thì ra 0 video, không được hiện "Xong"); nguồn có nhưng thư
    viện đã có hết ⇒ `already_owned` (xong thật, chạy lại vô ích).
    """
    thay: set[str] = set()
    duy_nhat = [r for r in refs if not (r.video_id in thay or thay.add(r.video_id))]
    if not duy_nhat:
        log.warning("nguồn %s: không lấy được video nào (link sai, không công khai, hoặc trang đổi cấu trúc)",
                    ten_nguon)
        on_stop(STOP_SOURCE_EMPTY)
        return []
    da_co = already_have([r.video_id for r in duy_nhat])
    moi: list[VideoRef] = []
    for r in duy_nhat:
        if r.video_id in da_co:
            on_skip(r)
        else:
            moi.append(r)
    if not moi:
        on_stop(STOP_ALREADY_OWNED)
        return []
    return moi[:max_videos]


class FbAdsLibrary:
    """Trang Facebook Ads Library. Playwright headless, không cookie, MỘT lượt cuộn (FB nhạy với
    việc quay lại nhiều lần). Ref mang URL FBCDN ký HMAC hết hạn sau vài giờ ⇒ người gọi phải tải
    NGAY sau khi liệt kê; `download_all` tải ref `fb-` bằng luồng HTTP trực tiếp (không qua yt-dlp)."""

    ten = "fb_ads"
    mo_ta_url = "trang Facebook Ads Library"

    def nhan(self, url: str) -> bool:
        return is_fb_ads_library(url)

    def loai_log(self, url: str) -> str:
        return "fb_ads"

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None = None,
                already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                **_chua_dung) -> list[VideoRef]:
        refs = scrape_ads_library(url, max_videos=max_videos, headless=True,
                                  proxy=proxy, profile_dir=None)
        return _loc_da_co(refs, max_videos, ten_nguon=self.ten, already_have=already_have,
                          on_skip=on_skip, on_stop=on_stop)


class DriveFolder:
    """Thư mục Google Drive công khai. Liệt kê KHÔNG tải (`gdrive.list_folder_videos`), chỉ giữ file
    video, id `gd-<fileId>`; `download_all` tải TỪNG file theo id nên mỗi lúc chỉ một file nằm trên
    đĩa (verify → đẩy Drive → xoá local trước khi sang file kế)."""

    ten = "drive"
    mo_ta_url = "thư mục Google Drive công khai"

    def nhan(self, url: str) -> bool:
        return is_gdrive_folder(url)

    def loai_log(self, url: str) -> str:
        return "drive"

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None = None,
                already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                **_chua_dung) -> list[VideoRef]:
        try:
            files = gdrive.list_folder_videos(url, proxy=proxy)
        except Exception as exc:  # noqa: BLE001 — đổi thành lỗi có tên nguồn, không kèm id/URL
            raise RuntimeError(
                f"nguồn drive: không liệt kê được thư mục ({type(exc).__name__})") from exc
        refs = [VideoRef(video_id=f"gd-{fid}", url=gdrive.DRIVE_FILE_URL.format(fid),
                         title=Path(ten).stem or None) for fid, ten in files]
        return _loc_da_co(refs, max_videos, ten_nguon=self.ten, already_have=already_have,
                          on_skip=on_skip, on_stop=on_stop)


# Thứ tự = thứ tự thử `nhan`; nguồn đầu tiên nhận thì thắng. Ba tập URL không giao nhau.
NGUON: tuple[Nguon, ...] = (TikTokCollection(), FbAdsLibrary(), DriveFolder())


# Nguồn dùng khi một URL cũ không nguồn nào nhận (xem `web/queue.py::_fetch_refs`).
NGUON_MAC_DINH: Nguon = NGUON[0]


def chon_nguon(url: str) -> Nguon | None:
    """Nguồn đầu tiên nhận URL, hoặc None nếu không nguồn nào nhận."""
    for n in NGUON:
        if n.nhan(url):
            return n
    return None


def mo_ta_cac_nguon() -> str:
    """Câu liệt kê các loại link đang nhận, cho thông báo 400 (sinh từ bảng, thêm nguồn tự có mặt)."""
    return ", ".join(n.mo_ta_url for n in NGUON)
