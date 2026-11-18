"""Vòng cuộn trang Facebook (tab /videos, /reels) tới khi đủ N video MỚI — chạy trên một `TrangFB` (giao thức nhỏ) nên test
không cần trình duyệt: tiêm trang giả kịch bản sẵn. Bản thật là `fb_trinh_duyet.PhienFB`. Khuôn của `ig_quet_cuon.py`.

Đường A (không cookie): Facebook cho khách xem được một ít rồi chặn bằng hộp thoại đăng nhập. Hộp thoại ĐẦU có nút Close
(bấm một lần, đi tiếp); hộp thoại KHÔNG có nút Close = tường cứng. Dừng khi (theo thứ tự ưu tiên): đủ N mới · tường mà chưa đủ
N (⇒ `fb_chan_dang_nhap`, kể cả 0 video mới mà thư viện đã có vài mã — không bao giờ `already_owned`) · hết trang
(`has_next_page = False`) · `SO_LUOT_LIEN_KHONG_MOI` lượt liền không thêm mã (⇒ `stalled`) · trần cuộn · trần thời gian.
HTTP 429 trên điều hướng / XHR ⇒ `chan_429` (người gọi báo cổng IP, không tự chạy lại, không trả video nào).
Video thư viện ĐÃ CÓ được lọc từng đợt (`already_have`) rồi cuộn tiếp: chỉ video MỚI tính vào N.

Chủ page = `owner.id` chiếm đa số trong các nút đã thấy; nút owner khác bị bỏ (chỉ đếm `so_la`).
"""
from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Protocol

from tiktok_music_downloader import fb_xhr_phan_tich as ph
from tiktok_music_downloader.utils import (
    STOP_ALREADY_OWNED, STOP_COMPLETE, STOP_FB_CHAN_DANG_NHAP, STOP_HET_THOI_GIAN, STOP_HET_VONG, STOP_SOURCE_EMPTY,
    STOP_STALLED, VideoRef,
)

TIEN_TO_ID_FB = "fbv-"
URL_REEL = "https://www.facebook.com/reel/{}"
URL_VIDEO = "https://www.facebook.com/watch/?v={}"
NGHI_CUON_GIAY = (2.5, 4.0)     # nghỉ giữa hai lần cuộn (đo bước 0)
CHO_BAN_DAU_GIAY = 6.0          # chờ sau khi mở trang cho XHR đầu về
TRAN_LUOT_CUON = 40             # trần số lần cuộn mỗi job (đo bước 0)
SO_LUOT_LIEN_KHONG_MOI = 6      # từng ấy lượt liền không thêm mã nào ⇒ coi như hết nguồn (đo bước 0)
TRAN_LAN_BAM_DONG = 3           # số lần bấm Close tối đa: hộp thoại cứ hiện lại có nút Close vẫn là tường


@dataclass(frozen=True)
class DauDomFB:
    """Dấu đọc từ DOM: chỉ cờ đúng/sai, không chứa chữ của trang."""
    co_hop_thoai_dang_nhap: bool = False    # dialog có `input[name=pass]`
    co_nut_dong: bool = False               # hộp thoại đó có nút Close / Đóng


class TrangFB(Protocol):
    def mo(self, url: str) -> int | None:
        """Mở URL, trả mã HTTP của lần điều hướng (None nếu không biết)."""

    def lay_script_json(self) -> list[str]:
        """Nội dung mọi thẻ `<script type="application/json">` hiện có (HTML lúc tải)."""

    def cuon(self) -> None: ...
    def dau_dom(self) -> DauDomFB: ...

    def bam_dong(self) -> bool:
        """Bấm nút Close của hộp thoại đăng nhập; True nếu bấm được."""

    def lay_xhr(self) -> list[ph.XhrFB]:
        """XHR đích mới về kể từ lần gọi trước (rút cạn)."""


@dataclass
class KetQuaQuet:
    refs: list[VideoRef] = field(default_factory=list)
    ly_do: str = STOP_COMPLETE      # một mã STOP_* (rỗng = đủ N)
    chan_429: bool = False
    co_tuong: bool = False          # dừng vì hộp thoại đăng nhập không đóng được
    so_da_co: int = 0               # video thư viện đã có (đã `on_skip`)
    so_la: int = 0                  # nút owner khác chủ page, bỏ
    so_qua_dai: int = 0             # vượt trần thời lượng (nút có thời lượng), bỏ
    so_bam_dong: int = 0
    so_cuon: int = 0
    so_xhr: int = 0


def _ref(ma: str, tab: str, giay: int | None) -> VideoRef:
    url = (URL_REEL if tab == "reels" else URL_VIDEO).format(ma)
    # Thiếu thời lượng ⇒ `la_short`: trần 15 phút kiểm SAU tải, trước khi lên Drive (`web/queue.py`).
    return VideoRef(video_id=TIEN_TO_ID_FB + ma, url=url, duration=giay, la_short=giay is None)


def quet(trang: TrangFB, url: str, *, tab: str, max_videos: int,
         already_have: Callable[[list[str]], set[str]], on_skip: Callable[[VideoRef], None],
         tran_thoi_luong_giay: int, tran_cuon: int = TRAN_LUOT_CUON, max_seconds: float | None = None,
         ngu: Callable[[float], None] | None = None,
         ngau_nhien: Callable[[float, float], float] | None = None,
         dong_ho: Callable[[], float] | None = None) -> KetQuaQuet:
    # Tra lúc GỌI (không buộc vào hàm lúc import): test thay `time.sleep` / `random.uniform` được.
    ngu, ngau_nhien, dong_ho = ngu or time.sleep, ngau_nhien or random.uniform, dong_ho or time.monotonic
    kq = KetQuaQuet()
    bat_dau = dong_ho()
    thay: set[str] = set()          # mã đã xử lý (mới, đã có, quá dài hay lạ owner)
    dem_owner: Counter[str] = Counter()
    het_trang = False
    khong_moi_lien_tiep = 0

    nav = trang.mo(url)
    if nav == 429:
        kq.chan_429 = True
        return kq
    ngu(CHO_BAN_DAU_GIAY)
    lan = -1
    while True:          # MỘT chốt duy nhất: `lan >= tran_cuon` ở cuối vòng (bỏ nó ⇒ vòng không dừng)
        lan += 1
        kq.so_cuon = lan
        moi_xhr = trang.lay_xhr()
        kq.so_xhr += len(moi_xhr)
        if any(x.status == 429 for x in moi_xhr):
            kq.chan_429, kq.refs, kq.ly_do = True, [], ""
            return kq
        goc = ph.doc_script_json(trang.lay_script_json()) if lan == 0 else []   # HTML lúc tải: chỉ đọc một lần
        for x in moi_xhr:
            goc.extend(ph.doc_nhieu_dong(x.body))
        boc = ph.boc_nut(goc, tab)
        chua_thay = [n for n in boc.nut if n.ma not in thay]
        dem_owner.update(n.owner for n in chua_thay)
        chu_page = dem_owner.most_common(1)[0][0] if dem_owner else None
        thay.update(n.ma for n in chua_thay)
        khong_moi_lien_tiep = 0 if chua_thay else khong_moi_lien_tiep + 1
        cua_page = []
        for n in chua_thay:
            if n.owner != chu_page:
                kq.so_la += 1
            elif n.giay is not None and n.giay > tran_thoi_luong_giay:
                kq.so_qua_dai += 1
            else:
                cua_page.append(n)
        da_co = already_have([TIEN_TO_ID_FB + n.ma for n in cua_page]) if cua_page else set()
        for n in cua_page:
            ref = _ref(n.ma, tab, n.giay)
            if ref.video_id in da_co:
                kq.so_da_co += 1
                on_skip(ref)
            else:
                kq.refs.append(ref)
        if boc.con_trang is not None:
            het_trang = not boc.con_trang
        if len(kq.refs) >= max_videos:
            break
        dau = trang.dau_dom()
        if dau.co_hop_thoai_dang_nhap:
            if dau.co_nut_dong and kq.so_bam_dong < TRAN_LAN_BAM_DONG:
                kq.so_bam_dong += 1
                trang.bam_dong()                # hộp thoại đầu: bấm Close rồi đi tiếp
            else:
                kq.co_tuong, kq.ly_do = True, STOP_FB_CHAN_DANG_NHAP
                break                           # tường: kể cả 0 mới mà thư viện có vài mã — không phải `already_owned`
        if het_trang or khong_moi_lien_tiep >= SO_LUOT_LIEN_KHONG_MOI:
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
        # Hết nguồn mà chưa đủ: có video mới ít hơn xin ⇒ stalled; chỉ có bài đã có ⇒ already_owned; không có gì ⇒ rỗng.
        kq.ly_do = (STOP_STALLED if kq.refs else STOP_ALREADY_OWNED if kq.so_da_co else STOP_SOURCE_EMPTY)
    return kq
