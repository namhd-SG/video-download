"""Bảng NGUỒN: mỗi nền tảng một lớp biết nhận URL nào và liệt kê video của URL đó ra sao.

Trước đây hai chỗ khoá cứng TikTok (cổng URL ở `web/app.py`, nhánh liệt kê ở `web/queue.py`).
Giờ cả hai hỏi bảng này; thêm nền tảng = thêm một lớp vào `NGUON`, không sửa hai chỗ đó.

Bước này bảng chỉ có `TikTokCollection`, bọc NGUYÊN hành vi cũ — cùng hàm, cùng kwargs, cùng
thứ tự — nên không có gì đổi với TikTok. Bước tải (`tai`) chưa nằm trong giao thức: TikTok vẫn
đi `download_all`, nền tảng đầu tiên cần cách tải riêng sẽ thêm nó cùng lúc.

Module này KHÔNG import `web.*` (lớp `src/` không được phụ thuộc lớp web): mọi thứ cần DB hay
cờ môi trường do người gọi dựng sẵn rồi truyền vào qua tham số.
"""
from __future__ import annotations

from typing import Callable, Protocol

from tiktok_music_downloader.hashtag_enumerator import enumerate_hashtag
from tiktok_music_downloader.scraper import scrape_music_page_multi
from tiktok_music_downloader.utils import (
    VideoRef,
    is_tiktok_collection,
    loai_nguon,
    parse_tag_slug,
)


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


# Thứ tự = thứ tự thử `nhan`; nguồn đầu tiên nhận thì thắng.
NGUON: tuple[Nguon, ...] = (TikTokCollection(),)


# Nguồn dùng khi một URL cũ không nguồn nào nhận (xem `web/queue.py::_fetch_refs`).
NGUON_MAC_DINH: Nguon = NGUON[0]


def chon_nguon(url: str) -> Nguon | None:
    """Nguồn đầu tiên nhận URL, hoặc None nếu không nguồn nào nhận."""
    for n in NGUON:
        if n.nhan(url):
            return n
    return None
