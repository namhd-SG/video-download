"""Nguồn Facebook page HÀNG LOẠT (R-09 #3, Đường A không cookie): `facebook.com/<page>`, `/<page>/videos`, `/<page>/reels`.

Đường (đã chốt, số đo bước 0): patchright Chrome thật, KHÔNG cookie ⇒ mở tab ⇒ đọc `<script type="application/json">` lúc
tải + bắt XHR `/api/graphql` whitelist ⇒ lọc theo chủ page ⇒ video tải lẻ bằng yt-dlp qua `download_all` (nền tảng khác,
id `fbv-<mã>`). Không cookie nên khách chỉ thấy một ít (≈16–22 video ở /videos, ≈50 ở /reels) rồi gặp hộp thoại đăng nhập
không đóng được ⇒ mã dừng `fb_chan_dang_nhap` khi chưa đủ số xin. Nhận dạng KHÔNG gọi mạng; liệt kê mỗi lượt MỞ trang =
một `cong.truoc_goi()` (bộ điều tốc IP của pacer).

Đứng TRƯỚC `LinkLe` trong `NGUON`: `/<page>/videos/<id>`, `/reel/<id>`, `/watch/?v=`, `/share/…` là link lẻ; thư viện quảng
cáo (`/ads/library`) thuộc `FbAdsLibrary`. Nền tảng `facebook` chỉ chạy khi có trong `VIDEODL_NEN_TANG_BAT` (mặc định TẮT).

Log chỉ có mã loại trang và con số: URL, tên page, mã video, tiền tố `fbv-` không bao giờ vào log hay thông điệp lỗi.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from tiktok_music_downloader import fb_quet_cuon
from tiktok_music_downloader.fb_trinh_duyet import PhienFB
from tiktok_music_downloader.utils import STOP_BI_CHAN, VideoRef

log = logging.getLogger("ttmd")

_HOST_FB = ("facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com")
BASE = "https://www.facebook.com"
# Đoạn đường dẫn đầu KHÔNG phải tên page (link lẻ, trang hệ thống…): không nhận là page.
_DUONG_RIENG = frozenset({
    "ads", "reel", "reels", "watch", "share", "sharer", "groups", "events", "profile.php", "video", "videos", "photo",
    "photos", "stories", "story.php", "permalink.php", "marketplace", "gaming", "login", "help", "policies", "privacy",
    "pages", "people", "hashtag", "public", "plugins", "dialog", "tr", "l.php", "business", "notes", "fundraisers",
    "bookmarks", "search", "friends", "messages", "settings", "checkpoint", "recover", "legal", "about", "careers",
    "developers", "media", "live", "lite", "ajax", "api", "home.php", "composer", "saved", "memories", "reviews",
})
_MAU_PAGE = re.compile(r"[A-Za-z0-9.\-]{1,100}")
_MAU_DUONG = re.compile(r"/([^/]+)(?:/(videos|reels))?/?")


@dataclass(frozen=True)
class Dich:
    loai: str        # "videos" | "reels"
    url: str         # URL đã ép về dạng đo được


def phan_tich_url(url: str) -> Dich | None:
    """Loại tab + URL chuẩn, hoặc None nếu không phải nguồn hàng loạt. Không gọi mạng."""
    try:
        t = urlsplit(url.strip())
    except ValueError:
        return None
    if t.scheme not in ("http", "https") or (t.hostname or "").lower() not in _HOST_FB or "\n" in url.strip():
        return None
    m = _MAU_DUONG.fullmatch(t.path or "/")
    if not m:
        return None
    page, tab = m.group(1), m.group(2) or "videos"        # `/<page>` ⇒ ép `/videos`
    if page.lower() in _DUONG_RIENG or page.lower().endswith(".php") or not _MAU_PAGE.fullmatch(page):
        return None
    return Dich(tab, f"{BASE}/{page}/{tab}")


def _mo_phien(proxy: str | None) -> PhienFB:
    """Điểm tiêm của test: trả context manager cho `TrangFB`. Đường A: luôn ẩn danh (cookies_path=None)."""
    return PhienFB(None, proxy=proxy)


class FacebookTrang:
    """Tab /videos hoặc /reels của một page Facebook. Một job = MỘT URL; số video theo ô số lượng."""

    ten = "facebook_trang"
    mo_ta_url = "Facebook page: tab Videos / Reels (không cần cookie, khách chỉ thấy khoảng 16–50 video đầu)"

    def nhan(self, url: str) -> bool:
        return phan_tich_url(url) is not None

    def nen_tang(self, url: str) -> str:
        return "facebook"

    def loai_log(self, url: str) -> str:
        d = phan_tich_url(url)
        return f"facebook:{d.loai if d else 'khac'}"

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None = None,
                already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                cong=None, max_seconds: float | None = None, **_chua_dung) -> list[VideoRef]:
        from tiktok_music_downloader.nguon import TRAN_THOI_LUONG_GIAY       # nhập muộn: `nguon` nhập module này
        d = phan_tich_url(url)
        if d is None:
            raise ValueError("url không phải nguồn Facebook page hàng loạt")
        if cong is not None:
            dung = cong.truoc_goi()              # mỗi lượt MỞ trang FB = một lượt pacer
            if dung:
                on_stop(dung)
                return []
        try:
            with _mo_phien(proxy) as trang:
                kq = fb_quet_cuon.quet(trang, d.url, tab=d.loai, max_videos=max_videos, already_have=already_have,
                                       on_skip=on_skip, tran_thoi_luong_giay=TRAN_THOI_LUONG_GIAY,
                                       max_seconds=max_seconds)
        except Exception as exc:  # noqa: BLE001 — thông điệp Playwright/Chrome kèm URL (tên page): chỉ tên lớp đi tiếp
            if cong is not None:
                cong.xu_ly_loi(exc)
            raise RuntimeError(f"nguồn facebook: lỗi trình duyệt ({type(exc).__name__})") from None
        if kq.chan_429:
            log.warning("facebook:%s: HTTP 429 sau %d XHR, %d lần cuộn", d.loai, kq.so_xhr, kq.so_cuon)
            if cong is not None:
                cong.xu_ly_loi(RuntimeError("HTTP Error 429"))       # tắt nền tảng tới khi admin bật lại
            on_stop(STOP_BI_CHAN)
            return []
        log.info("facebook:%s: %d video mới, %d đã có, %d lạ owner, %d quá dài, %d XHR, %d lần cuộn, "
                 "%d lần đóng hộp thoại, tường=%s", d.loai, len(kq.refs), kq.so_da_co, kq.so_la, kq.so_qua_dai,
                 kq.so_xhr, kq.so_cuon, kq.so_bam_dong, "có" if kq.co_tuong else "không")
        on_stop(kq.ly_do)
        return kq.refs
