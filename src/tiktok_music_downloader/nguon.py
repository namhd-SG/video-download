"""Bảng NGUỒN: mỗi nền tảng một lớp biết nhận URL nào và liệt kê video của URL đó ra sao.

Trước đây hai chỗ khoá cứng TikTok (cổng URL ở `web/app.py`, nhánh liệt kê ở `web/queue.py`).
Giờ cả hai hỏi bảng này; thêm nền tảng = thêm một lớp vào `NGUON`, không sửa hai chỗ đó.

`TikTokCollection` bọc NGUYÊN hành vi cũ — cùng hàm, cùng kwargs, cùng thứ tự. `FbAdsLibrary` và
`DriveFolder` nối lại hai đường tool GUI đã chạy thật. Bước tải (`tai`) vẫn chưa nằm trong giao
thức: `download_all` chọn cách tải theo tiền tố id (`fb-` luồng HTTP trực tiếp, `gd-` từng file Drive
theo id, còn lại yt-dlp), nên thêm nguồn cùng kiểu tải không phải sửa bảng này.

`LinkLe` nhận video lẻ của nhiều nền tảng bằng chính bộ nhận dạng của yt-dlp (`ie.suitable`, không gọi mạng),
chỉ giữ những extractor có trong bảng `BANG_LINK_LE`; nền tảng nào ĐƯỢC BẬT do cấu hình `VIDEODL_NEN_TANG_BAT`.

Module này KHÔNG import `web.*` (lớp `src/` không được phụ thuộc lớp web): mọi thứ cần DB hay
cờ môi trường do người gọi dựng sẵn rồi truyền vào qua tham số.
"""
from __future__ import annotations

import functools
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from typing import Callable, Protocol

from yt_dlp import YoutubeDL
from yt_dlp.extractor import gen_extractor_classes

from tiktok_music_downloader import downloader, gdrive
from tiktok_music_downloader.hashtag_enumerator import enumerate_hashtag
from tiktok_music_downloader.scraper import scrape_music_page_multi
from tiktok_music_downloader.scraper_fb import scrape_ads_library
from tiktok_music_downloader.phan_loai_loi import (
    LOI_LA_PLAYLIST,
    LOI_QUA_DAI,
    LOI_QUA_NANG,
    LOI_THIEU_JS,
    LOI_TRUC_TIEP,
    ly_do_loi_video,
)
from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED,
    STOP_SOURCE_EMPTY,
    VideoRef,
    che_url,
    is_fb_ads_library,
    is_gdrive_folder,
    is_tiktok_collection,
    loai_nguon,
    parse_tag_slug,
    parse_video_url,
)

log = logging.getLogger("ttmd")


class Nguon(Protocol):
    """Một nền tảng. `ten` là mã bền ghi vào `jobs.nen_tang` (chữ thường, không dấu)."""

    ten: str
    mo_ta_url: str

    def nhan(self, url: str) -> bool:
        """URL này thuộc nguồn này không (không chạm mạng)."""

    def nen_tang(self, url: str) -> str:
        """Mã nền tảng ghi vào `jobs.nen_tang` cho URL này (đã được `nhan`). Nguồn một-nền-tảng trả `ten`."""

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

    def nen_tang(self, url: str) -> str:
        return self.ten

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

    def nen_tang(self, url: str) -> str:
        return self.ten

    def loai_log(self, url: str) -> str:
        return "fb_ads"

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None = None,
                already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                **_chua_dung) -> list[VideoRef]:
        # `da_co` cho trình quét đếm riêng video MỚI: cuộn tới khi đủ `max_videos` mới (trần 3×), nếu không
        # lượt chạy lại cùng trang dừng ngay khi thấy N video — toàn video đã có — và báo `already_owned` sai.
        refs = scrape_ads_library(url, max_videos=max_videos, headless=True,
                                  proxy=proxy, profile_dir=None, da_co=already_have)
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

    def nen_tang(self, url: str) -> str:
        return self.ten

    def loai_log(self, url: str) -> str:
        return "drive"

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None = None,
                already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                **_chua_dung) -> list[VideoRef]:
        try:
            files = gdrive.list_folder_videos(url, proxy=proxy)
        except Exception as exc:  # noqa: BLE001 — đổi thành lỗi có tên nguồn
            # Văn bản lỗi gốc (gdown/urllib3) nhúng id thư mục ("folder ID: <id>", "url: …?id=<id>") nên
            # KHÔNG đưa vào thông điệp: chỉ loại lỗi + mã HTTP. `from None` để traceback của `log.exception`
            # cũng không in chuỗi nguyên nhân.
            raise RuntimeError(
                f"nguồn drive: không liệt kê được thư mục ({gdrive.mo_ta_loi(exc)})") from None
        refs = [VideoRef(video_id=f"gd-{fid}", url=gdrive.DRIVE_FILE_URL.format(fid),
                         title=Path(ten).stem or None) for fid, ten in files]
        return _loc_da_co(refs, max_videos, ten_nguon=self.ten, already_have=already_have,
                          on_skip=on_skip, on_stop=on_stop)


# ===========================================================================
# LINK LẺ ĐA NỀN TẢNG (yt-dlp)
# ===========================================================================
# `ie_key` của yt-dlp → (mã nền tảng ghi vào `jobs.nen_tang`, tiền tố id video). Một nơi duy nhất quyết định
# nền tảng nào có mặt: URL mà extractor KHÔNG nằm trong bảng (kênh/playlist/tab `YoutubeTab`, `TikTokUser`,
# `InstagramUser`, link rút gọn `TikTokVM`…) thì không nhận — kênh/playlist là việc riêng, chưa làm.
# Tiền tố cho id không phải số (id YouTube/Instagram có thể bắt đầu bằng `-`, và id của nền tảng này không
# được đụng id nền tảng khác); TikTok giữ id số TRẦN vì thư viện/thumbnail/tải đã quen dạng đó (⇒ lane TikTok).
# Không có Threads: không extractor nào của bản yt-dlp cài chứa "thread".
BANG_LINK_LE: dict[str, tuple[str, str]] = {
    "Youtube": ("youtube", "yt-"),
    "TikTok": ("tiktok", ""),
    "Instagram": ("instagram", "ig-"),
    "Facebook": ("facebook", "fbv-"),
    "FacebookReel": ("facebook", "fbv-"),
    "Twitter": ("x", "x-"),
    "Pinterest": ("pinterest", "pin-"),
    "Douyin": ("douyin", "dy-"),
    "BiliBili": ("bilibili", "bili-"),
    "SnapchatSpotlight": ("snapchat", "snap-"),
}
NEN_TANG_LINK_LE: frozenset[str] = frozenset(nt for nt, _ in BANG_LINK_LE.values())
# Tiền tố id của nền tảng link lẻ (không gồm TikTok vốn id trần) — để mẫu kiểm đường dẫn tệp không phải chép lại.
TIEN_TO_ID_LINK_LE: tuple[str, ...] = tuple(sorted({t.rstrip("-") for _, t in BANG_LINK_LE.values() if t}))

# Cấu hình nền tảng link lẻ nào được nhận. Chưa đặt hoặc để trống ⇒ mặc định; đặt tên không có trong bảng ⇒ bỏ
# qua tên đó (kèm MỘT dòng cảnh báo cho mỗi giá trị cấu hình) chứ không để một lỗi gõ làm tắt nền tảng khác.
#
# ⚠ Chỉ YouTube và TikTok video lẻ đã được dựng với bộ đo. Instagram, Facebook, X, Pinterest, Douyin, Bilibili,
# Snapchat có trong bảng nhưng CHƯA smoke: phải chạy smoke riêng (3/3 link công khai trên máy chạy thật) rồi mới
# thêm tên vào cấu hình này. Instagram/Facebook/X còn cần cookie cho phần lớn nội dung.
ENV_NEN_TANG_BAT = "VIDEODL_NEN_TANG_BAT"
NEN_TANG_BAT_MAC_DINH = "youtube,tiktok"

# Trần theo từng video, đo ở bước liệt kê (trước khi tải): video dài/nặng hơn thì bỏ, không tải.
TRAN_THOI_LUONG_GIAY = 15 * 60
TRAN_DUNG_LUONG_BYTE = 500 * 1024 * 1024
# Id sau tiền tố chỉ gồm chữ-số/gạch (tên tệp, đường dẫn thumbnail và mẫu kiểm của `GET /thumbs`); độ dài tổng
# (tiền tố + id) bằng trần của mẫu đó.
_MAU_ID_VIDEO = re.compile(r"[A-Za-z0-9_\-]+")
TRAN_DO_DAI_ID = 64
_MAU_URL_HTTP = re.compile(r"https?://", re.I)


def tach_link(van_ban: str) -> list[str]:
    """Các link trong ô nhập: mỗi dòng một link, bỏ dòng trống, bỏ trùng giữ thứ tự."""
    thay: set[str] = set()
    ra: list[str] = []
    for dong in (van_ban or "").splitlines():
        dong = dong.strip()
        if dong and dong not in thay:
            thay.add(dong)
            ra.append(dong)
    return ra


_DA_CANH_BAO_CAU_HINH: set[str] = set()


def nen_tang_bat() -> frozenset[str]:
    """Nền tảng link lẻ đang được bật (đọc cấu hình MỖI LẦN gọi: đổi cấu hình rồi khởi động lại là đủ, và test
    không phải dựng lại module). Hàm này chạy mỗi giây (vòng nhận job), nên cảnh báo tên lạ chỉ ghi MỘT lần cho
    mỗi giá trị cấu hình."""
    tho = os.environ.get(ENV_NEN_TANG_BAT, "").strip() or NEN_TANG_BAT_MAC_DINH
    ten = {t.strip().lower() for t in tho.split(",") if t.strip()}
    la = ten - NEN_TANG_LINK_LE
    if la and tho not in _DA_CANH_BAO_CAU_HINH:
        _DA_CANH_BAO_CAU_HINH.add(tho)
        log.warning("%s có tên nền tảng không biết (bỏ qua): %s", ENV_NEN_TANG_BAT, ", ".join(sorted(la)))
    return frozenset(ten & NEN_TANG_LINK_LE)


# Tên hiện cho người dùng (thông báo lỗi).
TEN_HIEN_THI = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram", "facebook": "Facebook",
                "x": "X", "pinterest": "Pinterest", "douyin": "Douyin", "bilibili": "Bilibili",
                "snapchat": "Snapchat"}

_MAU_ID_YOUTUBE = re.compile(r"[A-Za-z0-9_\-]{11}")
_HOST_YOUTUBE = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be",
                 "www.youtu.be")


def chuan_hoa_link(url: str) -> str:
    """Link YouTube chỉ giữ phần chỉ ra MỘT video: `watch?v=X&list=…&index=…&start_radio=…&pp=…` (link mở từ
    Mix/playlist) ⇒ `watch?v=X`. Không làm vậy thì `YoutubeIE.suitable` trả False khi có `list` (extractor playlist
    giành link) và cả link video thật bị 400. `shorts/ID`, `youtu.be/ID` bỏ hết query. Link khác: nguyên văn."""
    try:
        t = urlsplit(url.strip())
    except ValueError:
        return url
    if (t.hostname or "").lower() not in _HOST_YOUTUBE:
        return url
    from urllib.parse import parse_qs
    host = (t.hostname or "").lower()
    if t.path.rstrip("/") == "/watch":
        v = parse_qs(t.query).get("v", [""])[0]
        # Chỉ id đúng hình (11 ký tự chữ-số/gạch): không bao giờ chèn chuỗi đã giải mã (`v=X%26list%3D…`) vào URL.
        return f"https://www.youtube.com/watch?v={v}" if _MAU_ID_YOUTUBE.fullmatch(v) else url
    if host.endswith("youtu.be") or t.path.startswith("/shorts/"):
        return f"{t.scheme}://{t.netloc}{t.path}"
    return url


@functools.lru_cache(maxsize=1)
def _extractor_nhan_dang() -> tuple:
    """Mọi extractor của yt-dlp theo thứ tự ưu tiên của nó, trừ Generic (nhận MỌI URL nên vô nghĩa)."""
    return tuple(ie for ie in gen_extractor_classes() if ie.ie_key() != "Generic")


def _ie_cua(url: str):
    """Lớp extractor đầu tiên nhận URL (không gọi mạng), hoặc None. Chỉ nhận URL `http(s)://`:
    một số extractor còn nhận id trần."""
    if not _MAU_URL_HTTP.match(url):
        return None
    for ie in _extractor_nhan_dang():
        if ie.suitable(url):
            return ie
    return None


def _ie_key_cua(url: str) -> str | None:
    ie = _ie_cua(url)
    return ie.ie_key() if ie is not None else None


def _id_tam(url: str, tien_to: str) -> str | None:
    """Id video suy từ chính URL (`ie.get_temp_id`, KHÔNG gọi mạng) kèm tiền tố nền tảng, hoặc None. Dùng để bỏ
    link thư viện đã có TRƯỚC khi tốn một lượt gọi nền tảng. Nếu id thật (do `extract_info` trả) khác id tạm thì
    chỉ là một lượt liệt kê dư — bước lọc sau liệt kê vẫn chặn trùng."""
    ie = _ie_cua(url)
    vid = ie.get_temp_id(url) if ie is not None else None
    if not isinstance(vid, str) or not _MAU_ID_VIDEO.fullmatch(vid) or len(tien_to + vid) > TRAN_DO_DAI_ID:
        return None
    return tien_to + vid


class _ThieuJs(RuntimeError):
    """yt-dlp báo không thấy JS runtime trong lúc đọc link — lỗi của link đó (xem `downloader._YtdlpLog`)."""


def _extract_info(url: str, proxy: str | None) -> dict | None:
    """Ranh giới yt-dlp của bước liệt kê: một lời gọi `extract_info(download=False)`, KHÔNG tải. Cùng opts
    nền tảng với bước tải (ffmpeg + Deno chỉ đường tường minh)."""
    opts = downloader.opts_chung_nen_tang_khac(proxy)
    opts["skip_download"] = True
    logger = opts["logger"]
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if logger.thieu_js:
        raise _ThieuJs(f"{LOI_THIEU_JS}: yt-dlp không thấy JavaScript runtime (Deno) — đường Deno sai hoặc hỏng")
    return info


def _kich_thuoc_uoc(info: dict) -> float | None:
    """Kích thước ước của video: `filesize`/`filesize_approx` của cả video, hoặc tổng các luồng yt-dlp đã chọn."""
    for k in ("filesize", "filesize_approx"):
        v = info.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return v
    tong = 0.0
    for f in info.get("requested_formats") or ():
        for k in ("filesize", "filesize_approx"):
            v = f.get(k) if isinstance(f, dict) else None
            if isinstance(v, (int, float)) and v > 0:
                tong += v
                break
    return tong or None


def _ref_tu_info(info: dict | None, link: str, tien_to: str) -> tuple[VideoRef | None, str | None]:
    """`(ref, None)` nếu video tải được, hoặc `(None, mã lỗi)` — lỗi của riêng video này, không dừng job."""
    if not isinstance(info, dict):
        return None, "khong_doc_duoc"
    if info.get("_type") in ("playlist", "multi_video") or info.get("entries") is not None:
        return None, LOI_LA_PLAYLIST
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        return None, LOI_TRUC_TIEP
    dur = info.get("duration")
    if isinstance(dur, (int, float)) and dur > TRAN_THOI_LUONG_GIAY:
        return None, LOI_QUA_DAI
    size = _kich_thuoc_uoc(info)
    if size is not None and size > TRAN_DUNG_LUONG_BYTE:
        return None, LOI_QUA_NANG
    vid = info.get("id")
    if not isinstance(vid, str) or not _MAU_ID_VIDEO.fullmatch(vid) or len(tien_to + vid) > TRAN_DO_DAI_ID:
        return None, "id_la"
    return VideoRef(
        video_id=tien_to + vid, url=link,
        title=(info.get("title") or None),
        author=(info.get("uploader") or info.get("uploader_id") or None),
        duration=int(dur) if isinstance(dur, (int, float)) else None,
    ), None


class LinkLe:
    """Video LẺ của nhiều nền tảng (xem `BANG_LINK_LE`), một hoặc nhiều link (mỗi dòng một link) trong một job.

    Nhận dạng không gọi mạng. Liệt kê = một `extract_info(download=False)` mỗi link ⇒ một `VideoRef` (id có tiền
    tố nền tảng); riêng TikTok video lẻ lấy id số thẳng từ URL như `parse_video_url` vốn làm — job TikTok chạy ở
    lane TikTok, với cookie và opts TikTok, nên bước liệt kê không được tự gọi TikTok bằng opts khác."""

    ten = "link_le"
    mo_ta_url = "link video lẻ (YouTube, TikTok, Instagram, Facebook, X, Pinterest, Douyin, Bilibili, Snapchat)"

    def phan_loai(self, url: str) -> tuple[str, str] | None:
        """`(nen_tang, tien_to)` nếu URL là video lẻ của nền tảng trong bảng, ngược lại None."""
        url = chuan_hoa_link(url)
        loai = BANG_LINK_LE.get(_ie_key_cua(url) or "")
        if loai is None:
            return None
        if loai[0] == "tiktok" and parse_video_url(url) is None:
            return None   # TikTok mà không phải `/@user/video/<số>` (embed, photo…): không có id trần để dùng
        return loai

    def nhan(self, url: str) -> bool:
        return self.phan_loai(url) is not None

    def nen_tang(self, url: str) -> str:
        loai = self.phan_loai(url)
        if loai is None:
            raise ValueError("url không phải link video lẻ")
        return loai[0]

    def loai_log(self, url: str) -> str:
        link = (tach_link(url) or [""])[0]
        loai = self.phan_loai(link)
        return f"{loai[0] if loai else 'khac'}:video"

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None = None,
                already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                cong=None, ghi_loi_video: Callable[[str, str], None] | None = None,
                nghi: Callable[[], None] | None = None, **_chua_dung) -> list[VideoRef]:
        """`url` là một hoặc nhiều link (mỗi dòng một). `cong` (`web/pacer.py::CongNenTang`): `truoc_goi()` ghi lượt
        TRƯỚC mỗi lời gọi mạng và trả lý do dừng, `xu_ly_loi(exc)` trả lý do dừng khi lỗi là tín hiệu chặn.
        `ghi_loi_video(mã, chi_tiết)` nhận lỗi RIÊNG từng link (private, quá dài, lỗi mạng…) — job vẫn chạy tiếp.
        `nghi()` chạy giữa hai lời gọi mạng liên tiếp (nghỉ jitter)."""
        so_loi = [0]

        def loi(ma: str, chi_tiet: str = "") -> None:
            so_loi[0] += 1
            if ghi_loi_video is not None:
                ghi_loi_video(ma, chi_tiet)
            else:
                log.warning("link lỗi [%s] %s", ma, chi_tiet)

        ten_nt = "link_le"
        links = []
        for link in tach_link(url):
            loai_link = self.phan_loai(link)
            if loai_link is None:
                loi("khong_nhan", "")
            else:
                links.append((chuan_hoa_link(link), *loai_link))
        # Link thư viện ĐÃ có (theo id suy từ URL, không mạng) bị bỏ TRƯỚC khi gọi nền tảng: mỗi lời gọi là một
        # lượt tính vào trần IP, nên không được đốt lượt cho video không cần. Một lần hỏi cả danh sách.
        id_tam = {link: (parse_video_url(link).video_id if nt == "tiktok" else _id_tam(link, tt))
                  for link, nt, tt in links}
        da_co = already_have([i for i in id_tam.values() if i]) if id_tam else set()
        refs: list[VideoRef] = []
        da_bo_vi_da_co = 0
        dung: str | None = None
        da_goi_mang = False
        for link, nen_tang, tien_to in links:
            if len(refs) >= max_videos:
                break          # đủ số video MỚI: không liệt kê phần còn lại
            ten_nt = nen_tang
            tam = id_tam[link]
            if tam is not None and tam in da_co:
                on_skip(VideoRef(video_id=tam, url=link))
                da_bo_vi_da_co += 1
                continue
            if nen_tang == "tiktok":
                ref = parse_video_url(link)
                if ref is not None:
                    refs.append(ref)
                continue
            if da_goi_mang and nghi is not None:
                nghi()
            if cong is not None:
                dung = cong.truoc_goi()
                if dung:
                    break
            da_goi_mang = True
            try:
                info = _extract_info(link, proxy)
            except Exception as exc:  # noqa: BLE001 — một link hỏng không giết cả job
                if cong is not None:
                    dung = cong.xu_ly_loi(exc)
                    if dung:
                        break
                ma = LOI_THIEU_JS if isinstance(exc, _ThieuJs) else (ly_do_loi_video(exc) or "loi_khac")
                loi(ma, che_url(exc))
                continue
            ref, ma_loi = _ref_tu_info(info, link, tien_to)
            if ref is None:
                loi(ma_loi or "loi_khac", "")
            else:
                refs.append(ref)
        # Lọc trùng/đã có (theo id thật) chạy trên phần ĐÃ liệt kê được. Lượt rỗng: mọi link đều bị bỏ vì đã có ⇒
        # `already_owned`; không có lý do nào ⇒ `source_empty` (mọi link đều lỗi). Lý do dừng của cổng/tín hiệu
        # chặn ghi SAU CÙNG: nó là lý do thật job dừng.
        # `already_owned` chỉ khi KHÔNG link nào lỗi: có link lỗi thì "đã có hết" che mất lỗi đó ⇒ để `source_empty`.
        if not refs and da_bo_vi_da_co and not dung and so_loi[0] == 0:
            on_stop(STOP_ALREADY_OWNED)
            return []
        moi = _loc_da_co(refs, max_videos, ten_nguon=ten_nt, already_have=already_have,
                         on_skip=on_skip, on_stop=on_stop) if (refs or not dung) else []
        if dung:
            on_stop(dung)
        return moi


# Thứ tự = thứ tự thử `nhan`; nguồn đầu tiên nhận thì thắng. Các tập URL không giao nhau (FB Ads Library nằm
# trước `LinkLe` vì extractor `Facebook*` của yt-dlp không được cướp link thư viện quảng cáo).
NGUON: tuple[Nguon, ...] = (TikTokCollection(), FbAdsLibrary(), DriveFolder(), LinkLe())


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
