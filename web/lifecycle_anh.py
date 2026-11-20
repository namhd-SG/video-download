"""Vòng đời của MỘT bài ảnh sau khi đã tải + kiểm đủ K tệp: đẩy lên Drive, ghi DB, xoá local — tất cả hoặc không gì.

Song song với `web/lifecycle.on_video_verified` (không sửa file đó), dùng lại các mảnh của nó: thư mục job
(`_ensure_job_folder`), đẩy có thử lại (`_upload_co_thu_lai`), cầu dao Drive (`_note_upload_outcome`), đường thumb.

Bố cục Drive: `job-<id>/<bai_id>/01.<ext> … NN.<ext>`.

Thứ tự bắt buộc: đủ K tệp lên Drive → MỚI ghi K hàng `videos` (`ghi_bai_anh`, một giao dịch). Hàng ở DB nghĩa là
"tệp này nằm trong Shared Drive"; ghi trước upload sẽ cho hàng ma khi upload trượt.

Khác video: thư mục job không tạo được ⇒ bài FAILED, KHÔNG rơi về gốc Shared Drive (một bài K tệp rải ở gốc không
còn gom lại được).

Trượt bất kỳ ⇒ trash thư mục bài (gom cả tệp đã lên), 0 hàng DB, XOÁ local: lần chạy lại tải lại từ đầu vì URL CDN
ký đã hết hạn — giữ local không để lại gì dùng được.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Protocol, Sequence

from tiktok_music_downloader.gdrive_upload import UploadOutcome, UploadResult
from tiktok_music_downloader.tai_anh_cau_hinh import file_id_anh
from tiktok_music_downloader.utils import VideoRef, che_url
from web import lifecycle, models_anh
from web.lifecycle import THUMB_WIDTH, _cut_thumbnail_quietly, thumb_path_for

log = logging.getLogger("ttmd.lifecycle_anh")

_DUOI_VIDEO = ".mp4"


class UploaderAnhLike(Protocol):
    """Phần uploader Drive mà đường ảnh dùng; chữ ký khớp `gdrive_upload.DriveUploader`."""

    def upload_file(self, path: Path, parent_folder_id: str | None = None) -> UploadResult: ...
    def is_configured(self) -> bool: ...
    def create_job_folder(self, job_id: int) -> UploadResult: ...
    def create_folder(self, name: str, parent_id: str | None = None) -> UploadResult: ...
    def trash_file(self, file_id: str) -> UploadResult: ...


def _cat_thumb_anh_quietly(path: Path, db_path: Path, video_id: str) -> bool:
    """Thu ảnh `path` thành `thumbs/<video_id>.webp` (rộng `THUMB_WIDTH`). Không bao giờ ném: thiếu thumb chỉ là
    thẻ không có hình, thấy ngay trên lưới."""
    try:
        from PIL import Image, ImageOps
        out = thumb_path_for(db_path, video_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            cao = max(1, round(im.height * THUMB_WIDTH / im.width)) if im.width > THUMB_WIDTH else im.height
            im = im.resize((min(im.width, THUMB_WIDTH), cao))
            im.save(out, "WEBP", quality=80)
        return out.stat().st_size > 0
    except Exception as exc:  # noqa: BLE001 — hợp đồng "không ném" giữ bằng cấu trúc
        log.warning("thumbnail bài ảnh: không cắt được (%s)", type(exc).__name__)
        return False


def _cat_thumb_quietly(tep_dau: Path, db_path: Path, video_id: str) -> None:
    if tep_dau.suffix.lower() == _DUOI_VIDEO:        # ảnh 01 là con-video carousel: cắt khung bằng ffmpeg
        _cut_thumbnail_quietly(tep_dau, db_path, video_id)
    else:
        _cat_thumb_anh_quietly(tep_dau, db_path, video_id)


def _bo_thu_muc_dang(uploader: UploaderAnhLike, job_id: int, thu_muc_bai_id: str | None) -> None:
    """Trash thư mục bài dở trên Drive. Trash trượt không đổi kết quả bài (vẫn FAILED) nhưng phải để lại dấu."""
    if not thu_muc_bai_id:
        return
    r = uploader.trash_file(thu_muc_bai_id)
    if not r.ok:
        log.error("job %s: không trash được thư mục bài dở trên Drive (%s: %s) — lần chạy sau sẽ tạo thư mục "
                  "cùng tên (trùng), không mất dữ liệu; dọn tay thư mục bài thiếu tệp",
                  job_id, r.outcome.value, che_url(r.reason))


def _hang_db(job_id: int, ref: VideoRef, tep: Sequence[Path], file_ids: Sequence[str],
             thu_muc_bai_id: str) -> list[dict]:
    return [{
        "video_id": file_id_anh(ref.video_id, i), "job_id": job_id, "url": ref.url, "title": ref.title,
        "author": ref.author, "region": ref.region, "duration": ref.duration, "play_count": ref.play_count,
        "music_id": ref.music_id, "description": ref.description, "track": ref.track, "artist": ref.artist,
        "drive_file_id": file_ids[i - 1], "bai_id": ref.video_id, "thu_tu": i, "bai_thu_muc_id": thu_muc_bai_id,
    } for i in range(1, len(tep) + 1)]


def on_bai_anh_verified(*, job_id: int, ref: VideoRef, tep: Sequence[Path], db_path: Path | None = None,
                        uploader: UploaderAnhLike | None = None) -> UploadResult:
    """Đẩy K tệp đã kiểm của một bài lên Drive rồi ghi K hàng. Trả `UploadResult` (`.ok` ⇔ cả bài đã lên Drive và đã
    có hàng) — người gọi tính `xong+1` CHỈ khi `.ok`. Thư mục local của bài (`tep[0].parent`) bị xoá ở MỌI nhánh."""
    if not tep:
        return UploadResult(outcome=UploadOutcome.FAILED, reason="bài ảnh không có tệp")
    thu_muc_local = tep[0].parent
    uploader = uploader or lifecycle._get_uploader()
    try:
        return _day_bai_len(job_id, ref, list(tep), db_path, uploader)
    finally:
        shutil.rmtree(thu_muc_local, ignore_errors=True)


def _day_bai_len(job_id: int, ref: VideoRef, tep: list[Path], db_path: Path | None,
                 uploader: UploaderAnhLike) -> UploadResult:
    thu_muc_job = lifecycle._ensure_job_folder(job_id, uploader, db_path)
    if thu_muc_job is None:
        # `_ensure_job_folder` không tự báo cầu dao; không báo thì Drive hỏng hẳn mà bộ đếm đứng im. Nó nuốt kết quả
        # gốc nên dựng lại: chưa cấu hình ≠ đã cấu hình mà trượt (xem `_note_upload_outcome`).
        if uploader.is_configured():
            ket_qua = UploadResult(outcome=UploadOutcome.FAILED, reason="không tạo được thư mục job trên Drive")
        else:
            ket_qua = UploadResult(outcome=UploadOutcome.NOT_CONFIGURED, reason="Drive chưa cấu hình")
        lifecycle._note_upload_outcome(ket_qua)
        log.warning("job %s: bài ảnh FAILED — không có thư mục job (không rơi về gốc Shared Drive)", job_id)
        return ket_qua

    thu_muc_bai = uploader.create_folder(ref.video_id, thu_muc_job)
    lifecycle._note_upload_outcome(thu_muc_bai)
    if not thu_muc_bai.ok or not thu_muc_bai.file_id:
        log.warning("job %s: bài ảnh FAILED — không tạo được thư mục bài (%s)", job_id, thu_muc_bai.outcome.value)
        return thu_muc_bai if not thu_muc_bai.ok else UploadResult(
            outcome=UploadOutcome.FAILED, reason="thư mục bài không có id")

    file_ids: list[str] = []
    for i, duong_dan in enumerate(tep, start=1):
        ket_qua, lan_thu_lai = lifecycle._upload_co_thu_lai(uploader, duong_dan, thu_muc_bai.file_id)
        lifecycle._note_upload_outcome(ket_qua)
        if lan_thu_lai:
            log.info("job %s: tệp %d/%d lên Drive sau %d lần thử lại", job_id, i, len(tep), lan_thu_lai)
        if not ket_qua.ok or not ket_qua.file_id:
            log.warning("job %s: bài ảnh FAILED ở tệp %d/%d (%s: %s) — trash thư mục bài, xoá local",
                        job_id, i, len(tep), ket_qua.outcome.value, che_url(ket_qua.reason))
            _bo_thu_muc_dang(uploader, job_id, thu_muc_bai.file_id)
            return ket_qua if not ket_qua.ok else UploadResult(
                outcome=UploadOutcome.FAILED, reason="tệp lên Drive không có id")
        file_ids.append(ket_qua.file_id)

    if db_path is not None:
        # Thumb TRƯỚC khi ghi hàng (local còn nguyên); video_id của tệp 01 để `video_nay_cua_toi` khớp.
        _cat_thumb_quietly(tep[0], db_path, file_id_anh(ref.video_id, 1))
        try:
            models_anh.ghi_bai_anh(db_path, _hang_db(job_id, ref, tep, file_ids, thu_muc_bai.file_id))
        except Exception as exc:  # noqa: BLE001 — tệp đã lên Drive mà không có hàng ⇒ hoàn tác cả bài cho nhất quán
            log.error("job %s: bài ảnh đã lên Drive nhưng ghi DB trượt (%s) — trash thư mục bài để lần chạy "
                      "sau làm lại từ đầu", job_id, type(exc).__name__)
            _bo_thu_muc_dang(uploader, job_id, thu_muc_bai.file_id)
            return UploadResult(outcome=UploadOutcome.FAILED, reason=f"ghi DB trượt: {type(exc).__name__}")
    log.info("job %s: bài ảnh %d tệp lên Drive xong, đã xoá local", job_id, len(tep))
    return UploadResult(outcome=UploadOutcome.SUCCESS, file_id=thu_muc_bai.file_id, drive_id=thu_muc_bai.drive_id,
                        web_view_link=thu_muc_bai.web_view_link)
