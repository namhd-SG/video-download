"""Cloudflare Access JWT verification — the only place identity is decided.

Why a JWT check and not the `Cf-Access-Authenticated-User-Email` header: that
header is plain text, and ANY process on this box can set it by talking to
127.0.0.1:7870 directly, bypassing cloudflared entirely. The mini runs other
people's production (Promax, ollama, glances) under at least two accounts, so
"bound to loopback" is not an access-control boundary here (phase-05 fix 1).
Only the signed `Cf-Access-Jwt-Assertion` header proves the request really
came through Access.

No new dependency: `google-auth` is already a core dependency (Drive upload),
and `google.auth.jwt.decode` verifies an RS256 signature against a
`{kid: PEM}` mapping plus `exp`/`iat`. Three things it does NOT do for us,
all measured against the installed version before this module was written:

  1. `audience=` REJECTS Cloudflare's real shape. Access mints `aud` as a
     LIST; google-auth compares the whole list against its allow-list and
     fails with "Token has wrong audience ['x'], expected one of ['x']".
     So we pass `audience=None` and check `aud` here, accepting str or list.
  2. It does NOT pin `kid`. A token whose header names a kid that is absent
     from the mapping still verifies (the library tries the keys it has).
     Harmless — every key in the mapping is Cloudflare's own, so a forger
     still needs a Cloudflare private key — but do not read this code as
     kid-pinning, because it is not.
  3. Bad input raises several types (`MalformedError`, `InvalidValue`,
     `binascii.Error`). We catch broadly: an auth boundary must answer 401,
     never leak a 500 that says the token merely confused us.

`iss` is deliberately not checked: the certs URL is already team-scoped, so
verifying the signature against THAT team's keys is the same bind `iss`
would give, and the `aud` tag is unique per Access application. Adding a
literal `iss` string would buy nothing and would fail the service closed if
Cloudflare ever reformats it.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

import requests
from fastapi import HTTPException, Request
from google.auth import jwt as google_jwt

log = logging.getLogger("videodl.auth")

# Tên biến môi trường sống trong hằng số (quy ước của repo, xem
# gdrive_upload.ENV_*) — nghiệm thu cấu hình bằng is_configured(), đừng grep
# chuỗi: grep chuỗi không ra và sẽ kết luận nhầm là "chưa cấu hình".
ENV_TEAM_DOMAIN = "CF_ACCESS_TEAM_DOMAIN"
ENV_AUD = "CF_ACCESS_AUD"

ACCESS_JWT_HEADER = "Cf-Access-Jwt-Assertion"

# Cloudflare rotates the Access signing keys every few weeks and publishes
# the old and the new key side by side, so an hour-stale cache can never miss
# a live key. Refetching on every failed verification would instead hand any
# caller a way to make us hammer Cloudflare with junk tokens.
CERTS_TTL_SECONDS = 3600
CERTS_TIMEOUT_SECONDS = 10


class AccessConfigError(RuntimeError):
    """Access is not usable at all — missing env, or the key endpoint is
    unreachable. Kept distinct from a rejected token on purpose: "chưa cấu
    hình" and "đã cấu hình mà token sai" must not collapse into one answer,
    or a misdeployed service looks exactly like an attacker being blocked."""


class AccessDenied(Exception):
    """This particular request does not carry a valid Access JWT."""


def _fetch_certs_over_https(certs_url: str) -> dict[str, str]:
    resp = requests.get(certs_url, timeout=CERTS_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload = resp.json()
    # `public_certs` is the PEM x509 list; `keys` next to it is the JWKS form,
    # which google-auth cannot consume. Measured against the live team
    # endpoint: 2 RS256 entries, both with `kid` + `cert`.
    certs = {
        entry["kid"]: entry["cert"]
        for entry in payload.get("public_certs", [])
        if entry.get("kid") and entry.get("cert")
    }
    return certs


class AccessVerifier:
    """Verifies `Cf-Access-Jwt-Assertion` and answers who the caller is.

    `certs_fetcher` is injectable so tests drive this with their own key
    material instead of the network (same shape as the fake uploader in
    tests/test_lifecycle.py).
    """

    def __init__(
        self,
        team_domain: str | None = None,
        aud: str | None = None,
        certs_fetcher: Callable[[str], dict[str, str]] = _fetch_certs_over_https,
    ) -> None:
        raw_domain = team_domain if team_domain is not None else os.environ.get(ENV_TEAM_DOMAIN)
        self._team_domain = _normalise_domain(raw_domain)
        self._aud = (aud if aud is not None else os.environ.get(ENV_AUD) or "").strip()
        self._certs_fetcher = certs_fetcher
        self._certs: dict[str, str] | None = None
        self._certs_fetched_at = 0.0

    def is_configured(self) -> bool:
        return bool(self._team_domain and self._aud)

    @property
    def certs_url(self) -> str:
        return f"https://{self._team_domain}/cdn-cgi/access/certs"

    def _certs_now(self) -> dict[str, str]:
        now = time.monotonic()
        if self._certs is not None and (now - self._certs_fetched_at) < CERTS_TTL_SECONDS:
            return self._certs
        try:
            certs = self._certs_fetcher(self.certs_url)
        except AccessConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 — network/JSON/shape, all the same answer
            raise AccessConfigError(
                f"không lấy được bộ khoá Access từ {self.certs_url}: {type(exc).__name__}"
            ) from exc
        if not certs:
            # Guard sống ở ĐÂY, không ở trong fetcher mặc định: "không có khoá
            # nào" là lỗi cấu hình dù bộ khoá đến từ đường nào. Đặt nhầm chỗ
            # thì một service không khoá trả 401 — trông hệt như chặn được kẻ
            # tấn công, trong khi thật ra nó đang không kiểm được gì cả.
            raise AccessConfigError(
                f"{self.certs_url} không trả về khoá nào — không thể kiểm JWT"
            )
        # Mốc "đã nạp" ghi SAU khi có bộ khoá thật trong tay, không trước:
        # ghi trước thì một lượt fetch trượt sẽ đóng băng cache rỗng suốt TTL.
        self._certs = certs
        self._certs_fetched_at = now
        return certs

    def verify(self, token: str | None) -> str:
        """Return the caller's identity, or raise.

        Raises `AccessDenied` for anything wrong with the token itself, and
        `AccessConfigError` when we are in no position to judge it.
        """
        if not self.is_configured():
            raise AccessConfigError(
                f"Cloudflare Access chưa cấu hình ({ENV_TEAM_DOMAIN}/{ENV_AUD} "
                "thiếu trong môi trường)"
            )
        if not token:
            raise AccessDenied(f"thiếu header {ACCESS_JWT_HEADER}")

        certs = self._certs_now()
        try:
            payload = google_jwt.decode(token, certs=certs, audience=None)
        except Exception as exc:  # noqa: BLE001 — see module docstring, point 3
            log.warning("Access JWT bị từ chối: %s", type(exc).__name__)
            raise AccessDenied("JWT không hợp lệ") from exc

        claimed = payload.get("aud")
        claimed_list = claimed if isinstance(claimed, list) else [claimed]
        if self._aud not in claimed_list:
            # Không log giá trị aud của token: nó không phải secret, nhưng
            # thông điệp lỗi nhúng nguyên đầu vào đã có tiền lệ rò dữ liệu.
            log.warning("Access JWT sai aud (không khớp %s)", ENV_AUD)
            raise AccessDenied("JWT sai audience")

        identity = _identity_from(payload)
        if not identity:
            raise AccessDenied("JWT không mang danh tính (email/common_name/sub)")
        return identity


def _normalise_domain(raw: str | None) -> str:
    domain = (raw or "").strip().rstrip("/")
    for scheme in ("https://", "http://"):
        if domain.startswith(scheme):
            domain = domain[len(scheme):]
    return domain


def _identity_from(payload: dict) -> str:
    """`email` for a human, `common_name` for a service token, `sub` as the
    last resort. Whatever comes back becomes `nguoi_tao` and is hashed into a
    cookie-jar filename, so it must be stable per person."""
    for claim in ("email", "common_name", "sub"):
        value = payload.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


_verifier: AccessVerifier | None = None


def get_verifier() -> AccessVerifier:
    """Built on first use, not at import: `deploy/run-service.sh` exports the
    env before exec'ing uvicorn, but a test importing this module must not be
    forced to have Access configured."""
    global _verifier
    if _verifier is None:
        _verifier = AccessVerifier()
    return _verifier


def require_user(request: Request) -> str:
    """FastAPI dependency — the identity every job is attributed to.

    401 when the caller cannot prove who they are; 503 when the service
    cannot check (unconfigured or key endpoint down). Never a default
    identity: falling back to "khach" here would be the silent-default
    failure this whole module exists to remove.
    """
    verifier = get_verifier()
    try:
        return verifier.verify(request.headers.get(ACCESS_JWT_HEADER))
    except AccessDenied as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AccessConfigError as exc:
        log.error("Access không kiểm được: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

# Ai được xem hàng đợi của cả team. Đọc từ env (`~/.config/videodl/env` trên
# mini) chứ không cắm cứng: danh sách người thì đổi, mà đổi nó không đáng phải
# deploy lại. Rỗng = KHÔNG AI là admin — mặc định an toàn, vì mặc định sai ở
# đây nghĩa là phơi hàng đợi của mọi người.
ENV_ADMIN_EMAILS = "VIDEODL_ADMIN_EMAILS"


def admin_tu_env() -> list[str]:
    """Danh sách admin ghi trong env — chỉ dùng để MỒI bảng lần đầu.

    So khớp không phân biệt hoa thường và bỏ khoảng trắng: danh sách do người
    gõ tay vào tệp env, và một khoảng trắng thừa không nên biến một admin
    thành người thường mà không ai biết vì sao.
    """
    raw = os.environ.get(ENV_ADMIN_EMAILS, "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def is_admin(email: str, db_path=None) -> bool:
    """`True` nếu email này là admin.

    **Bảng là nguồn sự thật; env chỉ là mồi ban đầu** (`models.moi_admin_tu_env`
    chạy lúc khởi động, và chỉ chạy khi bảng chưa có admin nào). Nếu để env
    thắng mãi thì admin cấp từ env sẽ không bỏ được ở giao diện, và nút "Bỏ
    quyền admin" thành nút bấm-không-làm-gì.

    `db_path=None` ⇒ rơi về env. Đó là đường cho các chỗ gọi chưa có DB trong
    tay, và nó **nghiêng về phía CHẶT hơn**: env rỗng thì không ai là admin.
    """
    e = email.strip().lower()
    if db_path is not None:
        from web import models
        try:
            return any(u["email"] == e and u["la_admin"]
                       for u in models.danh_sach_nguoi_dung(db_path))
        except Exception:  # noqa: BLE001 — DB hỏng thì KHÔNG phong ai làm admin
            log.error("không đọc được bảng người dùng — coi như không phải admin")
            return False
    return e in admin_tu_env()
