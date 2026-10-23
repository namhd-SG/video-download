"""Khử trùng ứng viên trước khi tốn lượt agy: theo `video_id`, rồi theo dHash ảnh bìa (cùng video re-up dưới id khác).

GĐ1: 1 video xuất hiện ở 2 nguồn (md5 ảnh bìa khớp) và 3 URL khác nhau mang cùng 1 ảnh em bé ⇒ chấm 2–3 lần một thứ.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

KHOANG_TRUNG = 4   # Hamming ≤ 4/64 bit ⇒ coi là cùng ảnh (dHash 8×8, ngưỡng thường dùng cho ảnh nén lại/đổi cỡ)


def dhash(anh: Path | Image.Image, canh: int = 8) -> int:
    """dHash 64 bit: so độ sáng từng cặp điểm ngang trên ảnh xám thu nhỏ (canh+1)×canh."""
    img = anh if isinstance(anh, Image.Image) else Image.open(anh)
    nho = img.convert("L").resize((canh + 1, canh), Image.Resampling.LANCZOS)
    px = list(nho.get_flattened_data() if hasattr(nho, "get_flattened_data") else nho.getdata())
    bit = 0
    for y in range(canh):
        for x in range(canh):
            trai, phai = px[y * (canh + 1) + x], px[y * (canh + 1) + x + 1]
            bit = (bit << 1) | int(trai > phai)
    return bit


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


@dataclass(frozen=True)
class MucKhuTrung:
    video_id: str
    anh: Path | None   # ảnh bìa đã tải; None ⇒ chỉ khử theo id


def khu_trung(ds: list[MucKhuTrung]) -> tuple[list[MucKhuTrung], dict[str, str]]:
    """Giữ mục ĐẦU TIÊN của mỗi nhóm trùng. Trả (giữ, {video_id bị bỏ: lý do})."""
    giu: list[MucKhuTrung] = []
    bo: dict[str, str] = {}
    da_thay_id: set[str] = set()
    da_thay_hash: list[tuple[int, str]] = []
    for m in ds:
        if m.video_id in da_thay_id:
            bo.setdefault(m.video_id, "trung video_id")
            continue
        da_thay_id.add(m.video_id)
        if m.anh is not None:
            h = dhash(m.anh)
            goc = next((vid for hh, vid in da_thay_hash if hamming(h, hh) <= KHOANG_TRUNG), None)
            if goc is not None:
                bo[m.video_id] = f"trung anh bia voi {goc}"
                continue
            da_thay_hash.append((h, m.video_id))
        giu.append(m)
    return giu, bo
