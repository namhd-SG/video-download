"""Phân tích phản hồi XHR của Instagram — hàm THUẦN, không mạng, không trình duyệt.

Số đo thật (18/11/2026, `plans/reports/do-261118-1610-r08-m3-buoc0-ig-xhr.md` ở checkout chính):
  · profile reels / keyword / hashtag: POST `/graphql/query` hoặc `/api/graphql`, tên `fb_api_req_friendly_name`
    chứa `ProfileReelsTab` / `KeywordSearchExplorePage`; phân trang `page_info.end_cursor` + `has_next_page`.
  · audio: POST `/api/v1/clips/music/`, thân có tiền tố chống JSON-hijack `for (;;);`; phân trang
    `paging_info.max_id` + `more_available`.
  · node media: dict có `code` (str) + `media_type` (1 ảnh, 2 video, 8 carousel). CHỈ lấy 2.

Module này không có dữ liệu thật: mã ở test là mã giả. Không hàm nào ghi log (URL/handle/mã không được vào log).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

TIEN_TO_CHONG_HIJACK = "for (;;);"
MEDIA_ANH, MEDIA_VIDEO, MEDIA_CAROUSEL = 1, 2, 8
# Mã bài IG: chữ-số, gạch dưới, gạch nối. Chặn mã lạ trước khi ghép vào URL tải / tên tệp.
_MAU_MA_BAI = re.compile(r"[A-Za-z0-9_\-]{5,30}")
TEN_GRAPHQL_DICH = {"ProfileReelsTab": "profile", "KeywordSearchExplorePage": "keyword"}
DUONG_AUDIO = "/api/v1/clips/music/"
DUONG_GRAPHQL = ("/graphql/query", "/api/graphql")

# Ngưỡng "phản hồi rỗng": phản hồi đăng xuất đo được chỉ 125 B; trang thật nhỏ nhất đo được 5 KB.
NGUONG_XHR_NHO_BYTE = 1024

# Mã dấu mất phiên (ĐÓNG): thứ duy nhất đi ra log/DB, không bao giờ là nội dung trang.
MP_URL_DANG_NHAP = "url_dang_nhap"
MP_XHR_LOI = "xhr_loi"
MP_XHR_NHO = "xhr_nho"
MP_DOM_DANG_NHAP = "dom_dang_nhap"
MP_KHONG_XHR_DICH = "khong_xhr_dich"
MP_HTTP_429 = "http_429"


@dataclass(frozen=True)
class XhrDich:
    """Một phản hồi XHR đích đã bắt: mã HTTP, số byte thân, thân dạng chữ (có thể còn tiền tố `for (;;);`)."""
    status: int
    size: int
    body: str


@dataclass(frozen=True)
class DauDom:
    """Dấu đọc từ DOM (trình duyệt tự đo): chỉ cờ đúng/sai, không chứa chữ của trang."""
    co_o_ten_dang_nhap: bool = False   # có `input[name=username]`
    co_nut_dang_nhap: bool = False     # nút/liên kết có chữ "Log in" / "Đăng nhập"
    tieu_de_loi: bool = False          # title "Page couldn't load"
    chu_loi: bool = False              # chữ "Something went wrong"


@dataclass(frozen=True)
class Phan:
    """Một đợt đọc phân trang: còn trang sau không, và con trỏ (chỉ để đối chiếu test, không dùng gọi mạng)."""
    con_trang: bool
    con_tro: str | None


def bo_tien_to(body: str) -> str:
    """Bỏ tiền tố `for (;;);` (và khoảng trắng đầu) của phản hồi REST IG trước khi parse JSON."""
    s = body.lstrip()
    if s.startswith(TIEN_TO_CHONG_HIJACK):
        s = s[len(TIEN_TO_CHONG_HIJACK):]
    return s


def doc_json(body: str):
    """JSON của thân XHR (đã bóc tiền tố), hoặc None nếu không phải JSON."""
    try:
        return json.loads(bo_tien_to(body))
    except (ValueError, TypeError):
        return None


def la_xhr_dich(url: str, post_data: str | None) -> str | None:
    """Loại XHR đích ("profile" | "keyword" | "audio") hay None nếu không phải thứ ta cần bắt."""
    try:
        duong = urlsplit(url).path
    except ValueError:
        return None
    if duong.rstrip("/") == DUONG_AUDIO.rstrip("/"):
        return "audio"
    if duong.rstrip("/") in DUONG_GRAPHQL and post_data:
        ten = parse_qs(post_data).get("fb_api_req_friendly_name", [""])[0]
        for khoa, loai in TEN_GRAPHQL_DICH.items():
            if khoa in ten:
                return loai
    return None


def duyet_node_media(goc) -> list[dict]:
    """Mọi node media (dict có `code` str + `media_type`) trong JSON, theo thứ tự gặp. Không đi vào TRONG một node
    media đã nhận: con của carousel không có `code` riêng và không được đếm lần hai."""
    ra: list[dict] = []
    ngan_xep = [goc]
    while ngan_xep:
        o = ngan_xep.pop()
        if isinstance(o, dict):
            if isinstance(o.get("code"), str) and "media_type" in o:
                ra.append(o)
                continue
            ngan_xep.extend(reversed(list(o.values())))
        elif isinstance(o, list):
            ngan_xep.extend(reversed(o))
    return ra


def _chuoi_ngan(v, toi_da: int) -> str | None:
    return v.strip()[:toi_da] or None if isinstance(v, str) else None


def tom_tat_node(node: dict) -> dict:
    """Thông tin cho thư viện từ node video: tác giả và mô tả (cắt ngắn), đều tuỳ chọn."""
    chu = node.get("user") or node.get("owner")
    cap = node.get("caption")
    return {"author": _chuoi_ngan(chu.get("username"), 100) if isinstance(chu, dict) else None,
            "title": _chuoi_ngan(cap.get("text"), 200) if isinstance(cap, dict) else None}


def loc_video(nodes: list[dict]) -> tuple[list[dict], int]:
    """`(node video theo thứ tự không trùng mã, số carousel)`. CHỈ `media_type == 2` được giữ; carousel
    (8) — kể cả carousel có con video — không tải, chỉ đếm số; ảnh (1) bị bỏ."""
    thay: set[str] = set()
    video: list[dict] = []
    carousel: set[str] = set()
    for n in nodes:
        ma = n["code"]
        if not _MAU_MA_BAI.fullmatch(ma):
            continue
        if n.get("media_type") == MEDIA_CAROUSEL:
            carousel.add(ma)
        elif n.get("media_type") == MEDIA_VIDEO and ma not in thay:
            thay.add(ma)
            video.append(n)
    return video, len(carousel)


def doc_phan_trang(goc) -> Phan | None:
    """`page_info` (`has_next_page`, `end_cursor`) hoặc `paging_info` (`more_available`, `max_id`) đầu tiên tìm
    được trong JSON; không có ⇒ None (đừng suy ra 'hết trang' từ chỗ không có dấu)."""
    ngan_xep = [goc]
    while ngan_xep:
        o = ngan_xep.pop()
        if isinstance(o, dict):
            pi = o.get("page_info")
            if isinstance(pi, dict) and "has_next_page" in pi:
                return Phan(bool(pi.get("has_next_page")), _chuoi_ngan(pi.get("end_cursor"), 80))
            pg = o.get("paging_info")
            if isinstance(pg, dict) and "more_available" in pg:
                return Phan(bool(pg.get("more_available")), _chuoi_ngan(str(pg.get("max_id") or ""), 80))
            ngan_xep.extend(o.values())
        elif isinstance(o, list):
            ngan_xep.extend(o)
    return None


def _xhr_bao_loi(x: XhrDich) -> bool:
    """JSON có khoá `errors` (vd mã 1675002 "Unauthorized logged out query.") hoặc `require_login`."""
    j = doc_json(x.body)
    return isinstance(j, dict) and (bool(j.get("errors")) or j.get("require_login") is True)


def phan_loai_mat_phien(url_cuoi: str, xhr: list[XhrDich], dom: DauDom, *, la_audio: bool,
                        da_cho_du_xhr: bool) -> str | None:
    """Mã dấu mất phiên (một trong `MP_*`) hoặc None nếu chưa thấy dấu nào. Thứ tự: dấu 1, 5, 2, 3, 4.

    1. URL cuối chứa `accounts/login` / `challenge` / `checkpoint`.
    5. HTTP 429 trên XHR đích.
    2. XHR đích có `errors`, hoặc MỌI XHR đích đều < 1 KB (trang thật ≥ 5 KB). Không áp cho audio: lượt cuối
       của audio có thể rất nhỏ mà hợp lệ, và audio không cookie vẫn ra dữ liệu.
    3. DOM: ô tên đăng nhập, nút "Log in"/"Đăng nhập", title "Page couldn't load", chữ "Something went wrong".
    4. Trang không phải audio mà sau tải + cuộn (`da_cho_du_xhr`) vẫn 0 XHR đích.
    """
    duong = url_cuoi.lower()
    if "accounts/login" in duong or "challenge" in duong or "checkpoint" in duong:
        return MP_URL_DANG_NHAP
    if any(x.status == 429 for x in xhr):
        return MP_HTTP_429
    if not la_audio and xhr:
        if any(_xhr_bao_loi(x) for x in xhr):
            return MP_XHR_LOI
        if all(x.size < NGUONG_XHR_NHO_BYTE for x in xhr):
            return MP_XHR_NHO
    if dom.co_o_ten_dang_nhap or dom.co_nut_dang_nhap or dom.tieu_de_loi or dom.chu_loi:
        return MP_DOM_DANG_NHAP
    if not la_audio and not xhr and da_cho_du_xhr:
        return MP_KHONG_XHR_DICH
    return None
