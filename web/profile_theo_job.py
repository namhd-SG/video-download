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
import socket
from pathlib import Path

from tiktok_music_downloader.scraper import profile_dir_dang_mo
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
    ghi_khoa_worker(thu_muc)
    return thu_muc


# Khoá RIÊNG của worker, ghi vào thư mục profile mỗi lần chuẩn bị. Lý do: Chromium
# HEADLESS không tạo `SingletonLock` (đo 02/10 trên Chromium của Playwright: headful có
# khoá `<host>-<pid>`, headless thì không có) — mà headless là mặc định khi bật cờ. Không
# có khoá này thì bộ quét lúc boot không phân biệt được thư mục của tiến trình CŨ còn
# sống (launchd dựng tiến trình mới trước khi tiến trình cũ chết) với thư mục mồ côi.
TEN_KHOA_WORKER = ".videodl-worker"


def ghi_khoa_worker(thu_muc: Path) -> None:
    """Ghi `"<hostname>-<pid tiến trình này>"` vào `<thu_muc>/.videodl-worker` (ghi tạm
    rồi `os.replace` để bộ quét không bao giờ đọc phải nửa chuỗi)."""
    tam = thu_muc / (TEN_KHOA_WORKER + ".tam")
    tam.write_text(f"{socket.gethostname()}-{os.getpid()}", encoding="utf-8")
    os.replace(tam, thu_muc / TEN_KHOA_WORKER)


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


# Kết quả đọc `SingletonLock` của một thư mục profile.
_LOCK_KHONG_CO = "khong_co"    # không có khoá ⇒ không Chromium nào đang giữ thư mục
_LOCK_CHET = "chet"            # khoá của máy NÀY, pid đã chết ⇒ khoá mồ côi
_LOCK_SONG = "song"            # khoá của máy NÀY, pid còn sống ⇒ Chromium đang mở
_LOCK_KHONG_RO = "khong_ro"    # không đọc/đoán được ⇒ KHÔNG được xoá


def _phan_dinh_chuoi_khoa(chuoi: str) -> str:
    """Phân định chuỗi khoá `"<hostname>-<pid>"` (dùng chung cho `SingletonLock` của
    Chromium và khoá riêng của worker). Trả một trong `_LOCK_SONG/_LOCK_CHET/_LOCK_KHONG_RO`."""
    host, _, pid_txt = chuoi.rpartition("-")
    if not host or not pid_txt.isascii() or not pid_txt.isdigit() or int(pid_txt) <= 0:
        return _LOCK_KHONG_RO
    try:
        host_may = socket.gethostname()
    except OSError:
        return _LOCK_KHONG_RO
    if host != host_may:
        return _LOCK_KHONG_RO
    try:
        os.kill(int(pid_txt), 0)
    except ProcessLookupError:
        return _LOCK_CHET
    except PermissionError:
        return _LOCK_SONG  # tiến trình có thật, chỉ không thuộc user này
    except (OSError, OverflowError, ValueError):
        return _LOCK_KHONG_RO
    return _LOCK_SONG


def _doc_khoa_worker(thu_muc: Path) -> str:
    """Đọc `.videodl-worker` (file thường, KHÔNG đi theo symlink)."""
    khoa = thu_muc / TEN_KHOA_WORKER
    try:
        if khoa.is_symlink():
            return _LOCK_KHONG_RO
        chuoi = khoa.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return _LOCK_KHONG_CO
    except (OSError, UnicodeDecodeError):
        return _LOCK_KHONG_RO
    # Khoá do CHÍNH tiến trình này ghi: pid sống là đương nhiên (là mình), nên `os.kill`
    # không phân định được gì. Ở đây hỏi registry context của chính tiến trình: không giữ
    # context nào trên thư mục này ⇒ không ai dùng (job đã kết thúc theo DB) ⇒ xoá được.
    # Không có nhánh này thì thư mục xoá trượt của job đã xong nằm tới lần khởi động sau.
    try:
        if chuoi == f"{socket.gethostname()}-{os.getpid()}":
            return _LOCK_SONG if profile_dir_dang_mo(thu_muc) else _LOCK_CHET
    except OSError:
        return _LOCK_KHONG_RO
    return _phan_dinh_chuoi_khoa(chuoi)


def _doc_khoa(thu_muc: Path) -> str:
    """Gộp hai khoá: còn sống ở BẤT KỲ khoá nào ⇒ `_LOCK_SONG`; không xác định được ở bất
    kỳ khoá nào ⇒ `_LOCK_KHONG_RO`; còn lại (không có / chết) ⇒ xoá được."""
    ket_qua = (_doc_singleton_lock(thu_muc), _doc_khoa_worker(thu_muc))
    if _LOCK_SONG in ket_qua:
        return _LOCK_SONG
    if _LOCK_KHONG_RO in ket_qua:
        return _LOCK_KHONG_RO
    return _LOCK_CHET if _LOCK_CHET in ket_qua else _LOCK_KHONG_CO


def _doc_singleton_lock(thu_muc: Path) -> str:
    """Chromium HEADFUL giữ thư mục profile bằng symlink `SingletonLock` trỏ tới chuỗi
    `"<hostname>-<pid>"` (đích không phải file thật nên symlink luôn "treo" — đọc bằng
    `os.readlink`, KHÔNG đi theo). HEADLESS không tạo khoá này (đo 02/10), nên bộ quét còn
    đọc khoá riêng `.videodl-worker`. Trả một trong bốn hằng `_LOCK_*`.

    Tách ở dấu `-` CUỐI CÙNG vì hostname có thể chứa `-`. Phải khớp CẢ host lẫn pid:
    pid chỉ có nghĩa trên máy sinh ra nó, nên host khác ⇒ không xác định được ⇒
    `_LOCK_KHONG_RO` (giữ), đừng đem pid của máy khác đi hỏi `os.kill` ở đây.
    Pid còn sống nhưng bị tái dùng cho tiến trình khác ⇒ vẫn giữ (nghiêng về giữ; thư
    mục sót được dọn ở lượt sau khi pid đó chết).
    """
    try:
        dich = os.readlink(thu_muc / "SingletonLock")
    except FileNotFoundError:
        return _LOCK_KHONG_CO
    except OSError:  # có mục tên đó nhưng không phải symlink, hoặc không đọc được
        return _LOCK_KHONG_RO
    return _phan_dinh_chuoi_khoa(dich)


def dem_thu_muc_con_profiles(db_path: Path) -> int:
    """Số thư mục con trực tiếp của `profiles/` (0 nếu không có/không liệt được).
    Chỉ đếm: không đọc tên ra ngoài, không SELECT, không xoá."""
    try:
        with os.scandir(thu_muc_profiles(db_path)) as it:
            return sum(1 for e in it if e.is_dir(follow_symlinks=False))
    except OSError:
        return 0


def quet_profile_mo_coi(db_path: Path) -> dict[str, int]:
    """Xoá thư mục con của `profiles/` mà job tương ứng không còn hoặc đã kết thúc.

    Trả SỐ ĐẾM từng loại — người gọi log số, không log "xong" trần:
      · `da_xoa`    thư mục mồ côi đã xoá
      · `giu`       job còn sống (running/pending/trạng thái khác) ⇒ không đụng
      · `xoa_truot` mồ côi nhưng xoá trượt (quét lượt sau thử lại)
      · `bo_qua`    tên không phải số nguyên, hoặc không đọc được DB để biết job,
                    hoặc khoá không xác định được — `SingletonLock` của Chromium hoặc khoá
                    riêng `.videodl-worker` (host khác máy này, sai định dạng, pid không
                    phải số) ⇒ không xoá (không biết là của ai
                    thì không phải của mình). Chọn `bo_qua` chứ không `giu_dang_mo`
                    cho host khác: ta KHÔNG biết có Chromium đang sống, nói "đang mở"
                    là khai điều chưa đo.
      · `giu_dang_mo` chỉ XUẤT HIỆN khi > 0: job đã kết thúc/không còn nhưng
                    khoá (`SingletonLock` hoặc `.videodl-worker`) trỏ `<host máy này>-<pid>`
                    còn sống (launchd dựng tiến trình mới khi tiến trình cũ chưa chết hẳn
                    ⇒ Chromium/worker cũ vẫn đang giữ thư mục) ⇒ GIỮ, lượt sau thử lại.
    """
    dem = {"da_xoa": 0, "giu": 0, "xoa_truot": 0, "bo_qua": 0}
    goc = thu_muc_profiles(db_path)
    if goc.is_symlink():
        # `is_dir()`/`iterdir()` đi theo liên kết: quét qua đó là xoá thư mục con tên
        # số ở nơi liên kết trỏ tới, ngoài `profiles/` thật. Không phải của mình ⇒ bỏ.
        log.warning("bộ quét profile: %s là liên kết tượng trưng — bỏ qua", goc)
        dem["bo_qua"] += 1
        return dem
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
            continue
        # Mục là symlink/không phải thư mục thì chỉ gỡ liên kết (`_xoa_cay`), và đọc
        # `<m>/SingletonLock` sẽ đi theo liên kết ra ngoài ⇒ bỏ qua kiểm khoá.
        trang_lock = (_doc_khoa(m) if m.is_dir() and not m.is_symlink()
                      else _LOCK_KHONG_CO)
        if trang_lock == _LOCK_SONG:
            dem["giu_dang_mo"] = dem.get("giu_dang_mo", 0) + 1
        elif trang_lock == _LOCK_KHONG_RO:
            log.info("bộ quét profile: %s có khoá (SingletonLock hoặc .videodl-worker) không xác định được — giữ", m.name)
            dem["bo_qua"] += 1
        elif _xoa_cay(m):
            dem["da_xoa"] += 1
        else:
            dem["xoa_truot"] += 1
    return dem
