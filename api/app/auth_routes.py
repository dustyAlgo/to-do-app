"""Downstream auth: OIDC Authorization Code + PKCE against Keycloak (upstream)."""

import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete
from sqlalchemy.orm import Session

from . import oidc
from .config import settings
from .db import get_db
from .deps import apply_token_set
from .models import OidcLoginState, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

STATE_COOKIE_PATH = "/api/auth"


def _bad_login(reason: str) -> HTTPException:
    # TODO: render a friendly HTML page with a "try again" link instead of JSON
    return HTTPException(400, f"login failed: {reason}")


@router.get("/login")
def login(db: Session = Depends(get_db)):
    now = int(time.time())
    db.execute(delete(OidcLoginState).where(OidcLoginState.created_at < now - settings.login_state_ttl_seconds))

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = oidc.new_pkce()
    db.add(OidcLoginState(state=state, code_verifier=verifier, nonce=nonce, created_at=now))
    db.commit()

    resp = RedirectResponse(oidc.build_auth_url(state, nonce, challenge), status_code=302)
    resp.set_cookie(
        settings.state_cookie_name,
        state,
        max_age=settings.login_state_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=STATE_COOKIE_PATH,
    )
    return resp


@router.get("/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
):
    if error:
        raise _bad_login(f"{error}: {error_description or ''}".strip())
    if not code or not state:
        raise _bad_login("missing code or state")

    # 1. state must match the cookie (binds the response to this browser) and be unused
    cookie_state = request.cookies.get(settings.state_cookie_name)
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise _bad_login("state mismatch")
    pending = db.get(OidcLoginState, state)
    if pending is None:
        raise _bad_login("unknown or already used state")
    db.delete(pending)  # single use
    db.commit()
    if time.time() - pending.created_at > settings.login_state_ttl_seconds:
        raise _bad_login("login took too long, please retry")

    # 2. code → tokens (server-to-server, with PKCE verifier + client secret)
    # 3. validate both tokens
    try:
        tokens = oidc.exchange_code(code, pending.code_verifier)
        id_claims = oidc.validate_id_token(tokens["id_token"], pending.nonce)
        access_claims = oidc.validate_access_token(tokens["access_token"])
    except (oidc.OIDCError, KeyError) as exc:
        raise _bad_login(str(exc))
    if id_claims["sub"] != access_claims["sub"]:
        raise _bad_login("subject mismatch between tokens")

    # 4. server-side session; the browser only gets an opaque id
    now = int(time.time())
    session = UserSession(
        id=secrets.token_urlsafe(32),
        user_id=id_claims["sub"],
        username=id_claims.get("preferred_username"),
        created_at=now,
    )
    apply_token_set(session, tokens)
    db.add(session)
    db.commit()

    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        settings.session_cookie_name,
        session.id,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    resp.delete_cookie(settings.state_cookie_name, path=STATE_COOKIE_PATH)
    return resp


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    id_token = None
    session_id = request.cookies.get(settings.session_cookie_name)
    session = db.get(UserSession, session_id) if session_id else None
    if session is not None:
        id_token = session.id_token
        db.delete(session)
        db.commit()

    # RP-initiated logout: also ends the upstream Keycloak SSO session
    resp = RedirectResponse(oidc.build_logout_url(id_token), status_code=302)
    resp.delete_cookie(settings.session_cookie_name, path="/")
    return resp
