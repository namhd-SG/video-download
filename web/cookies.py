"""Which TikTok cookie jar a job goes out through, and what to call it.

Its own module because two layers need it and they already point at each
other: `web/queue.py` imports `web/lifecycle.py` (`on_video_verified`), so
lifecycle cannot import queue back to reach the jar lookup. Both import this
instead.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
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


def cookie_jar_path(cookies_dir: Path, nguoi_tao: str) -> Path:
    """Where this person's jar BELONGS, whether or not it exists yet.

    `cookies_path_for_user` answers "is there one?" and returns None when
    there is not — right for the job path, useless for the upload path, which
    needs a destination to write to. Same sha256 construction, so the two can
    never disagree about which file is whose: a test asserts that writing here
    makes `cookies_path_for_user` find it.
    """
    digest = hashlib.sha256(nguoi_tao.encode("utf-8")).hexdigest()
    cookies_dir_resolved = cookies_dir.resolve()
    candidate = (cookies_dir_resolved / f"{digest}.json").resolve()
    if candidate.parent != cookies_dir_resolved:
        raise ValueError("cookie jar path escaped cookies_dir")
    return candidate


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

# Tập mã ĐÓNG cho cột `ly_do_dung`. Câu chữ cho người dùng nằm ở
# `web/static/app.js::STOP_REASON_TEXT` — thêm mã ở đây thì phải thêm câu ở đó.
COOKIE_KHONG_DOC_DUOC = "cookie_khong_doc_duoc"
COOKIE_RONG = "cookie_rong"
COOKIE_CHUA_DANG_NHAP = "cookie_chua_dang_nhap"
COOKIE_HET_HAN = "cookie_het_han"
MA_LOI_COOKIE = (COOKIE_KHONG_DOC_DUOC, COOKIE_RONG,
                 COOKIE_CHUA_DANG_NHAP, COOKIE_HET_HAN)


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

def han_dung_nhat(path: str) -> str | None:
    """Khi nào jar này hết hạn, dạng ISO. `None` = không có hạn đọc được.

    Chỉ trả một MỐC THỜI GIAN — cùng kỷ luật với `ly_do_jar_khong_dung_duoc`:
    thứ đi ra khỏi tệp cookie chỉ được là mã hoặc con số, không bao giờ là byte
    của tệp. Lấy hạn SỚM NHẤT trong các cookie đăng nhập vì đó là lúc jar thật
    sự hết tác dụng, không phải lúc cái cuối cùng chết.

    `expires == 0` là cookie phiên — không có hạn, nên không tính vào đây.
    `int()` bọc trong try vì `expires` đi qua không được ép kiểu (xem ghi chú
    dài ở `ly_do_jar_khong_dung_duoc`); một bản xuất ghi hạn dạng ISO không
    được phép làm ngã trang Cookie của tôi.
    """
    from tiktok_music_downloader.scraper import _load_cookies

    try:
        cookies = _load_cookies(Path(path))
    except Exception:  # noqa: BLE001 — không đọc được thì không có hạn để nói
        return None

    han = []
    for c in cookies:
        if str(c.get("name") or "") not in COOKIE_DANG_NHAP:
            continue
        try:
            h = int(c.get("expires") or 0)
        except (TypeError, ValueError):
            continue
        if h > 0:
            han.append(h)
    if not han:
        return None
    return datetime.fromtimestamp(min(han), tz=timezone.utc).isoformat()


def ly_do_jar_khong_dung_duoc(path: str, bay_gio: float | None = None) -> str | None:
    """`None` -> jar dùng được. Ngược lại là một MÃ trong `MA_LOI_COOKIE`.

    Trả MÃ chứ không trả câu chữ, vì hai lý do độc lập:
    1. Câu chữ thuộc về giao diện. `web/static/app.js` tra `ly_do_dung` qua
       bảng `STOP_REASON_TEXT`; giá trị lạ hiện thành "mã chưa dịch — báo cho
       người phát triển", tức bảo người dùng đi báo dev cho một việc họ tự
       chữa được bằng cách dán lại cookie.
    2. **An toàn theo cấu tạo.** Cột `ly_do_dung` chỉ nhận một tập mã đóng thì
       nó KHÔNG THỂ cõng byte nào của tệp cookie — không phụ thuộc vào việc có
       ai nhớ viết test canh hay không. Bản trước trả câu chữ và phải nhờ một
       test canh đường rò; test đó hoá ra là lưới giả (nó tìm một cụm bị cắt
       mất ở nhánh 20 ký tự), nên lưới người-nhớ đã thua đúng một lần rồi.

    Chi tiết hình dạng hỏng đi vào LOG, không vào DB: log an toàn vì
    `_hinh_dang_hong` không trích một ký tự nào của tệp.
    """
    from tiktok_music_downloader.scraper import _load_cookies

    try:
        cookies = _load_cookies(Path(path))
    except Exception:  # noqa: BLE001 — mọi lỗi đọc đều là "jar không dùng được"
        log.warning("jar cookie không đọc được (%s)", _hinh_dang_hong(Path(path)))
        return COOKIE_KHONG_DOC_DUOC

    if not cookies:
        return COOKIE_RONG

    ten = {str(c.get("name") or "") for c in cookies}
    if not (ten & set(COOKIE_DANG_NHAP)):
        return COOKIE_CHUA_DANG_NHAP

    # `expires == 0` là cookie phiên: không có hạn, vẫn dùng được. Chỉ coi là
    # hết hạn khi MỌI cookie đăng nhập đều có hạn và hạn đã qua.
    #
    # ⚠ `int()` phải nằm TRONG try. `_normalize_cookie` chỉ ép kiểu cho khoá
    # `expirationDate`; khoá `expires` đi qua NGUYÊN XI, nên một bản xuất ghi
    # `expires` dạng ISO ("2026-12-01T00:00:00Z") hay chuỗi float làm `int()`
    # ném ra ngoài, bay lên catch-all của `process_job` và kết thúc job
    # `failed` với `ly_do_dung = None` — job chết KHÔNG MỘT CHỮ giải thích,
    # đúng bằng cái hỏng-âm-thầm phase này sinh ra để diệt.
    moc = bay_gio if bay_gio is not None else time.time()
    han = []
    for c in cookies:
        if str(c.get("name") or "") not in COOKIE_DANG_NHAP:
            continue
        try:
            han.append(int(c.get("expires") or 0))
        except (TypeError, ValueError):
            # Không đọc được hạn thì coi như KHÔNG CÓ hạn. Nghiêng về phía cho
            # chạy: từ chối một jar tốt vì một trường lạ thì tệ hơn.
            han.append(0)
    if han and all(0 < h < moc for h in han):
        return COOKIE_HET_HAN

    return None
