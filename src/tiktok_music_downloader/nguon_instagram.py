"""Nguồn Instagram HÀNG LOẠT (R-08 M3): profile reels / từ khoá / hashtag / audio ⇒ danh sách video MỚI.

Đường (đã chốt, số đo bước 0): patchright + cookie IG của người tạo job (tài khoản phụ) ⇒ mở trang ⇒ bắt XHR ⇒ lọc
`media_type == 2` ⇒ video tải lẻ bằng yt-dlp `--cookies` qua `download_all` (nền tảng khác, id `ig-<mã>`). Carousel không
tải. Nhận dạng KHÔNG gọi mạng; liệt kê mỗi lượt MỞ URL = một `cong.truoc_goi()` (bộ điều tốc IP của pacer).

Đứng TRƯỚC `LinkLe` trong `NGUON`: URL `/reel/<mã>/`, `/p/<mã>/` thuộc link lẻ, còn `/<user>/`, `/<user>/reels/`,
`/explore/search/keyword/`, `/explore/tags/<tag>/`, `/reels/audio/<id>/` thuộc nguồn này. Nền tảng `instagram` chỉ chạy khi
có trong `VIDEODL_NEN_TANG_BAT` (mặc định TẮT) — cổng ở `web/app.py` như link lẻ.

Log chỉ có mã và con số: URL, handle, từ khoá, mã bài, cookie không bao giờ vào log hay thông điệp lỗi.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs, quote, urlsplit

from tiktok_music_downloader import ig_quet_cuon
from tiktok_music_downloader import ig_xhr_phan_tich as ph
from tiktok_music_downloader.ig_trinh_duyet import PhienIG
from tiktok_music_downloader.tai_anh_cau_hinh import LOAI_HOP_LE, LOAI_VIDEO
from tiktok_music_downloader.utils import STOP_IG_CHUA_CO_COOKIE, STOP_IG_MAT_PHIEN, VideoRef

log = logging.getLogger("ttmd")

_HOST_IG = ("instagram.com", "www.instagram.com")
BASE = "https://www.instagram.com"
# Đoạn đường dẫn đầu KHÔNG phải tên người dùng (link lẻ, trang hệ thống…): không nhận là profile.
_DUONG_RIENG = frozenset({
    "p", "reel", "reels", "tv", "explore", "accounts", "stories", "direct", "about", "legal", "developer", "web",
    "api", "graphql", "challenge", "oauth", "privacy", "directory", "emails", "session", "static", "ajax", "download",
    "lite", "nametag", "shop", "business", "creators", "press", "locations", "topics", "fragment", "sharer",
})
_MAU_USER = re.compile(r"[A-Za-z0-9._]{1,30}")
_MAU_TAG = re.compile(r"[^\W]{1,100}", re.UNICODE)
_MAU_AUDIO = re.compile(r"/reels/audio/(\d{5,25})/?")
_MAU_TAGS = re.compile(r"/explore/tags/([^/\s]+)/?")
_MAU_PROFILE = re.compile(r"/([^/]+)(?:/reels)?/?")
_MAU_BAI_LE = re.compile(r"/p/([A-Za-z0-9_\-]{5,30})/?")
_CHI_VIDEO = frozenset({LOAI_VIDEO})
_CA_BA = frozenset(LOAI_HOP_LE)
TRAN_DO_DAI_TU_KHOA = 100


@dataclass(frozen=True)
class Dich:
    loai: str        # "profile" | "keyword" | "hashtag" | "audio"
    url: str         # URL đã ép về dạng đo được


def phan_tich_url(url: str, loai: str = LOAI_VIDEO) -> Dich | None:
    """Loại trang + URL chuẩn, hoặc None nếu không phải nguồn hàng loạt. Không gọi mạng. `loai` ảnh/cả hai: `/<user>/`
    GIỮ lưới bài (không ép `/reels/`, vì `/reels/` chỉ có reel); `/<user>/reels/` gõ rõ vẫn là trang reel."""
    try:
        t = urlsplit(url.strip())
    except ValueError:
        return None
    if t.scheme not in ("http", "https") or (t.hostname or "").lower() not in _HOST_IG or "\n" in url.strip():
        return None
    duong = t.path or "/"
    m = _MAU_AUDIO.fullmatch(duong)
    if m:
        return Dich("audio", f"{BASE}/reels/audio/{m.group(1)}/")
    if duong.rstrip("/") == "/explore/search/keyword":
        q = (parse_qs(t.query).get("q", [""])[0] or "").strip()
        if not q or len(q) > TRAN_DO_DAI_TU_KHOA:
            return None
        if q.startswith("#"):
            return Dich("hashtag", _url_tu_khoa(q)) if _MAU_TAG.fullmatch(q[1:]) else None
        return Dich("keyword", _url_tu_khoa(q))
    m = _MAU_TAGS.fullmatch(duong)
    if m and _MAU_TAG.fullmatch(m.group(1)):
        return Dich("hashtag", _url_tu_khoa("#" + m.group(1)))      # ép sang dạng keyword `?q=%23tag`
    m = _MAU_PROFILE.fullmatch(duong)
    if m and m.group(1).lower() not in _DUONG_RIENG and _MAU_USER.fullmatch(m.group(1)):
        if loai != LOAI_VIDEO and not duong.rstrip("/").lower().endswith("/reels"):
            return Dich("profile", f"{BASE}/{m.group(1)}/")          # ảnh/cả hai: lưới bài
        return Dich("profile", f"{BASE}/{m.group(1)}/reels/")        # `/<user>/` ⇒ ép `/reels/`
    return None


def _url_tu_khoa(q: str) -> str:
    return f"{BASE}/explore/search/keyword/?q={quote(q, safe='')}"


def _mo_phien(cookies_path: str, proxy: str | None) -> PhienIG:
    """Điểm tiêm của test: trả context manager cho `TrangIG`."""
    return PhienIG(cookies_path, proxy=proxy)


class _PhienIGAnh(PhienIG):
    """`PhienIG` bắt thêm XHR lưới bài của profile (`TEN_GRAPHQL_ANH`). Chỉ dùng khi job xin ảnh/cả hai; chế độ video
    dùng `PhienIG` nguyên bản. Cùng cách bắt như lớp cha, chỉ khác bộ tên đích."""

    def _ghi_phan_hoi(self, r) -> None:
        try:
            req = r.request
            try:
                post = req.post_data or ""
            except Exception:  # noqa: BLE001 — thân nhị phân
                post = ""
            if ph.la_xhr_dich(r.url, post, gom_anh=True) is None:
                return
            try:
                body = r.body()
            except Exception:  # noqa: BLE001 — trang đóng giữa chừng / 429 không có thân
                body = b""
            self._xhr.append(ph.XhrDich(status=int(r.status), size=len(body),
                                        body=body.decode("utf-8", "replace")))
        except Exception as exc:  # noqa: BLE001
            log.warning("không đọc được một phản hồi IG (%s)", type(exc).__name__)


def _mo_phien_anh(cookies_path: str, proxy: str | None) -> PhienIG:
    """Điểm tiêm riêng cho job ảnh/cả hai (bắt thêm tên XHR lưới bài)."""
    return _PhienIGAnh(cookies_path, proxy=proxy)


class _PhienIGBai(PhienIG):
    """`PhienIG` có thêm đọc các `<script type="application/json">` của trang đang mở (link lẻ `/p/<mã>/`)."""

    def doc_script_json(self) -> list[str]:
        return self._page.eval_on_selector_all(
            'script[type="application/json"]', "els => els.map(e => e.textContent || '')")


def _mo_phien_bai(cookies_path: str, proxy: str | None) -> _PhienIGBai:
    """Điểm tiêm của test cho link lẻ."""
    return _PhienIGBai(cookies_path, proxy=proxy)


def ma_bai_le(url: str) -> str | None:
    """Mã bài của link `/p/<mã>/` Instagram, hoặc None. Không gọi mạng."""
    try:
        t = urlsplit(url.strip())
    except ValueError:
        return None
    if t.scheme not in ("http", "https") or (t.hostname or "").lower() not in _HOST_IG:
        return None
    m = _MAU_BAI_LE.fullmatch(t.path or "/")
    return m.group(1) if m else None


def doc_bai_link_le(url: str, *, cookies_path: str | None, proxy: str | None = None) -> VideoRef | None:
    """Link lẻ `/p/<mã>/` ⇒ `VideoRef(loai="anh")` (ảnh đơn hoặc carousel), hoặc None khi bài không còn / không phải
    bài ảnh (video đi đường yt-dlp). Mở bằng trình duyệt (`requests` thường không có node: đo I1) và bóc node đúng mã
    từ script JSON lúc tải. Cookie BẮT BUỘC: thiếu ⇒ `ValueError`; mất phiên/429/lỗi trình duyệt ⇒ `RuntimeError`
    (thông điệp chỉ có tên lớp/mã, không URL/handle/cookie)."""
    ma = ma_bai_le(url)
    if ma is None:
        raise ValueError("url không phải link bài Instagram /p/<mã>/")
    if not cookies_path or not Path(cookies_path).is_file():
        raise ValueError("link ảnh Instagram cần cookie IG")
    try:
        with _mo_phien_bai(cookies_path, proxy) as trang:
            nav = trang.mo(f"{BASE}/p/{ma}/")
            if nav == 429:
                raise RuntimeError(f"nguồn instagram: mất phiên [{ph.MP_HTTP_429}]")
            cuoi = trang.url_cuoi().lower()
            if "accounts/login" in cuoi or "challenge" in cuoi or "checkpoint" in cuoi:
                raise RuntimeError(f"nguồn instagram: mất phiên [{ph.MP_URL_DANG_NHAP}]")
            cac_script = trang.doc_script_json()
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 — thông điệp Playwright kèm URL: chỉ tên lớp đi tiếp
        raise RuntimeError(f"nguồn instagram: lỗi trình duyệt ({type(exc).__name__})") from None
    return ph.ref_anh_tu_script(cac_script, ma)


def tham_lai(ref: VideoRef, proxy: str | None = None, *, cookies_path: str | None = None) -> VideoRef | None:
    """Thăm lại bài để lấy URL ảnh mới (URL IG hết hạn ~104h, `probe I4`). Khớp `web.queue_anh.HamThamLai` khi chỉ
    truyền `(ref, proxy)`, NHƯNG cần cookie ⇒ người nối phải bọc để đưa `cookies_path` của job (xem báo cáo)."""
    return doc_bai_link_le(ref.url, cookies_path=cookies_path, proxy=proxy)


class InstagramHangLoat:
    """Profile reels / từ khoá / hashtag / audio của Instagram. Một job = MỘT URL; số video theo ô số lượng."""

    ten = "instagram_hang_loat"
    mo_ta_url = "Instagram: profile reels, từ khoá, hashtag, audio (cần cookie IG của tài khoản phụ)"

    def nhan(self, url: str) -> bool:
        return phan_tich_url(url) is not None

    def nen_tang(self, url: str) -> str:
        return "instagram"

    def loai_log(self, url: str) -> str:
        d = phan_tich_url(url)
        return f"instagram:{d.loai if d else 'khac'}"

    def loai_ho_tro(self, url: str) -> frozenset[str]:
        """Profile `/<user>/`, từ khoá, hashtag ⇒ cả ba loại; `/<user>/reels/`, audio ⇒ chỉ video."""
        d = phan_tich_url(url)
        if d is None or d.loai == "audio":
            return _CHI_VIDEO
        if d.loai == "profile" and urlsplit(url.strip()).path.rstrip("/").lower().endswith("/reels"):
            return _CHI_VIDEO
        return _CA_BA

    def liet_ke(self, url: str, *, max_videos: int, proxy: str | None = None,
                cookies_path: str | None = None,
                already_have: Callable[[list[str]], set[str]],
                on_skip: Callable[[VideoRef], None], on_stop: Callable[[str], None],
                cong=None, max_seconds: float | None = None, loai: str = LOAI_VIDEO,
                **_chua_dung) -> list[VideoRef]:
        if loai not in LOAI_HOP_LE:
            raise ValueError("loại tải không hợp lệ")
        if loai not in self.loai_ho_tro(url):
            raise ValueError("nguồn instagram: URL này chỉ tải được video")
        d = phan_tich_url(url, loai)
        if d is None:
            raise ValueError("url không phải nguồn Instagram hàng loạt")
        if not cookies_path:
            on_stop(STOP_IG_CHUA_CO_COOKIE)      # không bao giờ chạy ẩn danh
            return []
        if cong is not None:
            dung = cong.truoc_goi()              # mỗi lượt MỞ URL IG = một lượt pacer
            if dung:
                on_stop(dung)
                return []
        try:
            mo = _mo_phien if loai == LOAI_VIDEO else _mo_phien_anh
            with mo(cookies_path, proxy) as trang:
                kq = ig_quet_cuon.quet(trang, d.url, la_audio=d.loai == "audio", max_videos=max_videos,
                                       already_have=already_have, on_skip=on_skip, max_seconds=max_seconds,
                                       loai=loai)
        except Exception as exc:  # noqa: BLE001 — thông điệp Playwright/Chrome kèm URL (handle): chỉ tên lớp đi tiếp
            if cong is not None:
                cong.xu_ly_loi(exc)
            raise RuntimeError(f"nguồn instagram: lỗi trình duyệt ({type(exc).__name__})") from None
        if kq.mat_phien is not None:
            log.warning("instagram:%s: mất phiên [%s] sau %d XHR, %d lần cuộn",
                        d.loai, kq.mat_phien, kq.so_xhr, kq.so_cuon)
            on_stop(STOP_IG_MAT_PHIEN)
            return []
        if loai == LOAI_VIDEO:
            log.info("instagram:%s: %d video mới, %d đã có, %d carousel bỏ qua, %d XHR, %d lần cuộn",
                     d.loai, len(kq.refs), kq.so_da_co, kq.so_carousel, kq.so_xhr, kq.so_cuon)
        else:
            log.info("instagram:%s [%s]: %d mục mới, %d đã có, %d ảnh hỏng bỏ qua, %d XHR, %d lần cuộn",
                     d.loai, loai, len(kq.refs), kq.so_da_co, kq.so_anh_hong, kq.so_xhr, kq.so_cuon)
        on_stop(kq.ly_do)
        return kq.refs
