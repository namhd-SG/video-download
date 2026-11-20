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

from tiktok_music_downloader.tai_anh_cau_hinh import LOAI_ANH, TRAN_ANH_MOI_BAI, bai_id_anh
from tiktok_music_downloader.utils import VideoRef

TIEN_TO_CHONG_HIJACK = "for (;;);"
MEDIA_ANH, MEDIA_VIDEO, MEDIA_CAROUSEL = 1, 2, 8
# Mã bài IG: chữ-số, gạch dưới, gạch nối. Chặn mã lạ trước khi ghép vào URL tải / tên tệp.
_MAU_MA_BAI = re.compile(r"[A-Za-z0-9_\-]{5,30}")
TEN_GRAPHQL_DICH = {"ProfileReelsTab": "profile", "KeywordSearchExplorePage": "keyword"}
# Tên XHR của lưới bài `/<user>/` (ảnh + carousel + reel chung một luồng; đo ở `probe-results.md` I2/I7). CHỈ bắt khi
# job xin ảnh/cả hai: chế độ video giữ bộ tên cũ ⇒ y hệt hôm nay. `PolarisProfilePostsTabContentQuery` khớp-chứa-chuỗi
# nên phủ cả biến thể `…_connection`.
TEN_GRAPHQL_ANH = {"PolarisProfilePostsTabContentQuery": "profile", "PolarisProfilePostsQuery": "profile"}
URL_BAI = "https://www.instagram.com/p/{}/"
# Mỗi tệp giữ tối đa từng ấy URL (lớn nhất trước, còn lại là dự phòng khi một host timeout).
TRAN_URL_DU_PHONG = 3
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


def la_xhr_dich(url: str, post_data: str | None, *, gom_anh: bool = False) -> str | None:
    """Loại XHR đích ("profile" | "keyword" | "audio") hay None nếu không phải thứ ta cần bắt. `gom_anh` (job ảnh/cả
    hai) bắt thêm tên XHR lưới bài của profile (`TEN_GRAPHQL_ANH`); mặc định False ≡ hôm nay."""
    try:
        duong = urlsplit(url).path
    except ValueError:
        return None
    if duong.rstrip("/") == DUONG_AUDIO.rstrip("/"):
        return "audio"
    if duong.rstrip("/") in DUONG_GRAPHQL and post_data:
        ten = parse_qs(post_data).get("fb_api_req_friendly_name", [""])[0]
        bang = {**TEN_GRAPHQL_DICH, **TEN_GRAPHQL_ANH} if gom_anh else TEN_GRAPHQL_DICH
        for khoa, loai in bang.items():
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


def _url_ung_vien(muc: dict) -> tuple[str, ...]:
    """URL ảnh của một mục (node bài ảnh hoặc con của carousel): `image_versions2.candidates` từ lớn đến nhỏ
    (theo diện tích), bỏ URL trùng/rỗng, cắt `TRAN_URL_DU_PHONG`. Không có ⇒ ()."""
    iv = muc.get("image_versions2")
    cands = iv.get("candidates") if isinstance(iv, dict) else None
    if not isinstance(cands, list):
        return ()

    def dien_tich(c) -> int:
        w, h = c.get("width"), c.get("height")
        return (w if isinstance(w, int) else 0) * (h if isinstance(h, int) else 0)

    co_url = [c for c in cands if isinstance(c, dict) and isinstance(c.get("url"), str) and c["url"]]
    ra: list[str] = []
    for c in sorted(co_url, key=dien_tich, reverse=True):      # sort ổn định: hoà diện tích giữ thứ tự gốc
        if c["url"] not in ra:
            ra.append(c["url"])
    return tuple(ra[:TRAN_URL_DU_PHONG])


def _url_video_con(muc: dict) -> tuple[str, ...]:
    """URL con-video của carousel: `video_versions[0].url` đầu, các bản còn lại làm dự phòng."""
    vv = muc.get("video_versions")
    if not isinstance(vv, list):
        return ()
    ra = [v["url"] for v in vv if isinstance(v, dict) and isinstance(v.get("url"), str) and v["url"]]
    return tuple(dict.fromkeys(ra))[:TRAN_URL_DU_PHONG]


def tep_cua_node(node: dict) -> list[tuple[tuple[str, ...], str]]:
    """Các tệp của MỘT bài ảnh theo thứ tự: `[(urls_du_phong, "anh"|"video"), …]`. Ảnh đơn (1) = 1 tệp; carousel (8) =
    mỗi con một tệp (con ảnh lấy candidate lớn nhất, con video lấy `video_versions[0]`). Bất kỳ con nào thiếu URL
    ⇒ `[]` (một bộ ảnh thiếu tệp là bộ sai: bỏ cả bài, không tải nửa chừng)."""
    mt = node.get("media_type")
    if mt == MEDIA_ANH:
        u = _url_ung_vien(node)
        return [(u, "anh")] if u else []
    if mt != MEDIA_CAROUSEL:
        return []
    con = node.get("carousel_media")
    if not isinstance(con, list) or not con:
        return []
    ra: list[tuple[tuple[str, ...], str]] = []
    for c in con:
        if not isinstance(c, dict):
            return []
        if c.get("media_type") == MEDIA_VIDEO:
            u, kieu = _url_video_con(c), "video"
        elif c.get("media_type") == MEDIA_ANH:
            u, kieu = _url_ung_vien(c), "anh"
        else:
            return []
        if not u:
            return []
        ra.append((u, kieu))
    return ra


def ref_anh_tu_node(node: dict) -> VideoRef | None:
    """`VideoRef(loai="anh")` của một bài ảnh/carousel (`video_id` = `anh-ig-<mã>`; 1 carousel = 1 ref) hoặc None khi
    mã sai hình / thiếu URL / vượt trần tệp."""
    ma = node.get("code")
    if not isinstance(ma, str) or not _MAU_MA_BAI.fullmatch(ma):
        return None
    tep = tep_cua_node(node)
    if not tep or len(tep) > TRAN_ANH_MOI_BAI:
        return None
    tt = tom_tat_node(node)
    return VideoRef(video_id=bai_id_anh("ig", ma), url=URL_BAI.format(ma), title=tt["title"], author=tt["author"],
                    loai=LOAI_ANH, anh_urls=tuple(u for u, _ in tep), anh_kieu=tuple(k for _, k in tep))


def loc_anh(nodes: list[dict]) -> tuple[list[dict], int]:
    """`(node ảnh/carousel đủ URL theo thứ tự không trùng mã, số bài ảnh/carousel bị bỏ vì thiếu URL/sai hình)`.
    Giữ `media_type` 1 và 8; video (2) bị bỏ. Carousel là MỘT bài dù có bao nhiêu con (kể cả con video)."""
    thay: set[str] = set()
    ra: list[dict] = []
    hong = 0
    for n in nodes:
        if n.get("media_type") not in (MEDIA_ANH, MEDIA_CAROUSEL) or n["code"] in thay:
            continue
        thay.add(n["code"])
        if ref_anh_tu_node(n) is None:
            hong += 1
        else:
            ra.append(n)
    return ra, hong


def loc_ca_hai(nodes: list[dict]) -> tuple[list[tuple[str, dict]], int]:
    """Cho `ca_hai`: `([("video"|"anh", node), …] theo thứ tự gặp không trùng mã, số bài ảnh hỏng)`. Video = `loc_video`,
    ảnh/carousel = `loc_anh`; hai bộ lọc chạy trên CÙNG danh sách nên thứ tự lưới được giữ."""
    video, _ = loc_video(nodes)
    anh, hong = loc_anh(nodes)
    la_video = {n["code"] for n in video}
    la_anh = {n["code"] for n in anh}
    gop = [("video" if n["code"] in la_video else "anh", n) for n in nodes
           if n["code"] in la_video | la_anh]
    thay: set[str] = set()
    ra = []
    for loai, n in gop:
        if n["code"] not in thay:
            thay.add(n["code"])
            ra.append((loai, n))
    return ra, hong


def ref_anh_tu_script(cac_script: list[str], ma: str) -> VideoRef | None:
    """Link lẻ `/p/<mã>/`: trong các `<script type="application/json">` lúc tải, tìm node ĐÚNG mã `ma` (bài khác
    — gợi ý, feed — nằm chung trang nên KHÔNG lấy theo vị trí) rồi dựng ref ảnh. Node đúng mã mà thiếu URL thì thử
    node cùng mã khác (một mã có thể xuất hiện ở nhiều script, bản đầy đủ không nhất thiết đứng đầu). Không có ⇒ None."""
    if not _MAU_MA_BAI.fullmatch(ma):
        return None
    for chu in cac_script:
        goc = doc_json(chu)
        if goc is None:
            continue
        for n in duyet_node_media(goc):
            if n["code"] == ma and n.get("media_type") in (MEDIA_ANH, MEDIA_CAROUSEL):
                ref = ref_anh_tu_node(n)
                if ref is not None:
                    return ref
    return None


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
