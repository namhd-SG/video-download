"""Khung dựng chung cho test Instagram hàng loạt: payload TỰ DỰNG (mã giả, không object user/tên/caption thật) và trang giả.

Cấu trúc bám số đo bước 0: graphql có `page_info.{has_next_page,end_cursor}`, audio có tiền tố `for (;;);` và
`paging_info.{max_id,more_available}`; node media = dict có `code` + `media_type` (1 ảnh, 2 video, 8 carousel).
Không có mạng, không trình duyệt: `TrangGia` cài `TrangIG`.
"""
from __future__ import annotations

import json

from tiktok_music_downloader import ig_xhr_phan_tich as ph

PAD = "x" * 1500        # phản hồi thật ≥ 5 KB; node nhỏ phải đệm để không dính ngưỡng "XHR < 1 KB"
URL_PROFILE = "https://www.instagram.com/ten.gia/reels/"
URL_AUDIO = "https://www.instagram.com/reels/audio/1485893805770596/"


def ma(i: int, tien="V") -> str:
    """Mã bài giả, hợp `_MAU_MA_BAI` (≥5 ký tự chữ-số)."""
    return f"{tien}{i:07d}"


def node(code: str, media_type: int = 2, **them) -> dict:
    return {"code": code, "media_type": media_type, **them}


def carousel(code: str, co_video: bool = False) -> dict:
    return node(code, 8, carousel_media=[{"media_type": 2 if co_video else 1, "id": "1"}])


def thanh_gia(nodes: list[dict], *, con_trang: bool = True, con_tro: str | None = "CUR", pad: bool = True) -> str:
    """Thân graphql (ProfileReels/Keyword): edges → node → media, kèm page_info."""
    j = {"data": {"conn": {"edges": [{"node": {"media": n}} for n in nodes],
                           "page_info": {"has_next_page": con_trang, "end_cursor": con_tro}}}}
    if pad:
        j["extensions"] = {"pad": PAD}
    return json.dumps(j)


def thanh_audio(nodes: list[dict], *, con_trang: bool = True, max_id: str | None = "MID") -> str:
    """Thân REST audio: có tiền tố `for (;;);`."""
    j = {"items": [{"media": n} for n in nodes], "paging_info": {"max_id": max_id, "more_available": con_trang},
         "pad": PAD}
    return ph.TIEN_TO_CHONG_HIJACK + json.dumps(j)


def xhr(body: str, status: int = 200) -> ph.XhrDich:
    return ph.XhrDich(status=status, size=len(body.encode()), body=body)


def dot(nodes: list[dict], **kw) -> list[ph.XhrDich]:
    """Một đợt XHR mới (một phản hồi graphql)."""
    return [xhr(thanh_gia(nodes, **kw))]


class TrangGia:
    """`TrangIG` theo kịch bản: lần `lay_xhr` thứ k trả `kich_ban[k]` (hết kịch bản ⇒ rỗng). Ghi lại số lần cuộn/URL mở."""

    def __init__(self, kich_ban: list[list[ph.XhrDich]], *, url_cuoi: str = URL_PROFILE, nav: int | None = 200,
                 dom: ph.DauDom | None = None, url_theo_lan: dict[int, str] | None = None,
                 dom_theo_lan: dict[int, ph.DauDom] | None = None):
        self.kich_ban, self.nav = list(kich_ban), nav
        self._url, self._dom = url_cuoi, dom or ph.DauDom()
        self.url_theo_lan, self.dom_theo_lan = url_theo_lan or {}, dom_theo_lan or {}
        self.da_mo: list[str] = []
        self.so_cuon = 0
        self._k = 0

    def mo(self, url):
        self.da_mo.append(url)
        return self.nav

    def cuon(self):
        self.so_cuon += 1

    def lay_xhr(self):
        k, self._k = self._k, self._k + 1
        return self.kich_ban[k] if k < len(self.kich_ban) else []

    def url_cuoi(self):
        return self.url_theo_lan.get(self._k - 1, self._url)

    def dau_dom(self):
        return self.dom_theo_lan.get(self._k - 1, self._dom)


class PhienGia:
    """Context manager thay `nguon_instagram._mo_phien`: trả `TrangGia`; ghi lại jar đã được đưa vào."""

    def __init__(self, trang: TrangGia | None = None, loi: Exception | None = None):
        self.trang, self.loi = trang, loi
        self.jar_da_dung: list[str] = []
        self.so_lan_mo = 0

    def __call__(self, cookies_path, proxy):
        self.jar_da_dung.append(cookies_path)
        self.so_lan_mo += 1
        return self

    def __enter__(self):
        if self.loi is not None:
            raise self.loi
        return self.trang

    def __exit__(self, *_a):
        return False


def nhieu_dot(so_dot: int, moi_dot: int, *, tu: int = 0, anh_moi_dot: int = 0) -> list[list[ph.XhrDich]]:
    """`so_dot` đợt, mỗi đợt `moi_dot` video mã tăng dần (+ `anh_moi_dot` ảnh); đợt cuối `has_next_page=False`."""
    ra = []
    for d in range(so_dot):
        a = tu + d * moi_dot
        nodes = [node(ma(a + i)) for i in range(moi_dot)] + [node(ma(a + i, "I"), 1) for i in range(anh_moi_dot)]
        ra.append(dot(nodes, con_trang=d < so_dot - 1))
    return ra
