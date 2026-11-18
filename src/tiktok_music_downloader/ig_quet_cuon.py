"""Vòng cuộn trang Instagram tới khi đủ N video MỚI — chạy trên một `TrangIG` (giao thức nhỏ) nên test không cần
trình duyệt: tiêm trang giả kịch bản sẵn. Bản thật là `ig_trinh_duyet.PhienIG`.

Dừng khi (theo thứ tự ưu tiên): thấy dấu mất phiên (⇒ `mat_phien`, KHÔNG trả video nào, job dừng nhãn riêng) ·
đủ N mới · hết trang (`has_next_page`/`more_available` = False) · 4 lần cuộn liền không ra XHR mới · chạm trần
cuộn · chạm trần thời gian. Video thư viện ĐÃ CÓ được lọc từng đợt XHR (`already_have`) rồi cuộn tiếp ("đào qua"
bài đã có): chỉ video MỚI mới tính vào N.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from tiktok_music_downloader import ig_xhr_phan_tich as ph
from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED, STOP_COMPLETE, STOP_HET_THOI_GIAN, STOP_HET_VONG, STOP_SOURCE_EMPTY, STOP_STALLED,
    VideoRef,
)

TIEN_TO_ID_IG = "ig-"
URL_REEL = "https://www.instagram.com/reel/{}/"
NGHI_CUON_GIAY = (2.5, 4.0)     # nghỉ giữa hai lần cuộn (đo bước 0)
CHO_BAN_DAU_GIAY = 6.0          # chờ sau khi mở trang cho XHR đầu về (đo bước 0)
TRAN_LUOT_CUON = 40             # trần số lần cuộn mỗi job (hashtag: ~1/8 mã là video ⇒ N=20 cần ~20 lần)
SO_CUON_CHO_XHR = 3             # trang thường mà sau từng ấy lần cuộn vẫn 0 XHR đích ⇒ mất phiên (dấu 4)
SO_CUON_LIEN_KHONG_XHR = 4      # từng ấy lần cuộn liền không có XHR mới ⇒ coi như hết nguồn


class TrangIG(Protocol):
    def mo(self, url: str) -> int | None:
        """Mở URL, trả mã HTTP của lần điều hướng (None nếu không biết)."""

    def cuon(self) -> None: ...
    def url_cuoi(self) -> str: ...
    def dau_dom(self) -> ph.DauDom: ...

    def lay_xhr(self) -> list[ph.XhrDich]:
        """XHR đích mới về kể từ lần gọi trước (rút cạn)."""


@dataclass
class KetQuaQuet:
    refs: list[VideoRef] = field(default_factory=list)
    ly_do: str = STOP_COMPLETE      # một mã STOP_* (rỗng = đủ N)
    mat_phien: str | None = None    # mã `ig_xhr_phan_tich.MP_*` khi dừng vì mất phiên
    so_carousel: int = 0            # carousel thấy được, KHÔNG tải (chỉ số, vào log)
    so_cuon: int = 0
    so_xhr: int = 0
    so_da_co: int = 0               # video thư viện đã có (đã `on_skip`)


def _ref_tu_node(node: dict) -> VideoRef:
    ma = node["code"]
    tt = ph.tom_tat_node(node)
    return VideoRef(video_id=TIEN_TO_ID_IG + ma, url=URL_REEL.format(ma), title=tt["title"], author=tt["author"])


def quet(trang: TrangIG, url: str, *, la_audio: bool, max_videos: int,
         already_have: Callable[[list[str]], set[str]], on_skip: Callable[[VideoRef], None],
         tran_cuon: int = TRAN_LUOT_CUON, max_seconds: float | None = None,
         ngu: Callable[[float], None] | None = None,
         ngau_nhien: Callable[[float, float], float] | None = None,
         dong_ho: Callable[[], float] | None = None) -> KetQuaQuet:
    # Tra lúc GỌI (không buộc vào hàm lúc import): test thay `time.sleep` / `random.uniform` được.
    ngu, ngau_nhien, dong_ho = ngu or time.sleep, ngau_nhien or random.uniform, dong_ho or time.monotonic
    kq = KetQuaQuet()
    bat_dau = dong_ho()
    tat_ca: list[ph.XhrDich] = []
    thay: set[str] = set()          # mã video đã xử lý (mới hay đã có)
    carousel: set[str] = set()
    het_trang = False
    khong_xhr_lien_tiep = 0

    def mat_phien(ma: str) -> KetQuaQuet:
        kq.refs, kq.mat_phien, kq.ly_do = [], ma, ""
        return kq

    nav = trang.mo(url)
    if nav == 429:
        return mat_phien(ph.MP_HTTP_429)
    ngu(CHO_BAN_DAU_GIAY)
    lan = -1
    while True:          # MỘT chốt duy nhất: `lan >= tran_cuon` ở cuối vòng (bỏ nó ⇒ vòng không dừng)
        lan += 1
        kq.so_cuon = lan
        moi_xhr = trang.lay_xhr()
        tat_ca.extend(moi_xhr)
        kq.so_xhr = len(tat_ca)
        khong_xhr_lien_tiep = 0 if moi_xhr else khong_xhr_lien_tiep + 1
        for x in moi_xhr:
            goc = ph.doc_json(x.body)
            if goc is None:
                continue
            nodes = ph.duyet_node_media(goc)
            video, _ = ph.loc_video(nodes)
            carousel.update(n["code"] for n in nodes if n.get("media_type") == ph.MEDIA_CAROUSEL)
            chua_thay = [n for n in video if n["code"] not in thay]
            thay.update(n["code"] for n in chua_thay)
            da_co = already_have([TIEN_TO_ID_IG + n["code"] for n in chua_thay]) if chua_thay else set()
            for n in chua_thay:
                ref = _ref_tu_node(n)
                if ref.video_id in da_co:
                    kq.so_da_co += 1
                    on_skip(ref)
                else:
                    kq.refs.append(ref)
            p = ph.doc_phan_trang(goc)
            if p is not None:
                het_trang = not p.con_trang
        kq.so_carousel = len(carousel)
        ma = ph.phan_loai_mat_phien(trang.url_cuoi(), tat_ca, trang.dau_dom(), la_audio=la_audio,
                                    da_cho_du_xhr=lan >= SO_CUON_CHO_XHR)
        if ma is not None:
            return mat_phien(ma)
        if len(kq.refs) >= max_videos:
            break
        if het_trang or khong_xhr_lien_tiep >= SO_CUON_LIEN_KHONG_XHR:
            break
        if lan >= tran_cuon:
            kq.ly_do = STOP_HET_VONG
            break
        if max_seconds is not None and dong_ho() - bat_dau >= max_seconds:
            kq.ly_do = STOP_HET_THOI_GIAN
            break
        trang.cuon()
        ngu(ngau_nhien(*NGHI_CUON_GIAY))
    kq.refs = kq.refs[:max_videos]
    if len(kq.refs) >= max_videos:
        kq.ly_do = STOP_COMPLETE
    elif not kq.ly_do:
        # Hết nguồn mà chưa đủ: không có gì mới ⇒ đã có hết (nếu thấy video) hoặc nguồn rỗng; có ít hơn xin ⇒ hết nguồn.
        kq.ly_do = (STOP_STALLED if kq.refs else STOP_ALREADY_OWNED if kq.so_da_co else STOP_SOURCE_EMPTY)
    return kq
