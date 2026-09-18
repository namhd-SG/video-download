"""Tests for web/auth.py — Cloudflare Access JWT verification.

Key material is generated here and injected through `certs_fetcher`, so none
of this touches the network. Tokens are signed with `google.auth.crypt`, the
same library that verifies them, which keeps the test honest about format
while still letting us forge, expire, and tamper at will.

Every deny test has a positive control next to it: a test that proves the
same request shape PASSES when the one thing under test is correct.
Otherwise a 401 could come from anywhere and the test would still be green.
"""
from __future__ import annotations

import base64
import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from starlette.requests import Request

from google.auth import crypt
from google.auth import jwt as google_jwt

from web import auth as auth_mod

TEAM_DOMAIN = "probeteam.cloudflareaccess.com"
AUD = "aud-tag-for-tests"


def _self_signed_pem(key: rsa.RSAPrivateKey) -> str:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-access")])
    now = dt.datetime.now(dt.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=3650))
        .sign(key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
        .decode()
    )


class _Keypair:
    """One RSA key plus the PEM cert and signer built from it."""

    def __init__(self, kid: str) -> None:
        self.kid = kid
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.cert_pem = _self_signed_pem(key)
        self.signer = crypt.RSASigner.from_string(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            key_id=kid,
        )


# 2048-bit keygen is slow; one pair per session is plenty. `cloudflare` is the
# legitimate team key, `attacker` is a key Cloudflare never published.
@pytest.fixture(scope="module")
def cloudflare_key() -> _Keypair:
    return _Keypair("kid-cloudflare")


@pytest.fixture(scope="module")
def attacker_key() -> _Keypair:
    return _Keypair("kid-attacker")


def mint(signer_key: _Keypair, *, aud=AUD, email: str | None = "nhanvien@astronex.ai",
         expires_in: int = 3600, extra: dict | None = None) -> str:
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    payload: dict = {
        "aud": aud,
        "iat": now - 10,
        "exp": now + expires_in,
        "iss": f"https://{TEAM_DOMAIN}",
        "sub": "subject-id-1",
    }
    if email is not None:
        payload["email"] = email
    if extra:
        payload.update(extra)
    token = google_jwt.encode(signer_key.signer, payload, header={"kid": signer_key.kid})
    # google.auth.jwt.encode returns BYTES. Header values are str, and a
    # bytes token silently takes a different code path — decode here or the
    # test is exercising something the server never sees.
    return token.decode("ascii")


def make_verifier(cloudflare_key: _Keypair, **kwargs) -> auth_mod.AccessVerifier:
    calls: list[str] = []

    def fetcher(url: str) -> dict[str, str]:
        calls.append(url)
        return {cloudflare_key.kid: cloudflare_key.cert_pem}

    verifier = auth_mod.AccessVerifier(
        team_domain=kwargs.pop("team_domain", TEAM_DOMAIN),
        aud=kwargs.pop("aud", AUD),
        certs_fetcher=kwargs.pop("certs_fetcher", fetcher),
        **kwargs,
    )
    verifier.test_fetch_calls = calls  # type: ignore[attr-defined]
    return verifier


def make_request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/jobs",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


# ---------------------------------------------------------------------------
# Positive controls — if these break, every 401 below proves nothing.
# ---------------------------------------------------------------------------

def test_valid_jwt_returns_the_email_as_identity(cloudflare_key):
    verifier = make_verifier(cloudflare_key)
    assert verifier.verify(mint(cloudflare_key)) == "nhanvien@astronex.ai"


def test_aud_as_a_LIST_is_accepted(cloudflare_key):
    """Cloudflare Access mints `aud` as a LIST, and google-auth's own
    `audience=` argument REJECTS that shape (measured: "Token has wrong
    audience ['x'], expected one of ['x']"). web/auth.py therefore checks
    `aud` itself. Drop that handling and this goes red while the str-aud
    test above stays green — which is exactly how this bug would ship."""
    verifier = make_verifier(cloudflare_key)
    assert verifier.verify(mint(cloudflare_key, aud=[AUD])) == "nhanvien@astronex.ai"


def test_aud_list_containing_other_tags_still_matches_ours(cloudflare_key):
    verifier = make_verifier(cloudflare_key)
    assert verifier.verify(mint(cloudflare_key, aud=["someone-else", AUD]))


# ---------------------------------------------------------------------------
# ĐỘT BIẾN (plan phase-05): a forged identity header with no valid JWT ⇒ 401.
# ---------------------------------------------------------------------------

def test_forged_email_header_without_jwt_is_401(cloudflare_key, monkeypatch):
    """The whole reason this module exists: `Cf-Access-Authenticated-User-Email`
    is plain text any local process can set. Trust it and this returns an
    identity instead of raising."""
    monkeypatch.setattr(auth_mod, "_verifier", make_verifier(cloudflare_key))
    request = make_request({"Cf-Access-Authenticated-User-Email": "sep@astronex.ai"})

    with pytest.raises(HTTPException) as exc_info:
        auth_mod.require_user(request)

    assert exc_info.value.status_code == 401


def test_same_request_WITH_a_valid_jwt_passes(cloudflare_key, monkeypatch):
    """Positive control for the test above — proves the 401 came from the
    missing JWT, not from the fake request object or the header plumbing."""
    monkeypatch.setattr(auth_mod, "_verifier", make_verifier(cloudflare_key))
    request = make_request({
        "Cf-Access-Authenticated-User-Email": "sep@astronex.ai",
        auth_mod.ACCESS_JWT_HEADER: mint(cloudflare_key),
    })

    # Danh tính lấy từ JWT, KHÔNG phải từ header email giả đi kèm.
    assert auth_mod.require_user(request) == "nhanvien@astronex.ai"


def test_no_header_at_all_is_401(cloudflare_key, monkeypatch):
    monkeypatch.setattr(auth_mod, "_verifier", make_verifier(cloudflare_key))
    with pytest.raises(HTTPException) as exc_info:
        auth_mod.require_user(make_request({}))
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Token-level rejections
# ---------------------------------------------------------------------------

def test_token_signed_by_a_key_cloudflare_never_published_is_denied(
        cloudflare_key, attacker_key):
    """Forging the payload is easy; forging the signature is the point."""
    verifier = make_verifier(cloudflare_key)
    with pytest.raises(auth_mod.AccessDenied):
        verifier.verify(mint(attacker_key))


def test_tampered_signature_is_denied(cloudflare_key):
    head, body, sig = mint(cloudflare_key).split(".")
    raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    flipped = base64.urlsafe_b64encode(bytes([raw[0] ^ 0xFF]) + raw[1:]).rstrip(b"=")
    verifier = make_verifier(cloudflare_key)
    with pytest.raises(auth_mod.AccessDenied):
        verifier.verify(f"{head}.{body}.{flipped.decode()}")


def test_expired_token_is_denied(cloudflare_key):
    verifier = make_verifier(cloudflare_key)
    with pytest.raises(auth_mod.AccessDenied):
        verifier.verify(mint(cloudflare_key, expires_in=-60))


def test_token_for_another_access_application_is_denied(cloudflare_key):
    """Signed by the real team key, but issued for a DIFFERENT application —
    e.g. the Promax hostname next door on the same Cloudflare team."""
    verifier = make_verifier(cloudflare_key)
    with pytest.raises(auth_mod.AccessDenied):
        verifier.verify(mint(cloudflare_key, aud="promax-application-aud"))


def test_aud_list_without_our_tag_is_denied(cloudflare_key):
    verifier = make_verifier(cloudflare_key)
    with pytest.raises(auth_mod.AccessDenied):
        verifier.verify(mint(cloudflare_key, aud=["promax-aud", "other-aud"]))


@pytest.mark.parametrize("junk", ["", "abc", "a.b.c", "a.b", "....", None])
def test_junk_tokens_are_denied_not_crashed(cloudflare_key, junk):
    """Measured: malformed input raises MalformedError / binascii.Error, not
    one tidy type. Catch too narrowly and these become 500s."""
    verifier = make_verifier(cloudflare_key)
    with pytest.raises(auth_mod.AccessDenied):
        verifier.verify(junk)


def test_token_with_no_identity_claim_is_denied(cloudflare_key):
    """A JWT we cannot attribute is useless: `nguoi_tao` feeds the per-user
    cookie-jar filename, so an empty identity would pool everyone together."""
    verifier = make_verifier(cloudflare_key)
    token = mint(cloudflare_key, email=None, extra={"sub": ""})
    with pytest.raises(auth_mod.AccessDenied):
        verifier.verify(token)


def test_service_token_falls_back_to_common_name(cloudflare_key):
    verifier = make_verifier(cloudflare_key)
    token = mint(cloudflare_key, email=None, extra={"common_name": "ci-runner"})
    assert verifier.verify(token) == "ci-runner"


# ---------------------------------------------------------------------------
# "Chưa cấu hình" must not look like "token sai" — and must never open up.
# ---------------------------------------------------------------------------

def test_unconfigured_access_raises_config_error_not_denied(cloudflare_key):
    verifier = make_verifier(cloudflare_key, team_domain="", aud="")
    with pytest.raises(auth_mod.AccessConfigError):
        verifier.verify(mint(cloudflare_key))


def test_unconfigured_access_is_503_never_a_default_identity(monkeypatch, cloudflare_key):
    monkeypatch.setattr(auth_mod, "_verifier",
                        make_verifier(cloudflare_key, team_domain="", aud=""))
    request = make_request({auth_mod.ACCESS_JWT_HEADER: mint(cloudflare_key)})
    with pytest.raises(HTTPException) as exc_info:
        auth_mod.require_user(request)
    # 503, not 401: a misdeployed service and a blocked attacker are different
    # facts and must not print the same answer.
    assert exc_info.value.status_code == 503


def test_unreachable_cert_endpoint_is_503_not_an_open_door(cloudflare_key, monkeypatch):
    def boom(url: str) -> dict[str, str]:
        raise OSError("connection refused")

    monkeypatch.setattr(auth_mod, "_verifier",
                        make_verifier(cloudflare_key, certs_fetcher=boom))
    request = make_request({auth_mod.ACCESS_JWT_HEADER: mint(cloudflare_key)})
    with pytest.raises(HTTPException) as exc_info:
        auth_mod.require_user(request)
    assert exc_info.value.status_code == 503


def test_empty_public_certs_is_a_config_error(cloudflare_key):
    verifier = make_verifier(cloudflare_key, certs_fetcher=lambda url: {})
    with pytest.raises(auth_mod.AccessConfigError):
        verifier.verify(mint(cloudflare_key))


def test_failed_fetch_does_not_freeze_an_empty_cache(cloudflare_key):
    """Mốc "đã nạp khoá" ghi SAU khi có khoá thật. Ghi trước thì một lượt
    fetch trượt sẽ khoá cache rỗng suốt TTL và mọi request sau đó chết oan."""
    attempts: list[int] = []

    def flaky(url: str) -> dict[str, str]:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("first call fails")
        return {cloudflare_key.kid: cloudflare_key.cert_pem}

    verifier = make_verifier(cloudflare_key, certs_fetcher=flaky)
    with pytest.raises(auth_mod.AccessConfigError):
        verifier.verify(mint(cloudflare_key))
    # Lượt thứ hai phải thử lại và ăn — không bị cache rỗng chặn.
    assert verifier.verify(mint(cloudflare_key)) == "nhanvien@astronex.ai"
    assert len(attempts) == 2


def test_certs_are_cached_within_the_ttl(cloudflare_key):
    verifier = make_verifier(cloudflare_key)
    for _ in range(3):
        verifier.verify(mint(cloudflare_key))
    assert len(verifier.test_fetch_calls) == 1


def test_certs_are_refetched_after_the_ttl(cloudflare_key, monkeypatch):
    """Positive control for the cache test: proves the single fetch above is
    caching, not a fetcher that only ever works once."""
    verifier = make_verifier(cloudflare_key)
    verifier.verify(mint(cloudflare_key))
    monkeypatch.setattr(auth_mod.time, "monotonic",
                        lambda: verifier._certs_fetched_at + auth_mod.CERTS_TTL_SECONDS + 1)
    verifier.verify(mint(cloudflare_key))
    assert len(verifier.test_fetch_calls) == 2


@pytest.mark.parametrize("configured", [
    "probeteam.cloudflareaccess.com",
    "https://probeteam.cloudflareaccess.com",
    "https://probeteam.cloudflareaccess.com/",
])
def test_team_domain_is_normalised_into_one_certs_url(cloudflare_key, configured):
    """The env var is typed by hand into ~/.config/videodl/env; a stray
    scheme or slash must not produce https://https://... and a 503."""
    verifier = make_verifier(cloudflare_key, team_domain=configured)
    assert verifier.certs_url == f"https://{TEAM_DOMAIN}/cdn-cgi/access/certs"


def test_env_vars_are_read_through_the_ENV_constants(monkeypatch, cloudflare_key):
    """Nghiệm thu cấu hình bằng is_configured(), kèm ca âm: bỏ biến ⇒ False.
    Grep chuỗi tên biến không ra vì chúng nằm trong hằng số ENV_*."""
    monkeypatch.setenv(auth_mod.ENV_TEAM_DOMAIN, TEAM_DOMAIN)
    monkeypatch.setenv(auth_mod.ENV_AUD, AUD)
    assert auth_mod.AccessVerifier().is_configured() is True

    monkeypatch.delenv(auth_mod.ENV_AUD)
    assert auth_mod.AccessVerifier().is_configured() is False
