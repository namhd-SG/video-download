"""Tải MỘT bài ảnh (K tệp) về đĩa và kiểm từng tệp — tất cả hoặc không gì.

Trung lập nền tảng: nhận `VideoRef(loai="anh")` đã có `anh_urls` (mỗi tệp một tuple URL dự phòng) và `anh_kieu`.
Không chạm Drive/DB. Hụt BẤT KỲ tệp nào ⇒ xoá cả thư mục bài và trả kết quả lỗi; người gọi không phải dọn.

Phân loại lỗi (`loai_loi`):
  * "nguon"    — phía nguồn: bài gỡ (404), URL ký hết hạn mà vẫn 403/410, bài quá nặng (vượt trần số ảnh).
  * "he_thong" — phía ta: tệp thiếu/hỏng (không phải ảnh, cụt, con-video không có luồng hình), mạng.
`can_tham_lai=True` khi có URL bị 403/410: chữ ký CDN hết hạn, người gọi thăm bài lại ĐÚNG 1 lần để lấy URL mới.

Log chỉ mang nhãn + số — không URL, handle hay id bài.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tiktok_music_downloader.tai_anh_cau_hinh import BYTE_TOI_THIEU, LOAI_ANH, TRAN_ANH_MOI_BAI, la_bai_id_hop_le
from tiktok_music_downloader.utils import USER_AGENTS, VideoRef

log = logging.getLogger("ttmd.tai_anh")

LOI_NGUON = "nguon"
LOI_HE_THONG = "he_thong"

KIEU_ANH = "anh"
KIEU_VIDEO = "video"

# Trần dung lượng MỘT tệp: bài thật đo ≤ 12 MB cả bài; vượt xa là luồng lạ, đừng để nó lấp đĩa.
TRAN_BYTE_MOI_TEP = 100 * 1024 * 1024
_TIMEOUT = (10, 60)
_MA_URL_HET_HAN = (403, 410)
_MA_BAI_GO = (404,)
_DUOI_THEO_DINH_DANG = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "HEIF": "heic", "HEIC": "heic",
                        "AVIF": "avif", "BMP": "bmp"}


@dataclass(frozen=True)
class KetQuaTaiBai:
    """`ok` ⇒ `tep` là đúng K đường dẫn `thu_muc_bai/NN.<ext>` theo thứ tự, đã qua kiểm. Lỗi ⇒ thư mục đã xoá,
    `tep` rỗng, `loai_loi` ∈ {"nguon","he_thong"}, `ly_do` là nhãn ngắn (không URL)."""
    ok: bool
    bai_id: str
    thu_muc_bai: Path | None = None
    tep: tuple[Path, ...] = ()
    loai_loi: str | None = None
    ly_do: str | None = None
    can_tham_lai: bool = False


class _HutTep(Exception):
    """Một tệp không tải/kiểm được sau khi thử hết URL dự phòng."""

    def __init__(self, loai_loi: str, ly_do: str, can_tham_lai: bool = False):
        super().__init__(ly_do)
        self.loai_loi, self.ly_do, self.can_tham_lai = loai_loi, ly_do, can_tham_lai


def _lay_mac_dinh(url: str, **kw):
    import requests  # nhập trễ như `downloader._download_url_direct`
    return requests.get(url, **kw)


def _kiem_anh_bang_pillow(duong_dan: Path) -> str:
    """Trả đuôi tệp theo định dạng THẬT; ném `_HutTep` nếu không giải mã nổi. `verify()` bắt tệp lạ, `load()` bắt tệp
    cụt (verify một mình cho qua ảnh JPEG bị cắt)."""
    from PIL import Image
    try:
        with Image.open(duong_dan) as im:
            dinh_dang = (im.format or "").upper()
            im.verify()
        with Image.open(duong_dan) as im:
            im.load()
    except Exception as exc:  # noqa: BLE001 — mọi lỗi giải mã đều là "tệp không phải ảnh lành"
        raise _HutTep(LOI_HE_THONG, f"tệp ảnh hỏng ({type(exc).__name__})") from exc
    duoi = _DUOI_THEO_DINH_DANG.get(dinh_dang)
    if duoi is None:
        raise _HutTep(LOI_HE_THONG, "định dạng ảnh lạ")
    return duoi


def _tai_mot_url(lay: Callable, url: str, dich: Path, kieu: str, proxy: str | None) -> None:
    """Tải stream một URL vào `dich` (`.part`). Ném `_HutTep` kèm phân loại; ngoại lệ mạng ném nguyên cho vòng ngoài."""
    proxies = {"http": proxy, "https": proxy} if proxy else None
    with lay(url, headers={"User-Agent": USER_AGENTS[0]}, stream=True, proxies=proxies, timeout=_TIMEOUT) as r:
        if r.status_code in _MA_URL_HET_HAN:
            raise _HutTep(LOI_NGUON, f"HTTP {r.status_code} (URL hết hạn)", can_tham_lai=True)
        if r.status_code in _MA_BAI_GO:
            raise _HutTep(LOI_NGUON, f"HTTP {r.status_code} (bài gỡ)")
        if r.status_code >= 400:
            raise _HutTep(LOI_HE_THONG, f"HTTP {r.status_code}")
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kieu == KIEU_ANH and not ctype.startswith("image/"):
            raise _HutTep(LOI_HE_THONG, "Content-Type không phải ảnh")
        da_ghi = 0
        with open(dich, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                da_ghi += len(chunk)
                if da_ghi > TRAN_BYTE_MOI_TEP:
                    raise _HutTep(LOI_NGUON, "tệp quá nặng")
                f.write(chunk)


def _tai_mot_tep(lay: Callable, urls: tuple, thu_muc_bai: Path, thu_tu: int, kieu: str, proxy: str | None,
                 kiem_video: Callable[[Path], bool] | None) -> Path:
    """Thử LẦN LƯỢT các URL dự phòng; URL đầu lỗi (kết nối/HTTP/Content-Type/tệp hỏng) thì sang URL sau."""
    part = thu_muc_bai / f"{thu_tu:02d}.part"
    loi_cuoi: _HutTep | None = None
    het_han = False
    for url in urls:
        try:
            _tai_mot_url(lay, url, part, kieu, proxy)
            if kieu == KIEU_VIDEO:
                if kiem_video is None:
                    raise _HutTep(LOI_HE_THONG, "thiếu hàm kiểm con-video")
                if part.stat().st_size < BYTE_TOI_THIEU:
                    raise _HutTep(LOI_HE_THONG, "con-video quá nhỏ")
                dich = thu_muc_bai / f"{thu_tu:02d}.mp4"
                # ffmpeg đoán định dạng theo nội dung, không theo đuôi `.part`.
                if not kiem_video(part):
                    raise _HutTep(LOI_HE_THONG, "con-video không có luồng hình")
            else:
                if part.stat().st_size < BYTE_TOI_THIEU:
                    raise _HutTep(LOI_HE_THONG, "tệp ảnh quá nhỏ")
                dich = thu_muc_bai / f"{thu_tu:02d}.{_kiem_anh_bang_pillow(part)}"
            part.replace(dich)
            return dich
        except _HutTep as exc:
            loi_cuoi = exc
            het_han = het_han or exc.can_tham_lai
        except Exception as exc:  # noqa: BLE001 — lỗi kết nối/ghi đĩa: thử URL dự phòng
            loi_cuoi = _HutTep(LOI_HE_THONG, f"lỗi mạng ({type(exc).__name__})")
        finally:
            part.unlink(missing_ok=True)
    assert loi_cuoi is not None  # `urls` rỗng đã bị chặn ở người gọi
    if het_han:
        raise _HutTep(LOI_NGUON, loi_cuoi.ly_do, can_tham_lai=True)
    raise loi_cuoi


def tai_mot_bai(ref: VideoRef, thu_muc: Path, proxy: str | None = None, *,
                kiem_video: Callable[[Path], bool] | None = None,
                lay: Callable | None = None) -> KetQuaTaiBai:
    """Tải K tệp của `ref.anh_urls` về `thu_muc/<bai_id>/NN.<ext>`; hụt bất kỳ ⇒ xoá thư mục bài và trả lỗi.

    `kiem_video`: hàm kiểm con-video (production truyền `web.queue.verify_video_stream`; `src` không import `web`).
    `lay`: thay `requests.get` khi test. Không bao giờ ném: mọi lỗi nằm trong `KetQuaTaiBai`."""
    bai_id = ref.video_id
    if not la_bai_id_hop_le(bai_id):
        # `bai_id` thành tên thư mục bị mkdir/rmtree bên dưới: không tin nguồn, tự rào (chặn `..`, `/`, rỗng).
        return KetQuaTaiBai(False, str(bai_id), loai_loi=LOI_HE_THONG, ly_do="bai_id sai hình")
    urls_moi_tep = tuple(ref.anh_urls or ())
    k = len(urls_moi_tep)
    if ref.loai != LOAI_ANH or k == 0 or any(not u for u in urls_moi_tep):
        return KetQuaTaiBai(False, bai_id, loai_loi=LOI_NGUON, ly_do="bài không có ảnh")
    if k > TRAN_ANH_MOI_BAI:
        return KetQuaTaiBai(False, bai_id, loai_loi=LOI_NGUON, ly_do=f"bài quá nặng ({k} tệp)")
    kieu = tuple(ref.anh_kieu) if ref.anh_kieu else (KIEU_ANH,) * k
    if len(kieu) != k or any(x not in (KIEU_ANH, KIEU_VIDEO) for x in kieu):
        return KetQuaTaiBai(False, bai_id, loai_loi=LOI_HE_THONG, ly_do="anh_kieu lệch anh_urls")

    thu_muc_bai = Path(thu_muc) / bai_id
    lay = lay or _lay_mac_dinh
    try:
        thu_muc_bai.mkdir(parents=True, exist_ok=True)
        tep = []
        for i, (urls, loai_tep) in enumerate(zip(urls_moi_tep, kieu), start=1):
            tep.append(_tai_mot_tep(lay, tuple(urls), thu_muc_bai, i, loai_tep, proxy, kiem_video))
        # Đủ K: mỗi vòng đều trả đường dẫn hoặc ném, nên `len(tep) == k` luôn đúng; kiểm lại để lệch là lỗi to.
        if len(tep) != k or not all(p.is_file() for p in tep):
            raise _HutTep(LOI_HE_THONG, "thiếu tệp sau khi tải")
    except _HutTep as exc:
        shutil.rmtree(thu_muc_bai, ignore_errors=True)
        log.warning("tải bài ảnh: hụt tệp (%s) trong %d tệp — bỏ cả bài", exc.ly_do, k)
        return KetQuaTaiBai(False, bai_id, loai_loi=exc.loai_loi, ly_do=exc.ly_do, can_tham_lai=exc.can_tham_lai)
    except OSError as exc:
        shutil.rmtree(thu_muc_bai, ignore_errors=True)
        log.error("tải bài ảnh: lỗi đĩa (%s)", type(exc).__name__)
        return KetQuaTaiBai(False, bai_id, loai_loi=LOI_HE_THONG, ly_do=f"lỗi đĩa ({type(exc).__name__})")
    return KetQuaTaiBai(True, bai_id, thu_muc_bai=thu_muc_bai, tep=tuple(tep))
