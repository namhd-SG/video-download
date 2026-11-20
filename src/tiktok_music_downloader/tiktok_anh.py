"""Bài ảnh TikTok (photo/slideshow): thăm một bài lấy danh sách URL ảnh, bóc ảnh từ feed trình duyệt.

Đo (xem kế hoạch tải ảnh): HTML `/@u/photo/<id>` KHÔNG mang scope `webapp.video-detail`, nhưng HTML
`/@u/video/<id>` của CÙNG bài có `itemInfo.itemStruct.imagePost.images[].imageURL.urlList` ẩn danh (không cookie,
không trình duyệt). Nên mọi lượt thăm đều đi `/video/<id>`, kể cả khi link nguồn là `/photo/`.

Module thuần: không import `web.*`, không throttle (người gọi lo nhịp), không ghi log URL/handle/id.
`tham_lai` đúng chữ ký `web.queue_anh.HamThamLai` để lớp web tự đăng ký.
"""
from __future__ import annotations

import json
import logging
import re

from tiktok_music_downloader.tai_anh_cau_hinh import (
    LOAI_ANH,
    LOAI_CA_HAI,
    LOAI_VIDEO,
    TIEN_TO_ID_ANH,
    TRAN_ANH_MOI_BAI,
    bai_id_anh,
)
from tiktok_music_downloader.utils import VideoRef, parse_photo_url, parse_video_url

log = logging.getLogger("ttmd")

# Mã `loai` lỗi phía nguồn, khớp `web.queue_anh.LOAI_LOI_NGUON` (khung xám) — queue không import module này.
LOAI_LOI_NGUON = "tiktok"
_UA_CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_TIMEOUT_GIAY = 25.0
# HTTP nghĩa là bài không cho xem/không còn (phía nguồn), khác lỗi mạng/máy chủ (phía ta, thử lại được).
_MA_HTTP_NGUON = frozenset({403, 404, 410, 429})

_MAU_SCRIPT = re.compile(
    r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)
_MAU_ID_SO = re.compile(r"\d{5,25}")
_MAU_BAI_ID_TT = re.compile(rf"{TIEN_TO_ID_ANH}tt-(\d+)$")


class LoiNguonTikTok(Exception):
    """Bài không xem được ở phía TikTok (gỡ/riêng tư/chặn): statusCode≠0, HTTP 403/404/410/429, thiếu scope,
    bài vượt trần ảnh. Queue xếp loại `tiktok` (`loai` = `LOAI_LOI_NGUON`), không phải lỗi hệ thống."""

    loai = LOAI_LOI_NGUON

    def __init__(self, ly_do: str, ma: int | None = None):
        super().__init__(ly_do)
        self.ma = ma


class LoiChanTikTok(Exception):
    """Thăm lại bài gặp dấu hiệu TikTok CHẶN/GIỚI HẠN (HTTP 403/429, trang không có dữ liệu bài) — khác "bài không
    còn": queue đếm số lần liên tiếp và dừng lượt `bi_chan` thay vì báo nhầm từng bài là đã gỡ."""


# HTTP 403/429 và trang trống dữ liệu (trang chặn/captcha) ⇒ chặn; 404/410/statusCode≠0 ⇒ bài không còn.
_MA_HTTP_CHAN = frozenset({403, 429})
_LY_DO_TRANG_CHAN = "trang không có dữ liệu bài"


def _id_bai(url_hoac_id: str) -> str:
    """Id số của bài từ id trần, link `/photo/<id>` hoặc `/video/<id>`; ngoài ra `ValueError`."""
    gia_tri = (url_hoac_id or "").strip()
    if _MAU_ID_SO.fullmatch(gia_tri):
        return gia_tri
    id_anh = parse_photo_url(gia_tri)
    if id_anh:
        return id_anh
    ref = parse_video_url(gia_tri)
    if ref is not None:
        return ref.video_id
    raise ValueError("không nhận ra id bài TikTok")


def ref_anh_tu_item(item: object) -> VideoRef | None:
    """Ref ảnh từ một `itemStruct`/mục feed TikTok có `imagePost`, hoặc None nếu không phải bài ảnh hợp lệ.

    Tất-cả-hoặc-không: một ảnh thiếu URL ⇒ None cả bài. Bài quá `TRAN_ANH_MOI_BAI` ảnh ⇒ None (bài lạ).
    `url` = `/@handle/photo/<id>` (handle thiếu ⇒ `_`; `tham_bai` chuẩn hoá về `/video/` khi thăm)."""
    if not isinstance(item, dict):
        return None
    bai = item.get("imagePost")
    id_bai = str(item.get("id") or "").strip()
    if not isinstance(bai, dict) or not _MAU_ID_SO.fullmatch(id_bai):
        return None
    anh = bai.get("images")
    if not isinstance(anh, list) or not anh or len(anh) > TRAN_ANH_MOI_BAI:
        return None
    moi_tep: list[tuple[str, ...]] = []
    for a in anh:
        ds = ((a or {}).get("imageURL") or {}).get("urlList") if isinstance(a, dict) else None
        urls = tuple(u for u in ds if isinstance(u, str) and u.startswith(("http://", "https://"))) \
            if isinstance(ds, list) else ()
        if not urls:
            return None
        moi_tep.append(urls)
    tac_gia = item.get("author")
    handle = ""
    if isinstance(tac_gia, dict):
        handle = str(tac_gia.get("uniqueId") or tac_gia.get("unique_id") or "").strip()
    elif isinstance(tac_gia, str):
        handle = tac_gia.strip()
    mo_ta = item.get("desc")
    return VideoRef(
        video_id=bai_id_anh("tt", id_bai),
        url=f"https://www.tiktok.com/@{handle or '_'}/photo/{id_bai}",
        title=mo_ta.strip() or None if isinstance(mo_ta, str) else None,
        author=handle or None,
        loai=LOAI_ANH,
        anh_urls=tuple(moi_tep),
        anh_kieu=("anh",) * len(moi_tep),
    )


def ref_anh_tu_feed(du_lieu: object, *, do_sau_toi_da: int = 6) -> dict[str, VideoRef]:
    """Gom mọi bài ảnh nằm ở bất kỳ đâu trong JSON feed (`itemList`, `data[].item`, …), khoá theo `bai_id`.
    Đi đệ quy có trần độ sâu: feed đổi bọc ngoài vẫn đọc được, không treo trên JSON lạ."""
    ra: dict[str, VideoRef] = {}

    def _di(nut: object, sau: int) -> None:
        if sau > do_sau_toi_da:
            return
        if isinstance(nut, dict):
            ref = ref_anh_tu_item(nut) if "imagePost" in nut else None
            if ref is not None:
                ra.setdefault(ref.video_id, ref)
                return
            for v in nut.values():
                if isinstance(v, (dict, list)):
                    _di(v, sau + 1)
        elif isinstance(nut, list):
            for v in nut:
                _di(v, sau + 1)

    _di(du_lieu, 0)
    return ra


def _tai_html(url: str, proxy: str | None) -> str:
    """GET trang bài; HTTP phía nguồn ⇒ `LoiNguonTikTok`, lỗi mạng/máy chủ khác ⇒ để requests ném (phía ta)."""
    import requests    # nhập trễ như `tai_anh`/`downloader`
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = requests.get(url, headers={"User-Agent": _UA_CHROME, "Accept-Language": "en-US,en;q=0.9"},
                     timeout=_TIMEOUT_GIAY, proxies=proxies)
    if r.status_code in _MA_HTTP_NGUON:
        raise LoiNguonTikTok(f"HTTP {r.status_code}", ma=r.status_code)
    r.raise_for_status()
    return r.text


def _item_struct(html: str) -> dict:
    """`webapp.video-detail.itemInfo.itemStruct` từ HTML; statusCode≠0/thiếu scope ⇒ `LoiNguonTikTok`."""
    m = _MAU_SCRIPT.search(html or "")
    if not m:
        raise LoiNguonTikTok("trang không có dữ liệu bài")
    try:
        goc = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise LoiNguonTikTok("dữ liệu bài không đọc được") from exc
    scope = (goc.get("__DEFAULT_SCOPE__") or {}) if isinstance(goc, dict) else {}
    chi_tiet = scope.get("webapp.video-detail") if isinstance(scope, dict) else None
    if not isinstance(chi_tiet, dict):
        raise LoiNguonTikTok("trang không có chi tiết bài")
    ma = chi_tiet.get("statusCode", 0)
    if ma != 0:
        raise LoiNguonTikTok(f"bài không xem được (statusCode={ma})", ma=ma if isinstance(ma, int) else None)
    item = (chi_tiet.get("itemInfo") or {}).get("itemStruct")
    if not isinstance(item, dict):
        raise LoiNguonTikTok("trang không có itemStruct")
    return item


def tham_bai(url_hoac_id: str, proxy: str | None = None) -> VideoRef:
    """Thăm một bài TikTok (id hoặc link `/photo/`, `/video/`) và phân loại: có `imagePost` ⇒ ref ảnh (đủ
    `anh_urls`), không ⇒ ref video thường. Luôn đi `/@_/video/<id>` (xem đầu module). Thuần: không throttle.

    Lỗi phía nguồn ⇒ `LoiNguonTikTok`; `ValueError` khi đầu vào không phải id/link bài; lỗi mạng ném nguyên."""
    id_bai = _id_bai(url_hoac_id)
    item = _item_struct(_tai_html(f"https://www.tiktok.com/@_/video/{id_bai}", proxy))
    if isinstance(item.get("imagePost"), dict):
        ref = ref_anh_tu_item({**item, "id": id_bai})
        if ref is None:
            n = len((item["imagePost"].get("images") or []))
            raise LoiNguonTikTok("bài ảnh quá nhiều ảnh" if n > TRAN_ANH_MOI_BAI else "bài ảnh thiếu URL ảnh")
        return ref
    tac_gia = item.get("author")
    handle = str(tac_gia.get("uniqueId") or "") if isinstance(tac_gia, dict) else ""
    return VideoRef(video_id=id_bai, url=f"https://www.tiktok.com/@{handle or '_'}/video/{id_bai}",
                    author=handle or None)


def tham_lai(ref: VideoRef, proxy: str | None = None) -> VideoRef | None:
    """Đúng chữ ký `web.queue_anh.HamThamLai`: thăm lại bài ảnh `ref` lấy URL mới. Bài không còn/không xem được/
    đã thành video ⇒ `None`; dấu hiệu chặn ⇒ `LoiChanTikTok`; lỗi mạng ném nguyên (queue tính là hụt phía ta)."""
    m = _MAU_BAI_ID_TT.match(ref.video_id or "")
    if not m:
        raise ValueError("bai_id không phải bài ảnh TikTok")
    try:
        moi = tham_bai(m.group(1), proxy)
    except LoiNguonTikTok as exc:
        if exc.ma in _MA_HTTP_CHAN or str(exc) == _LY_DO_TRANG_CHAN:
            log.warning("thăm lại bài ảnh TikTok: dấu hiệu chặn (%s)", exc.ma if exc.ma is not None else "trang chặn")
            raise LoiChanTikTok(f"TikTok chặn/giới hạn ({exc.ma if exc.ma is not None else 'trang chặn'})") from None
        log.warning("thăm lại bài ảnh TikTok: phía nguồn (%s)", exc.ma if exc.ma is not None else "khác")
        return None
    return moi if moi.loai == LOAI_ANH else None


def liet_ke_link_le(url: str, *, loai: str, proxy: str | None = None) -> list[VideoRef]:
    """Link lẻ TikTok (`/photo/<id>` hoặc `/video/<id>`) → 0 hoặc 1 ref theo `loai`: `anh` chỉ nhận bài ảnh,
    `video` chỉ nhận bài video, `ca_hai` nhận cả hai. Lệch loại ⇒ `[]` (người gọi báo "link này là <loại khác>").
    Lỗi phía nguồn ném `LoiNguonTikTok`; link không phải bài ⇒ `ValueError`."""
    if loai not in (LOAI_VIDEO, LOAI_ANH, LOAI_CA_HAI):
        raise ValueError(f"loai không hợp lệ: {loai!r}")
    ref = tham_bai(url, proxy)
    if loai != LOAI_CA_HAI and ref.loai != loai:
        return []
    return [ref]
