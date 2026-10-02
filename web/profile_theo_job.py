"""Profile Chromium THEO JOB cho job trang profile TikTok (sau cờ, mặc định TẮT).

Lớp web từng hardcode `profile_dir=None` để cookie phiên của người này không rò
sang job của người khác. Khi bật `VIDEODL_PROFILE_CAPTCHA`, job profile dùng một
thư mục RIÊNG của đúng job đó (`<data>/profiles/<job_id>`), tạo 0700, xoá khi job
kết thúc, và bộ quét dọn phần sót — nên không có chuyện hai job chung một phiên.

Không import `web.app` (vòng import) ⇒ `tao_thu_muc_rieng` nhân bản đúng hai dòng
của `web.app._make_private_dir`.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from web import models

log = logging.getLogger("videodl.web")

ENV_PROFILE_CAPTCHA = "VIDEODL_PROFILE_CAPTCHA"
ENV_PROFILE_HEADFUL = "VIDEODL_PROFILE_HEADFUL"
_GIA_TRI_BAT = ("1", "true", "yes", "on")

# Job ở các trạng thái này sẽ không bao giờ mở lại profile_dir của nó. Trạng thái
# KHÁC (running, pending, và mọi trạng thái trung gian về sau) ⇒ GIỮ: thà để sót
# một thư mục cho bộ quét lượt sau còn hơn xoá phiên của job đang sống.
TRANG_THAI_KET_THUC = frozenset({"done", "failed", "interrupted", "cancelled"})

_TEN_JOB_RE = re.compile(r"[0-9]+")


def _doc_co(ten: str) -> bool:
    # Đọc LÚC CHẠY, không lúc import: đổi cờ rồi restart là đủ, và test đặt env được.
    return os.environ.get(ten, "").strip().lower() in _GIA_TRI_BAT


def profile_captcha_dang_bat() -> bool:
    return _doc_co(ENV_PROFILE_CAPTCHA)


def profile_headful_dang_bat() -> bool:
    """Chỉ có nghĩa khi `profile_captcha_dang_bat()`; cờ chính tắt thì không ai hỏi."""
    return _doc_co(ENV_PROFILE_HEADFUL)


def thu_muc_profiles(db_path: Path) -> Path:
    return db_path.parent / "profiles"


def thu_muc_profile_job(db_path: Path, job_id: int) -> Path:
    return thu_muc_profiles(db_path) / str(job_id)


def tao_thu_muc_rieng(path: Path) -> None:
    """Tạo `path` chỉ chủ đọc được. `mkdir(mode=)` không đủ (umask che, và bị bỏ qua
    khi thư mục đã có) ⇒ `chmod` tường minh — cùng lý do `web.app._make_private_dir`."""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def chuan_bi_profile_job(db_path: Path, job_id: int) -> Path:
    """Tạo `profiles/` và `profiles/<job_id>` đều 0700, trả đường dẫn thư mục job.

    Gọi TRƯỚC scraper: `_open_context` tự `mkdir` nhưng không đặt quyền.
    """
    tao_thu_muc_rieng(thu_muc_profiles(db_path))
    thu_muc = thu_muc_profile_job(db_path, job_id)
    tao_thu_muc_rieng(thu_muc)
    return thu_muc


def _xoa_cay(duong_dan: Path) -> bool:
    """Xoá một mục dưới `profiles/`; True nếu đã mất. Symlink chỉ gỡ liên kết,
    không bao giờ đi theo ra ngoài `profiles/`."""
    try:
        if duong_dan.is_symlink() or not duong_dan.is_dir():
            duong_dan.unlink()
        else:
            shutil.rmtree(duong_dan)
    except FileNotFoundError:
        return True
    except OSError as exc:
        log.warning("không xoá được %s (%s) — bộ quét sẽ thử lại", duong_dan, type(exc).__name__)
        return False
    return True


def xoa_profile_job(db_path: Path, job_id: int) -> bool:
    """Xoá `profiles/<job_id>` nếu có. Không bao giờ ném: xoá trượt chỉ log, để bộ
    quét dọn sau — không được làm hỏng việc ghi trạng thái job. True = không còn gì."""
    thu_muc = thu_muc_profile_job(db_path, job_id)
    try:
        if not (thu_muc.exists() or thu_muc.is_symlink()):
            return True
    except OSError as exc:
        log.warning("job %s: không kiểm được %s (%s)", job_id, thu_muc, type(exc).__name__)
        return False
    return _xoa_cay(thu_muc)


def quet_profile_mo_coi(db_path: Path) -> dict[str, int]:
    """Xoá thư mục con của `profiles/` mà job tương ứng không còn hoặc đã kết thúc.

    Trả SỐ ĐẾM từng loại — người gọi log số, không log "xong" trần:
      · `da_xoa`    thư mục mồ côi đã xoá
      · `giu`       job còn sống (running/pending/trạng thái khác) ⇒ không đụng
      · `xoa_truot` mồ côi nhưng xoá trượt (quét lượt sau thử lại)
      · `bo_qua`    tên không phải số nguyên, hoặc không đọc được DB để biết job
                    ⇒ không xoá (không biết là của ai thì không phải của mình)
    """
    dem = {"da_xoa": 0, "giu": 0, "xoa_truot": 0, "bo_qua": 0}
    goc = thu_muc_profiles(db_path)
    if not goc.is_dir():
        return dem
    try:
        muc = sorted(goc.iterdir())
    except OSError as exc:
        log.warning("không liệt được %s (%s)", goc, type(exc).__name__)
        dem["bo_qua"] += 1
        return dem
    for m in muc:
        if not _TEN_JOB_RE.fullmatch(m.name):
            log.info("bộ quét profile: bỏ qua %r (tên không phải số job)", m.name)
            dem["bo_qua"] += 1
            continue
        try:
            job = models.get_job(db_path, int(m.name))
        except Exception as exc:  # noqa: BLE001 — không biết job sống hay chết ⇒ KHÔNG xoá
            log.warning("bộ quét profile: không đọc được job %s (%s) — giữ nguyên",
                        m.name, type(exc).__name__)
            dem["bo_qua"] += 1
            continue
        if job is not None and job["trang_thai"] not in TRANG_THAI_KET_THUC:
            dem["giu"] += 1
        elif _xoa_cay(m):
            dem["da_xoa"] += 1
        else:
            dem["xoa_truot"] += 1
    return dem
