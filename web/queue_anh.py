"""Đường ảnh của hàng đợi job: tải từng BÀI ảnh (K tệp) rồi đẩy Drive — tách khỏi `download_all` (hợp đồng 1 ref = 1
tệp `<id>.mp4`). `web/queue.py::_hoan_tat_tu_refs` chỉ nối dây: tách ref theo `VideoRef.loai`, video đi `download_all`
như cũ, ảnh đi `tai_cac_bai_anh` ở đây.

Mỗi bài, theo thứ tự:
  1. kiểm đĩa SỐNG (hết đĩa ⇒ dừng cả job, mọi bài sau không chạy);
  2. throttle: TikTok (không có cổng IP) = `JitterThrottle` + nghỉ lô như `download_all`; Instagram/Facebook = ghi lượt
     vào cổng (`cong.truoc_goi()`, có thể trả lý do dừng) rồi nghỉ jitter của cổng;
  3. `tai_mot_bai` (tất cả K tệp hoặc không gì; không ném);
  4. URL CDN ký hết hạn (`can_tham_lai`) ⇒ thăm bài lại ĐÚNG MỘT lần để lấy URL mới rồi tải lại một lần;
  5. tải ok ⇒ `on_bai_anh_verified` (Drive + K hàng DB); CHỈ khi `.ok` mới `xong+1` và ghi sighting.

Thăm bài lại là điểm cắm của từng nền tảng (`dang_ky_tham_lai`): nguồn nào chưa đăng ký thì bài cần thăm lại coi như
hụt phía nguồn (không im lặng coi là xong).

Log chỉ mang nhãn + số — không URL, handle hay id bài.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tiktok_music_downloader import nguon_facebook_trang, nguon_instagram, tai_anh, tiktok_anh
from tiktok_music_downloader.downloader import BATCH_REST_SECONDS, BATCH_SIZE
from tiktok_music_downloader.tai_anh_cau_hinh import LOAI_ANH
from tiktok_music_downloader.utils import JitterThrottle, VideoRef, che_url
from web import lifecycle_anh, models

log = logging.getLogger("ttmd.queue_anh")

# Phân loại lỗi (khớp `_JobProgress._ghi_loi(loai=…)`): "tiktok" = phía nguồn (WARNING, khung xám),
# "he_thong" = phía ta (ERROR, khung đỏ).
LOAI_LOI_NGUON = "tiktok"
LOAI_LOI_HE_THONG = "he_thong"

# Hàm thăm bài lại: `(ref, proxy) -> VideoRef | None`. Trả ref MỚI (cùng `video_id` = bai_id, `loai="anh"`, URL ảnh
# mới) hoặc None khi bài không còn (gỡ/riêng tư). Ném lỗi ⇒ hụt phía ta.
HamThamLai = Callable[[VideoRef, "str | None"], "VideoRef | None"]
_THAM_LAI: dict[str, HamThamLai] = {}

# Gỡ hậu tố `nt` ("tt" | "ig" | "fbp") ra khỏi `anh-<nt>-<id>`.
_NHAN_NEN_TANG = ("tt", "ig", "fbp")


def dang_ky_tham_lai(nen_tang_id: str, ham: HamThamLai) -> None:
    """Đăng ký hàm thăm bài lại cho nền tảng `nen_tang_id` ∈ {tt, ig, fbp} (phần giữa của `anh-<nt>-<id>`).
    Mỗi nền tảng một hàm; đăng ký lại thay hàm cũ."""
    if nen_tang_id not in _NHAN_NEN_TANG:
        raise ValueError(f"nền tảng ảnh không hợp lệ: {nen_tang_id!r}")
    _THAM_LAI[nen_tang_id] = ham


def _nen_tang_cua_bai(bai_id: str) -> str | None:
    phan = bai_id.split("-", 2)
    return phan[1] if len(phan) == 3 and phan[0] == "anh" and phan[1] in _NHAN_NEN_TANG else None


# TikTok và Facebook thăm bài ẩn danh ⇒ đăng ký thẳng lúc nạp module. Instagram cần cookie của người tạo job nên
# không nằm trong bảng: `tham_lai_theo_job(cookies_path)` bọc riêng.
dang_ky_tham_lai("tt", tiktok_anh.tham_lai)
dang_ky_tham_lai("fbp", nguon_facebook_trang.tham_lai)


def tham_lai_theo_job(cookies_path: str | None) -> HamThamLai:
    """Hàm thăm lại cho MỘT job: bài Instagram mở bằng jar IG của người tạo job (`cookies_path`; thiếu ⇒ hàm IG ném
    `ValueError` ⇒ bài hụt phía ta, không coi là bài gỡ); nền tảng khác tra bảng đăng ký."""
    def _ham(ref: VideoRef, proxy: str | None) -> VideoRef | None:
        if _nen_tang_cua_bai(ref.video_id) == "ig":
            return nguon_instagram.tham_lai(ref, proxy, cookies_path=cookies_path)
        return _tham_lai_mac_dinh(ref, proxy)
    return _ham


class _ChuaCoHamThamLai(Exception):
    """Nền tảng của bài chưa đăng ký hàm thăm lại."""


def _tham_lai_mac_dinh(ref: VideoRef, proxy: str | None) -> VideoRef | None:
    ham = _THAM_LAI.get(_nen_tang_cua_bai(ref.video_id) or "")
    if ham is None:
        raise _ChuaCoHamThamLai()
    return ham(ref, proxy)


@dataclass(frozen=True)
class KetQuaCacBai:
    """`ly_do_dung`: lý do dừng cả lượt ảnh do chính vòng này phát hiện (hết đĩa / cổng bảo dừng); None = chạy hết."""
    xong: int = 0
    loi: int = 0
    ly_do_dung: str | None = None


def _tai_va_tham_lai(ref: VideoRef, thu_muc: Path, proxy: str | None, kiem_video, tai_mot_bai, tham_lai,
                     truoc_tham_lai: Callable[[], str | None]) -> tuple[tai_anh.KetQuaTaiBai, str | None]:
    """`(kết quả, lý do dừng)`. Thăm lại tối đa MỘT lần; sau lần thăm mà URL vẫn 403/410 ⇒ lỗi phía nguồn.

    Ref ảnh CHƯA có URL (`anh_urls` rỗng — trang liệt kê chỉ thấy anchor `/photo/`, chưa thấy dữ liệu bài) thì thăm
    bài NGAY, không tải trước (tải trước chỉ ra "bài không có ảnh" sai phía nguồn)."""
    if ref.anh_urls:
        kq = tai_mot_bai(ref, thu_muc, proxy, kiem_video=kiem_video)
        if kq.ok or not kq.can_tham_lai:
            return kq, None
    else:
        kq = _hut(ref, tai_anh.LOI_NGUON, "bài ảnh chưa có URL ảnh")
    ly_do_dung = truoc_tham_lai()
    if ly_do_dung:
        return kq, ly_do_dung
    try:
        ref_moi = tham_lai(ref, proxy)
    except _ChuaCoHamThamLai:
        return _hut(ref, tai_anh.LOI_NGUON, "URL ảnh hết hạn, nguồn chưa hỗ trợ thăm lại"), None
    except Exception as exc:  # noqa: BLE001 — hàm của nền tảng; mọi lỗi của nó là một bài hụt, không giết job
        log.error("thăm lại bài ảnh lỗi (%s)", type(exc).__name__)
        return _hut(ref, tai_anh.LOI_HE_THONG, f"thăm lại bài lỗi ({type(exc).__name__})"), None
    if ref_moi is None:
        return _hut(ref, tai_anh.LOI_NGUON, "bài không còn khi thăm lại"), None
    if ref_moi.video_id != ref.video_id or ref_moi.loai != LOAI_ANH:
        return _hut(ref, tai_anh.LOI_HE_THONG, "thăm lại trả bài lệch id/loại"), None
    kq2 = tai_mot_bai(ref_moi, thu_muc, proxy, kiem_video=kiem_video)
    if not kq2.ok and kq2.can_tham_lai:
        # Vẫn 403/410 sau khi đã có URL mới ⇒ nguồn không cho tải, thăm thêm cũng vô ích.
        return _hut(ref, tai_anh.LOI_NGUON, kq2.ly_do or "403 sau thăm lại"), None
    return kq2, None


def _hut(ref: VideoRef, loai_loi: str, ly_do: str) -> tai_anh.KetQuaTaiBai:
    return tai_anh.KetQuaTaiBai(False, ref.video_id, loai_loi=loai_loi, ly_do=ly_do)


def tai_cac_bai_anh(
    anh_refs: list[VideoRef], *, job_id: int, db_path: Path, thu_muc: Path, proxy: str | None = None,
    kiem_dia: Callable[[VideoRef], str | None] | None = None,
    cong=None,
    kiem_video: Callable[[Path], bool] | None = None,
    ghi_loi: Callable[..., None],
    ghi_sighting: Callable[[VideoRef], None],
    tham_lai: HamThamLai | None = None,
    throttle: JitterThrottle | None = None,
    nghi_lo: Callable[[float], None] = time.sleep,
    kich_thuoc_lo: int = BATCH_SIZE,
    nghi_lo_giay: float = BATCH_REST_SECONDS,
) -> KetQuaCacBai:
    """Tải + đẩy Drive lần lượt từng bài trong `anh_refs`; trả số xong/hụt và lý do dừng (nếu có).

    `kiem_dia(ref)`: trả lý do (chuỗi) khi đĩa dưới ngưỡng ⇒ dừng TRƯỚC bài đó. `cong` (nền tảng có cổng IP):
    `truoc_goi()` ghi lượt trước mỗi bài và có thể trả lý do dừng; None (TikTok) ⇒ `throttle` tự do. `ghi_loi(ref,
    ly_do, loai=…)` và `ghi_sighting(ref)` do `queue.py` nối vào `_JobProgress` (đếm lỗi/sighting dùng chung với video).
    Hàm `tham_lai` mặc định tra bảng đăng ký (`dang_ky_tham_lai`); `tai_mot_bai`/`on_bai_anh_verified` tra lúc gọi
    nên test thay được. `xong+1` CHỈ sau khi hook báo `.ok`."""
    tham_lai = tham_lai or _tham_lai_mac_dinh
    tai_mot_bai = tai_anh.tai_mot_bai
    hook = lifecycle_anh.on_bai_anh_verified
    nghi_cong = None
    if throttle is None:
        throttle = JitterThrottle(2.0)      # như `download_all` (delay_seconds mặc định) cho TikTok
    if cong is not None:
        from web import pacer
        nghi_cong = JitterThrottle(0.0, khoang=pacer.NGHI_GIUA_LUOT)
    cho_nghi = nghi_cong or throttle

    def _truoc_goi() -> str | None:
        return cong.truoc_goi() if cong is not None else None

    xong = loi = 0
    da_lam_trong_lo = 0
    ly_do_dung: str | None = None
    for ref in anh_refs:
        if kiem_dia is not None:
            ly_do_dung = kiem_dia(ref)
            if ly_do_dung:
                log.warning("dừng lượt ảnh trước một bài: %s", ly_do_dung)
                break
        if da_lam_trong_lo >= kich_thuoc_lo:
            log.info("lô %d bài ảnh xong — nghỉ %.0fs", kich_thuoc_lo, nghi_lo_giay)
            nghi_lo(nghi_lo_giay)
            da_lam_trong_lo = 0
        cho_nghi.wait()
        ly_do_dung = _truoc_goi()
        if ly_do_dung:
            log.warning("dừng lượt ảnh: cổng nền tảng từ chối (%s)", ly_do_dung)
            break
        kq, ly_do_dung = _tai_va_tham_lai(ref, thu_muc, proxy, kiem_video, tai_mot_bai, tham_lai,
                                          _truoc_goi_sau_nghi(cho_nghi, _truoc_goi))
        if ly_do_dung:
            log.warning("dừng lượt ảnh trước khi thăm lại: cổng nền tảng từ chối (%s)", ly_do_dung)
            break
        da_lam_trong_lo += 1
        if not kq.ok:
            loi += 1
            ghi_loi(ref, kq.ly_do or "bài ảnh hụt",
                    loai=LOAI_LOI_NGUON if kq.loai_loi == tai_anh.LOI_NGUON else LOAI_LOI_HE_THONG)
            continue
        ket_qua_up = hook(job_id=job_id, ref=ref, tep=kq.tep, db_path=db_path)
        if ket_qua_up.ok:
            models.increment_job_counts(db_path, job_id, xong_delta=1)
            ghi_sighting(ref)
            xong += 1
        else:
            loi += 1
            ghi_loi(ref, f"bài ảnh không lên được Drive ({ket_qua_up.outcome.value}: {che_url(ket_qua_up.reason)})",
                    loai=LOAI_LOI_HE_THONG)
    return KetQuaCacBai(xong=xong, loi=loi, ly_do_dung=ly_do_dung)


def _truoc_goi_sau_nghi(cho_nghi: JitterThrottle, truoc_goi: Callable[[], str | None]) -> Callable[[], str | None]:
    """Trước lần thăm lại: nghỉ jitter (TikTok: `JitterThrottle`; IG/FB: nghỉ của cổng) rồi ghi lượt cổng."""
    def _ham() -> str | None:
        cho_nghi.wait()
        return truoc_goi()
    return _ham
