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
    # Nền tảng link lẻ (YouTube): giới hạn tuổi ("Sign in to confirm your age") là video này không cho tải khi
    # ẩn danh — lỗi của MỘT video, giống "private video" ở trên. "Sign in" trần KHÔNG vào đây (xem `phat_hien_chan`).
    "confirm your age",
    # TikTok video lẻ lớn hơn trần dung lượng một file (`downloader.download_all(max_filesize=…)`).
    "qua_nang:",
)


def phan_loai_loi(text: object) -> str:
    """`"tiktok"` nếu `text` khớp whitelist, ngược lại `"he_thong"`."""
    s = str(text).lower()
    return "tiktok" if any(m in s for m in _MAU_TIKTOK) else "he_thong"


# ---------------------------------------------------------------------------
# Nền tảng link lẻ (yt-dlp): lỗi TỪNG VIDEO khác hẳn tín hiệu CHẶN CẢ NỀN TẢNG
# ---------------------------------------------------------------------------
# Tín hiệu chặn = CHỈ những chuỗi riêng của việc bị chặn (đọc từ `extractor/youtube/_video.py` của bản cài):
#   · lý do YouTube "Sign in to confirm you're not a bot" — chuỗi "not a bot";
#   · "YouTube is requiring a captcha challenge before playback";
#   · "Your account / The current session has been rate-limited by YouTube for up to an hour";
#   · HTTP 429 / "Too Many Requests" (mọi nền tảng).
# CỐ Ý KHÔNG có "sign in" trần: nhánh `'sign in' in reason.lower()` của yt-dlp gom cả video riêng tư lẫn giới hạn
# tuổi ("Sign in to confirm your age"), tức lỗi của MỘT video — dùng nó làm tín hiệu thì một video riêng tư tắt cả
# nền tảng. Cũng không khớp số `429` trần: URL/id trong thông điệp có thể chứa "429".
_MAU_CHAN = (
    ("not_a_bot", "not a bot"),
    ("captcha_challenge", "captcha challenge"),
    ("rate_limited", "has been rate-limited by youtube"),
    ("http_429", "http error 429"),
    ("http_429", "too many requests"),
)


def phat_hien_chan(text: object) -> str | None:
    """Mã tín hiệu chặn nếu `text` mang chuỗi chặn, ngược lại None. Mã chỉ để ghi `nen_tang_tat.ly_do`."""
    s = str(text).lower()
    for ma, mau in _MAU_CHAN:
        if mau in s:
            return ma
    return None


# Lỗi riêng từng video của link lẻ (KHÔNG tắt nền tảng). `can_dang_nhap` gom video riêng tư / giới hạn tuổi / cần
# đăng nhập; lỗi khác (mạng, định dạng…) trả None để người gọi xếp vào lỗi hệ thống.
LOI_CAN_DANG_NHAP = "can_dang_nhap"
LOI_QUA_DAI = "qua_dai"
LOI_QUA_NANG = "qua_nang"
LOI_LA_PLAYLIST = "la_playlist"
LOI_TRUC_TIEP = "truc_tiep"
LOI_THIEU_JS = "thieu_js"
_MAU_CAN_DANG_NHAP = ("sign in", "login required", "private video", "this video is private",
                      "members-only", "confirm your age")


def ly_do_loi_video(text: object) -> str | None:
    """`can_dang_nhap` nếu lỗi là video riêng tư / giới hạn tuổi / cần đăng nhập, ngược lại None. Gọi SAU
    `phat_hien_chan` (chuỗi "not a bot" cũng chứa "sign in")."""
    s = str(text).lower()
    return LOI_CAN_DANG_NHAP if any(m in s for m in _MAU_CAN_DANG_NHAP) else None
