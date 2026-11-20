"""Hợp đồng chung của chế độ TẢI ẢNH (job Video / Ảnh / Cả hai): giá trị loại, cờ bật, trần và cách đặt id.

Module thuần (không import `web.*`, không chạm mạng/DB) để mọi lớp — nguồn liệt kê, hàng đợi, DB, API — dùng
CHUNG một bảng tên, không ai chép lại chuỗi. Tên ở đây là hợp đồng đóng băng: đổi tên là đổi cả dây chuyền.

Id: một BÀI (bài đăng TikTok/IG/FB có K ảnh) có `bai_id`; mỗi TỆP ảnh của bài là một hàng `videos` có
`video_id` = `file_id_anh(bai_id, thu_tu)`. Cả hai mang tiền tố `anh-` nên không bao giờ trùng id video.
"""
from __future__ import annotations

import os
import re

LOAI_VIDEO = "video"
LOAI_ANH = "anh"
LOAI_CA_HAI = "ca_hai"
LOAI_HOP_LE = (LOAI_VIDEO, LOAI_ANH, LOAI_CA_HAI)

# Cờ bật tính năng. Mặc định TẮT: đọc LÚC GỌI (đổi cờ rồi restart là đủ, test đặt env được), cùng mẫu
# `web/profile_theo_job.py`.
ENV_TAI_ANH_BAT = "VIDEODL_TAI_ANH_BAT"
_GIA_TRI_BAT = frozenset({"1", "true", "yes", "on"})

# Trần số ảnh của MỘT bài (đo: TikTok tới 35, Instagram carousel tới 20) — bài vượt trần là bài lạ, không tải.
TRAN_ANH_MOI_BAI = 50
# Tệp ảnh nhỏ hơn mức này là tệp hỏng/trang lỗi đặt tên .jpg, không phải ảnh.
BYTE_TOI_THIEU = 1024

# Nền tảng (`jobs.nen_tang`) có tải ảnh: TikTok photo/slideshow, Instagram ảnh + carousel, Facebook page photos.
NEN_TANG_CO_ANH = frozenset({"tiktok", "instagram", "facebook"})
# Nền tảng trong id: TikTok · Instagram · Facebook page (photos).
NEN_TANG_ID_ANH = ("tt", "ig", "fbp")
TIEN_TO_ID_ANH = "anh-"
_MAU_ID_BAI = re.compile(r"[A-Za-z0-9_\-]+")
# Cùng trần độ dài id của đường dẫn tệp/thumb (`web/app.py::MAX_VIDEO_ID_TIEN_TO_LEN`).
TRAN_DO_DAI_ID = 64


def tai_anh_dang_bat() -> bool:
    """Cờ `VIDEODL_TAI_ANH_BAT` đang bật không (đọc lúc gọi)."""
    return os.environ.get(ENV_TAI_ANH_BAT, "").strip().lower() in _GIA_TRI_BAT


def la_loai_hop_le(loai: object) -> bool:
    return loai in LOAI_HOP_LE


def bai_id_anh(nt: str, id_bai: str) -> str:
    """`anh-<nt>-<id bài>` với `nt` ∈ {tt, ig, fbp}. Ném `ValueError` khi nền tảng lạ hoặc id sai hình
    (id đi vào tên tệp/thư mục Drive/URL thumb nên chỉ nhận chữ-số/gạch)."""
    if nt not in NEN_TANG_ID_ANH:
        raise ValueError(f"nền tảng ảnh không hợp lệ: {nt!r}")
    if not isinstance(id_bai, str) or not _MAU_ID_BAI.fullmatch(id_bai):
        raise ValueError("id bài ảnh sai hình")
    bai_id = f"{TIEN_TO_ID_ANH}{nt}-{id_bai}"
    if len(bai_id) + 3 > TRAN_DO_DAI_ID:      # chừa chỗ cho hậu tố `-NN` của file
        raise ValueError("id bài ảnh quá dài")
    return bai_id


def file_id_anh(bai_id: str, thu_tu: int) -> str:
    """`<bai_id>-<NN>` (NN 2 chữ số, `thu_tu` bắt đầu từ 1) — `video_id` của hàng `videos` cho MỘT tệp ảnh."""
    if not isinstance(bai_id, str) or not bai_id.startswith(TIEN_TO_ID_ANH) or not _MAU_ID_BAI.fullmatch(bai_id):
        raise ValueError("bai_id sai hình")
    if isinstance(thu_tu, bool) or not isinstance(thu_tu, int) or not 1 <= thu_tu <= 99:
        raise ValueError("thu_tu phải là số nguyên 1..99")
    return f"{bai_id}-{thu_tu:02d}"
