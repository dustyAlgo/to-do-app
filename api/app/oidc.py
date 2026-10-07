"""Hand-written OAuth 2.0 / OpenID Connect client for Keycloak (no OIDC library).

Browser-facing URLs (authorize, logout) use the public host; token + JWKS calls go
server-to-server to http://keycloak:8080. Tokens are validated against the PUBLIC issuer,
which Keycloak always puts in "iss" because KC_HOSTNAME is fixed.
"""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt

from .config import settings


class OIDCError(Exception):
    """Any failure talking to Keycloak or validating a token."""


# ---------------------------------------------------------------- PKCE (RFC 7636)
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def pkce_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)  # 86 chars, within the 43–128 allowed
    return verifier, pkce_challenge(verifier)


# ---------------------------------------------------------------- front-channel URLs
def build_auth_url(state: str, nonce: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.oidc_auth_url}?{urlencode(params)}"


def build_logout_url(id_token: str | None) -> str:
    params = {
        "client_id": settings.oidc_client_id,
        "post_logout_redirect_uri": f"{settings.public_base_url}/",
    }
    if id_token:
        params["id_token_hint"] = id_token  # skips Keycloak's "do you want to log out?" page
    return f"{settings.oidc_logout_url}?{urlencode(params)}"


# ---------------------------------------------------------------- token endpoint
def _token_request(data: dict) -> dict:
    try:
        resp = httpx.post(
            settings.oidc_token_url,
            data=data,
            auth=(settings.oidc_client_id, settings.oidc_client_secret),  # client_secret_basic
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise OIDCError(f"token endpoint unreachable: {exc}") from exc
    if resp.status_code != 200:
        raise OIDCError(f"token endpoint returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def exchange_code(code: str, code_verifier: str) -> dict:
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.oidc_redirect_uri,
            "code_verifier": code_verifier,
        }
    )


def refresh(refresh_token: str) -> dict:
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


def token_expiry(tokens: dict) -> int:
    return int(time.time()) + int(tokens.get("expires_in", 60))


# ---------------------------------------------------------------- JWT validation
_jwks: jwt.PyJWKClient | None = None


def jwks_client() -> jwt.PyJWKClient:
    """Caches Keycloak's signing keys; refetches automatically on an unknown `kid` (key rotation)."""
    global _jwks
    if _jwks is None:
        _jwks = jwt.PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=300)
    return _jwks


def _decode(token: str, audience: str) -> dict:
    try:
        key = jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=settings.oidc_issuer,
            leeway=settings.jwt_leeway_seconds,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OIDCError(f"invalid token: {exc}") from exc


def validate_id_token(id_token: str, expected_nonce: str) -> dict:
    claims = _decode(id_token, audience=settings.oidc_client_id)
    if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
        raise OIDCError("invalid token: nonce mismatch")
    if claims.get("azp", settings.oidc_client_id) != settings.oidc_client_id:
        raise OIDCError("invalid token: azp mismatch")
    return claims


def validate_access_token(access_token: str) -> dict:
    return _decode(access_token, audience=settings.api_audience)
