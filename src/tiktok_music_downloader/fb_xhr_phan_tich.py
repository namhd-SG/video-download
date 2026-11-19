"""Bóc mã video của trang Facebook (tab /videos, /reels) — hàm THUẦN, không mạng, không trình duyệt.

Số đo thật (18/11/2026, không cookie, `plans/reports/do-261118-r09-fb-page-buoc0.md` ở checkout chính):
  · mã nằm ở HAI nơi: thẻ `<script type="application/json">` lúc tải trang, và thân XHR `/api/graphql` (phân trang).
    Thân XHR có thể NHIỀU DÒNG, mỗi dòng một object JSON (dòng sau là mảnh `@defer`).
  · tab /videos: nút `Video` ở `<container>.edges[].node` với container ∈ `CONTAINER_VIDEOS`, cộng nút trực tiếp
    `channel_tab_popular_video` (thẻ "Most popular" — thuộc tab thật, không mang `__typename`).
  · tab /reels: `aggregated_fb_shorts.edges[].profile_reel_node.node.attachments[].media`.
  · mọi nút có `owner.id`; id chủ page chiếm đa số trong lượt (lọc ở `fb_quet_cuon`).

KHÔNG quét regex phẳng toàn trang: regex phẳng thấy cả video của bình luận / quảng cáo / gợi ý. Ở đây chỉ nút nằm đúng
đường dẫn container mới được nhận. Module không ghi log (mã video / URL không được vào log).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

# Chỉ bắt XHR của các truy vấn dưới đây; loại `useInstreamAdsHaloFetcherQuery` (quảng cáo) và
# `CometChannelTabVideoPreviewRootQuery` (xem trước một video, không phải danh sách tab).
TEN_GRAPHQL_DICH = frozenset({
    "CometProfilePlusVideosRootQuery",
    "PagesCometChannelTabAllVideosCardImplPaginationQuery",
    "ProfileCometTopAppSectionQuery",
    "ProfileCometAppCollectionReelsRendererPaginationQuery",
})
DUONG_GRAPHQL = "/api/graphql"
CONTAINER_VIDEOS = ("all_videos", "latest_videos", "series_videos", "video_list_videos")
CONTAINER_TRUC_TIEP = "channel_tab_popular_video"
CONTAINER_REELS = "aggregated_fb_shorts"
# Id video Facebook: chuỗi số. Chặn id lạ trước khi ghép vào URL tải / tên tệp.
_MAU_MA = re.compile(r"\d{5,25}")
_KHOA_THOI_LUONG_GIAY = ("length_in_second", "playable_duration")      # giây (có thể thập phân)
_KHOA_THOI_LUONG_MS = "playable_duration_in_ms"
_TRAN_DO_SAU_TIM_GIAY = 8


@dataclass(frozen=True)
class XhrFB:
    """Một phản hồi XHR đích đã bắt: mã HTTP và thân dạng chữ (có thể nhiều dòng JSON)."""
    status: int
    body: str


@dataclass(frozen=True)
class NutVideo:
    ma: str
    owner: str
    giay: int | None        # thời lượng nếu nút mang; None = đo sau tải


@dataclass
class KetQuaBoc:
    nut: list[NutVideo] = field(default_factory=list)
    con_trang: bool | None = None       # None = không thấy `page_info` nào
    so_thieu_owner: int = 0             # nút Video không có owner.id ⇒ bỏ (chỉ đếm)


def ten_xhr_dich(url: str, post_data: str | None, ten_header: str | None = None) -> str | None:
    """Tên truy vấn nếu là XHR `/api/graphql` thuộc whitelist, ngược lại None. Tên lấy từ `fb_api_req_friendly_name`
    của thân form, hoặc từ header `x-fb-friendly-name` khi thân không có."""
    try:
        duong = urlsplit(url).path
    except ValueError:
        return None
    if duong.rstrip("/") != DUONG_GRAPHQL:
        return None
    ten = parse_qs(post_data or "").get("fb_api_req_friendly_name", [""])[0] or (ten_header or "")
    return ten if ten in TEN_GRAPHQL_DICH else None


def doc_nhieu_dong(body: str) -> list:
    """Mọi object JSON của thân (một dòng một object); dòng không phải JSON bị bỏ. Thân một khối JSON cũng đúng."""
    ra = []
    for dong in (body or "").splitlines():
        dong = dong.strip()
        if not dong:
            continue
        try:
            ra.append(json.loads(dong))
        except ValueError:
            continue
    return ra


def doc_script_json(texts: list[str]) -> list:
    """`json.loads` từng nội dung thẻ `<script type="application/json">`; thẻ không phải JSON hợp lệ bị bỏ."""
    ra = []
    for t in texts:
        try:
            ra.append(json.loads(t))
        except (ValueError, TypeError):
            continue
    return ra


def _owner_id(nut: dict) -> str | None:
    o = nut.get("owner")
    oid = o.get("id") if isinstance(o, dict) else None
    return oid if isinstance(oid, str) and oid else None


def _thoi_luong(nut: dict) -> int | None:
    """Thời lượng (giây) của nút: khoá giây trước, rồi mili-giây; tìm trong cây con tới độ sâu giới hạn."""
    hang = [(nut, 0)]
    while hang:
        o, d = hang.pop(0)
        if isinstance(o, dict):
            for k in _KHOA_THOI_LUONG_GIAY:
                if isinstance(o.get(k), (int, float)) and not isinstance(o.get(k), bool) and o[k] > 0:
                    return int(o[k])
            ms = o.get(_KHOA_THOI_LUONG_MS)
            if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0:
                return int(ms / 1000)
            if d < _TRAN_DO_SAU_TIM_GIAY:
                hang.extend((v, d + 1) for v in o.values() if isinstance(v, (dict, list)))
        elif isinstance(o, list) and d < _TRAN_DO_SAU_TIM_GIAY:
            hang.extend((v, d + 1) for v in o)
    return None


def _nut(o, ket: KetQuaBoc, *, can_typename: bool = True) -> None:
    """Nhận `o` là nút Video hợp lệ (id số, `__typename == "Video"` nếu bắt buộc, có owner.id) vào kết quả."""
    if not isinstance(o, dict):
        return
    ma = o.get("id")
    if not isinstance(ma, str) or not _MAU_MA.fullmatch(ma):
        return
    tn = o.get("__typename")
    if tn != "Video" and (can_typename or tn is not None):
        return
    oid = _owner_id(o)
    if oid is None:
        ket.so_thieu_owner += 1
        return
    ket.nut.append(NutVideo(ma, oid, _thoi_luong(o)))


def _con_trang(container: dict, ket: KetQuaBoc) -> None:
    pi = container.get("page_info")
    if isinstance(pi, dict) and "has_next_page" in pi:
        # Nhiều container: còn trang nếu CÓ container nào còn (latest_videos có thể còn khi all_videos đã hết).
        ket.con_trang = bool(pi.get("has_next_page")) or bool(ket.con_trang)


def _doc_container_videos(container, ket: KetQuaBoc) -> None:
    if not isinstance(container, dict) or not isinstance(container.get("edges"), list):
        return
    for e in container["edges"]:
        _nut(e.get("node") if isinstance(e, dict) else None, ket)
    _con_trang(container, ket)


def _doc_container_reels(container, ket: KetQuaBoc) -> None:
    if not isinstance(container, dict) or not isinstance(container.get("edges"), list):
        return
    for e in container["edges"]:
        node = ((e.get("profile_reel_node") or {}).get("node") or {}) if isinstance(e, dict) else {}
        att = node.get("attachments") if isinstance(node, dict) else None
        for a in att if isinstance(att, list) else []:
            _nut(a.get("media") if isinstance(a, dict) else None, ket)
    _con_trang(container, ket)


def boc_nut(goc_json: list, tab: str) -> KetQuaBoc:
    """Nút video + trạng thái phân trang trong các JSON đã parse. `tab` = "videos" | "reels". Duyệt cả cây nhưng
    CHỈ nhận nút ở đường dẫn container của tab; nút trùng mã trong một lần gọi chỉ giữ một."""
    ket = KetQuaBoc()
    ngan_xep = list(reversed(goc_json))
    while ngan_xep:
        o = ngan_xep.pop()
        if isinstance(o, dict):
            if tab == "reels":
                _doc_container_reels(o.get(CONTAINER_REELS), ket)
            else:
                for ten in CONTAINER_VIDEOS:
                    _doc_container_videos(o.get(ten), ket)
                _nut(o.get(CONTAINER_TRUC_TIEP), ket, can_typename=False)
            ngan_xep.extend(reversed(list(o.values())))
        elif isinstance(o, list):
            ngan_xep.extend(reversed(o))
    thay: set[str] = set()
    ket.nut = [n for n in ket.nut if not (n.ma in thay or thay.add(n.ma))]
    return ket
