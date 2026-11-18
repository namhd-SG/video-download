"""Khung dựng chung cho test Facebook page hàng loạt: payload TỰ DỰNG nhỏ (mã giả, không tên page/caption/URL media thật)
và trang giả. Cấu trúc bám đường dẫn đo được ở `plans/261118-1839-r09-fb-trang-hang-loat/plan.md` §5:

  · /videos: `data.<all_videos|latest_videos|…>.edges[].node` (nút `Video` + `owner.id`; thời lượng nằm sâu trong
    `channel_tab_thumbnail_renderer…target.playable_duration_in_ms`) + `channel_tab_popular_video` (không `__typename`).
  · /reels: `data.node.aggregated_fb_shorts.edges[].profile_reel_node.node.attachments[].media`.
  · XHR nhiều dòng JSON: dòng sau là mảnh `@defer` mang video lạ ngoài đường dẫn container.

Không mạng, không trình duyệt: `TrangGia` cài `TrangFB`.
"""
from __future__ import annotations

import json

from tiktok_music_downloader import fb_xhr_phan_tich as ph
from tiktok_music_downloader.fb_quet_cuon import DauDomFB

CHU_PAGE = "100000000000001"        # owner.id của "page" giả
CHU_LA = "100000000000999"          # owner.id của video không thuộc page (bình luận / quảng cáo)
URL_VIDEOS = "https://www.facebook.com/ten-page-gia/videos"
URL_REELS = "https://www.facebook.com/ten-page-gia/reels"
TUONG = DauDomFB(co_hop_thoai_dang_nhap=True, co_nut_dong=False)         # hộp thoại KHÔNG đóng được
HOP_THOAI_DONG_DUOC = DauDomFB(co_hop_thoai_dang_nhap=True, co_nut_dong=True)


def ma(i: int, tien: str = "1") -> str:
    """Id video giả: chuỗi số (hợp mẫu id Facebook)."""
    return f"{tien}{i:09d}"


def nut(m: str, owner: str = CHU_PAGE, giay: int | None = None, **them) -> dict:
    """Nút video tab /videos (trong `edges[].node`)."""
    n = {"__typename": "Video", "id": m, "owner": {"__typename": "User", "id": owner}, **them}
    if giay is not None:
        n["channel_tab_thumbnail_renderer"] = {"video": {"creation_story": {"attachments": [
            {"target": {"__typename": "Video", "id": m, "playable_duration_in_ms": giay * 1000}}]}}}
    return n


def media_reel(m: str, owner: str = CHU_PAGE, giay: int | None = None) -> dict:
    d = {"__typename": "Video", "id": m, "owner": {"__typename": "User", "id": owner}}
    if giay is not None:
        d["length_in_second"] = float(giay)
        d["playable_duration_in_ms"] = giay * 1000
    return d


def container(nodes: list[dict], *, con_trang: bool = True, reels: bool = False) -> dict:
    if reels:
        edges = [{"profile_reel_node": {"node": {"__typename": "Story", "attachments": [{"media": n}]}}} for n in nodes]
    else:
        edges = [{"node": n} for n in nodes]
    return {"edges": edges, "page_info": {"end_cursor": "CUR", "has_next_page": con_trang}}


def script_videos(nodes: list[dict], *, con_trang: bool = True, ten: str = "all_videos", them: dict | None = None) -> str:
    """Nội dung một thẻ `<script type="application/json">` của HTML lúc tải (đường dẫn lồng như thật)."""
    data = {ten: container(nodes, con_trang=con_trang), **(them or {})}
    return json.dumps({"require": [["ScheduledServerJS", "handle", None, [{"__bbox": {"result": {"data": data}}}]]]})


def script_reels(nodes: list[dict], *, con_trang: bool = True) -> str:
    return json.dumps({"require": [["x", "y", None, [{"__bbox": {"result": {"data": {"node": {
        "aggregated_fb_shorts": container(nodes, con_trang=con_trang, reels=True)}}}}}]]]})


def than_videos(nodes: list[dict], *, con_trang: bool = True) -> str:
    """Thân XHR /videos: dòng 1 = trang, dòng 2 = mảnh `@defer` mang một video LẠ (owner khác) ngoài container."""
    d1 = {"data": {"node": {"all_videos": container(nodes, con_trang=con_trang)}}, "extensions": {}}
    d2 = {"label": "x$defer$y", "path": ["node", "all_videos", "edges", 0, "node"],
          "data": {"video": nut(ma(900000, "9"), CHU_LA)}}
    return json.dumps(d1) + "\n" + json.dumps(d2)


def than_reels(nodes: list[dict], *, con_trang: bool = True) -> str:
    d1 = {"data": {"node": {"aggregated_fb_shorts": container(nodes, con_trang=con_trang, reels=True)}}}
    d2 = {"label": "x$defer$y", "path": ["node"], "data": {"attachments": [{"media": media_reel(ma(900001, "9"), CHU_LA)}]}}
    return json.dumps(d1) + "\n" + json.dumps(d2)


def xhr(body: str, status: int = 200) -> ph.XhrFB:
    return ph.XhrFB(status=status, body=body)


def dot(nodes: list[dict], *, con_trang: bool = True, reels: bool = False) -> list[ph.XhrFB]:
    """Một đợt XHR mới (một phản hồi phân trang)."""
    return [xhr((than_reels if reels else than_videos)(nodes, con_trang=con_trang))]


def nhieu_dot(so_dot: int, moi_dot: int, *, tu: int = 0, reels: bool = False,
              giay: int | None = None) -> list[list[ph.XhrFB]]:
    """`so_dot` đợt, mỗi đợt `moi_dot` video mã tăng dần; đợt cuối `has_next_page=False`."""
    mk = media_reel if reels else nut
    return [dot([mk(ma(tu + d * moi_dot + i), giay=giay) for i in range(moi_dot)],
                con_trang=d < so_dot - 1, reels=reels) for d in range(so_dot)]


class TrangGia:
    """`TrangFB` theo kịch bản: lần `lay_xhr` thứ k trả `kich_ban[k]` (hết kịch bản ⇒ rỗng). Ghi lại số lần cuộn / bấm
    Close / URL mở / số lần đọc script. `dom_theo_lan[k]` = dấu DOM đọc ngay sau lần `lay_xhr` thứ k."""

    def __init__(self, kich_ban: list[list[ph.XhrFB]] | None = None, *, scripts: list[str] | None = None,
                 nav: int | None = 200, dom: DauDomFB | None = None, dom_theo_lan: dict[int, DauDomFB] | None = None):
        self.kich_ban, self.scripts, self.nav = list(kich_ban or []), list(scripts or []), nav
        self._dom, self.dom_theo_lan = dom or DauDomFB(), dom_theo_lan or {}
        self.da_mo: list[str] = []
        self.so_cuon = self.so_bam_dong = self.so_doc_script = 0
        self._k = 0

    def mo(self, url):
        self.da_mo.append(url)
        return self.nav

    def lay_script_json(self):
        self.so_doc_script += 1
        return self.scripts

    def cuon(self):
        self.so_cuon += 1

    def lay_xhr(self):
        k, self._k = self._k, self._k + 1
        return self.kich_ban[k] if k < len(self.kich_ban) else []

    def dau_dom(self):
        return self.dom_theo_lan.get(self._k - 1, self._dom)

    def bam_dong(self):
        self.so_bam_dong += 1
        return True


class PhienGia:
    """Context manager thay `nguon_facebook_trang._mo_phien`: trả `TrangGia`; ghi lại số lần mở và proxy."""

    def __init__(self, trang: TrangGia | None = None, loi: Exception | None = None):
        self.trang, self.loi = trang, loi
        self.so_lan_mo = 0
        self.proxy_da_dung: list = []

    def __call__(self, proxy):
        self.proxy_da_dung.append(proxy)
        self.so_lan_mo += 1
        return self

    def __enter__(self):
        if self.loi is not None:
            raise self.loi
        return self.trang

    def __exit__(self, *_a):
        return False
