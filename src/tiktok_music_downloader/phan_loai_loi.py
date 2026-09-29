"""Phân loại lỗi tải từng video: do TikTok, hay do hệ thống của mình.

Dùng chung cho CLI (`downloader.py`) và dịch vụ web (`web/queue.py`) để cùng
một lỗi không bị hai nơi xếp hai loại khác nhau.

`tiktok`   = TikTok không cho tải video này (bài ảnh, video gỡ/riêng tư, không
             có định dạng tải được). Bỏ qua được, không phải sự cố của mình.
`he_thong` = mọi thứ còn lại (mạng, Drive, lifecycle hook, lỗi chưa từng thấy).

⚠ Danh sách `tiktok` là WHITELIST HẸP và mặc định là `he_thong`: phân loại sai
một lỗi hệ thống thành `tiktok` là che lỗi thật (log hạ xuống WARNING, giao
diện tô xám), còn sai chiều ngược lại chỉ thừa một dòng đỏ. Thêm mẫu vào đây
chỉ khi đã thấy đúng chuỗi đó do TikTok trả về.
"""
from __future__ import annotations

# Nhánh "đã tải xong nhưng file không có luồng video" (bài ảnh / slideshow ra
# file chỉ có tiếng — `web/queue.py::verify_video_stream`). Không có ngoại lệ
# nào của yt-dlp để khớp, nên web truyền đúng chuỗi này vào hàm phân loại.
LOI_KHONG_CO_LUONG_VIDEO = "downloaded file carries no video stream"

_MAU_TIKTOK = (
    "requested format is not available",
    "video unavailable",
    "private video",
    "this video is private",
    "carries no video stream",
)


def phan_loai_loi(text: object) -> str:
    """`"tiktok"` nếu `text` khớp whitelist, ngược lại `"he_thong"`."""
    s = str(text).lower()
    return "tiktok" if any(m in s for m in _MAU_TIKTOK) else "he_thong"
