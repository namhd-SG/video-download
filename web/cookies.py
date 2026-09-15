"""Which TikTok cookie jar a job goes out through, and what to call it.

Its own module because two layers need it and they already point at each
other: `web/queue.py` imports `web/lifecycle.py` (`on_video_verified`), so
lifecycle cannot import queue back to reach the jar lookup. Both import this
instead.
"""

from __future__ import annotations

import hashlib
import logging
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
