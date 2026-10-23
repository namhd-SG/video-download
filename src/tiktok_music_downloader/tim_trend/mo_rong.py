"""Hop 2: từ caption của các kết quả ĐẠT (hạng 3 và 2A) sinh truy vấn mới — cách GĐ1 tìm ra tên trend bản địa.

GĐ1: caption "lookbook ai kolase multi pose …" của một kết quả 2A dẫn tới "kolase 7 pose" ⇒ 9/10 đúng dạng. Vì vậy nguồn
hạt giống gồm cả 2A (ĐK2 của agy R3b). Chỉ nhận cụm có trong ≥2 caption KHÁC NHAU (một caption lẻ là ý một người, chưa phải
tên trend), bỏ từ dừng tutorial/nền tảng để không sinh truy vấn kéo về video dạy làm.
"""
from __future__ import annotations

import re
from collections import Counter

from .truy_van import TruyVan

TU_DUNG = frozenset("""
tutorial cara buat membuat pembuatan gratis how to make prompt fyp fypシ viral foryou foryoupage xuhuong trending
capcut capcutpioneer capcutnow capcutforus pioneertemplate template di de la el the a an and of in on with for
y e o do da para com untuk dan yang ini itu dengan jadi
suara asli original sound som created by
""".split())
SO_CAPTION_TOI_THIEU = 2
DAI_CUM_TOI_DA = 3

_TU = re.compile(r"[#@]?[\w]+", re.UNICODE)


def _tu(caption: str) -> list[str]:
    return [w.lower() for w in _TU.findall(caption)]


def _cum(tu: list[str]) -> set[str]:
    # Bỏ hashtag/@ và mẩu 1 ký tự (vd "s" từ "©s" / "'s") — Pha 4 23/10 sinh truy vấn rác "s suara asli".
    sach = [w for w in tu if not w.startswith(("#", "@")) and (len(w) > 1 or w.isdigit())]
    ra: set[str] = set()
    for dai in range(1, DAI_CUM_TOI_DA + 1):
        for i in range(len(sach) - dai + 1):
            cum = sach[i:i + dai]
            if any(w in TU_DUNG for w in cum):
                continue
            if dai == 1 and (len(cum[0]) < 4 or cum[0].isdigit()):
                continue   # 1 từ ngắn/số đơn lẻ không đủ làm truy vấn
            ra.add(" ".join(cum))
    return ra


def sinh_mo_rong(captions: list[str], da_dung: set[str], toi_da: int) -> list[TruyVan]:
    """Cụm/hashtag lặp trong ≥2 caption khác nhau, chưa dùng, ưu tiên cụm dài rồi phổ biến."""
    dem_cum: Counter[str] = Counter()
    dem_tag: Counter[str] = Counter()
    for cap in {c.strip() for c in captions if c and c.strip()}:   # caption trùng nguyên văn chỉ tính 1
        tu = _tu(cap)
        dem_cum.update(_cum(tu))
        dem_tag.update({w[1:] for w in tu if w.startswith("#") and w[1:] not in TU_DUNG and len(w) > 4})
    da = {" ".join(x.lower().split()) for x in da_dung}
    cum = [c for c, n in dem_cum.items() if n >= SO_CAPTION_TOI_THIEU and c not in da]
    # Cụm dài hơn chứa cụm ngắn ⇒ bỏ cụm ngắn trùng nghĩa (giữ "kolase 7 pose", bỏ "kolase").
    cum = [c for c in cum if not any(c != d and f" {c} " in f" {d} " and dem_cum[d] >= dem_cum[c] for d in cum)]
    cum.sort(key=lambda c: (-len(c.split()), -dem_cum[c], c))
    tag = sorted((t for t, n in dem_tag.items() if n >= SO_CAPTION_TOI_THIEU and t not in da),
                 key=lambda t: (-dem_tag[t], t))
    ra = [TruyVan(c, "mo_rong", "goc") for c in cum] + [TruyVan(t, "mo_rong", "goc", loai="tag") for t in tag]
    return ra[:toi_da]
