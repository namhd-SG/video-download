"""Which TikTok cookie jar a job goes out through, and what to call it.

Its own module because two layers need it and they already point at each
other: `web/queue.py` imports `web/lifecycle.py` (`on_video_verified`), so
lifecycle cannot import queue back to reach the jar lookup. Both import this
instead.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

# What the daily cap counts against when no jar exists for anyone. Not a
# missing value to be skipped: jobs with no cookie still leave this machine
# from one IP, as one anonymous identity, which is exactly the shape the cap
# exists to bound.
ANONYMOUS_COOKIE = "khong-cookie"


def cookies_path_for_user(cookies_dir: Path, nguoi_tao: str) -> str | None:
    """Resolve which cookie jar belongs to this job's creator.

    Phase 05 wires real per-user auth + upload; until then this only
    guarantees the parameter travels down the right, per-user path — a real
    file at `<cookies_dir>/<sha256(nguoi_tao)>.json` when an operator has
    dropped one there by hand. No file for that user -> None (anonymous),
    never another user's cookies.

    The filename is the SHA-256 hex digest of `nguoi_tao`, not `nguoi_tao`
    itself — a hex digest never contains "/" or "." (structural, not a
    regex filter), so a path-traversal payload in `nguoi_tao` (e.g.
    "../../../etc/passwd") cannot escape `cookies_dir` no matter what value
    it carries. `web/app.py`'s `CreateJobRequest` no longer accepts
    `nguoi_tao` from the client (removed — it was the attacker-controlled
    input into this exact function), so today `nguoi_tao` is always the
    fixed "khach"; the hash stays as defense-in-depth for when Phase 05
    wires a real (still untrusted-until-verified) per-user identity through
    here.
    """
    digest = hashlib.sha256(nguoi_tao.encode("utf-8")).hexdigest()
    cookies_dir_resolved = cookies_dir.resolve()
    candidate = (cookies_dir_resolved / f"{digest}.json").resolve()
    if candidate.parent != cookies_dir_resolved:
        # Lưới thứ hai: cấu tạo digest ở trên đã chặn traversal rồi (không
        # có "/" hay ".."), đây chỉ là double-check phòng khi logic hash
        # đổi trong tương lai mà quên xét lại ràng buộc thư mục.
        log.error("cookies path traversal blocked for nguoi_tao=%r (resolved outside %s)",
                   nguoi_tao, cookies_dir_resolved)
        return None
    return str(candidate) if candidate.is_file() else None


def cookie_identity(cookies_dir: Path, nguoi_tao: str) -> str:
    """The TikTok identity this job will go out as — the key the daily cap
    counts on.

    Deliberately NOT `nguoi_tao`. The risk the cap exists for is one account,
    seen from one IP, running steadily enough to read as a bot farm; the
    account is the cookie, not the person holding the mouse. Today the two
    give the same number — every job runs as the fixed "khach" through one
    jar — so counting per person would look right and quietly become a
    different rule the day Phase 05 wires real identities and several people
    share a jar.
    """
    path = cookies_path_for_user(cookies_dir, nguoi_tao)
    return Path(path).stem if path is not None else ANONYMOUS_COOKIE


# Tên cookie đăng nhập của TikTok. Cùng hai tên mà phase-05 bắt grep trong log
# — nếu jar không có cái nào trong số này thì phiên đó KHÔNG đăng nhập, và job
# sẽ chạy y như ẩn danh (trần khách ~28 video) mà không ai biết.
COOKIE_DANG_NHAP = ("sessionid", "sessionid_ss", "sid_tt")


def _hinh_dang_hong(path: Path) -> str:
    """Vì sao tệp không đọc được, nói bằng LOẠI chứ không bằng nội dung.

    Không chuỗi nào trả về từ đây chứa một ký tự nào của tệp.
    """
    try:
        dau = path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff").lstrip()[:8]
    except OSError:
        return "không mở được tệp"
    if dau.startswith("{\\rtf"):
        return "đang là Rich Text (RTF), cần lưu lại dạng văn bản thuần"
    if not dau.startswith(("[", "{")):
        return "không phải JSON — có thể là bản xuất Header String hoặc Netscape"
    return "JSON hỏng"

def ly_do_jar_khong_dung_duoc(path: str, bay_gio: float | None = None) -> str | None:
    """`None` -> jar dùng được. Ngược lại là lý do đọc được cho người dùng.

    Tồn tại vì `download_all` nuốt lỗi cookie thành một dòng log rồi CHẠY TIẾP
    KHÔNG COOKIE (`downloader.py`: "could not load cookies — continuing
    without"). Với công cụ dòng lệnh đó là tiện; với lớp web dùng chung thì đó
    là ca hỏng âm thầm mà phase-05 sinh ra để chặn: người dùng dán cookie hỏng,
    job vẫn "xong", chỉ là ra ít video hơn hẳn và không ai biết vì sao.

    Bốn ca hỏng được phân biệt, vì bốn ca cần bốn cách chữa khác nhau.
    """
    from tiktok_music_downloader.scraper import _load_cookies

    try:
        cookies = _load_cookies(Path(path))
    except Exception:  # noqa: BLE001 — mọi lỗi đọc đều là "jar không dùng được"
        # ⚠ KHÔNG chuyển tiếp thông điệp của `_load_cookies`. Nó nhúng
        # `raw[:20]` và `raw[:80]` — 80 ký tự đầu của tệp (`scraper.py:82,91`).
        # Với bản xuất "Header String" thì 80 ký tự đầu CHÍNH LÀ
        # `sessionid=…; sid_tt=…`, và chuỗi này đi vào cột `ly_do_dung` rồi lên
        # UI. Thông điệp đó hữu ích cho người chạy dòng lệnh với tệp của chính
        # mình; ở đây nó là đường rò. Phân loại bằng HÌNH DẠNG, không trích nội
        # dung — có lặp một phần logic của loader, và lặp ở đây là cố ý.
        return f"tệp cookie không đọc được ({_hinh_dang_hong(Path(path))})"

    if not cookies:
        return "tệp cookie không có cookie nào"

    ten = {str(c.get("name") or "") for c in cookies}
    if not (ten & set(COOKIE_DANG_NHAP)):
        return ("tệp cookie không có cookie đăng nhập nào "
                f"({'/'.join(COOKIE_DANG_NHAP)}) — phiên này chưa đăng nhập")

    # `expires == 0` là cookie phiên: không có hạn, vẫn dùng được. Chỉ coi là
    # hết hạn khi MỌI cookie đăng nhập đều có hạn và hạn đã qua.
    moc = bay_gio if bay_gio is not None else time.time()
    han = [int(c.get("expires") or 0) for c in cookies
           if str(c.get("name") or "") in COOKIE_DANG_NHAP]
    if han and all(0 < h < moc for h in han):
        return "cookie đăng nhập đã hết hạn — cần dán lại"

    return None
