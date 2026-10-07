import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import oidc
from .config import settings
from .db import get_db
from .models import UserSession

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class CurrentUser:
    sub: str
    username: str | None


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")


def apply_token_set(session: UserSession, tokens: dict) -> None:
    """Store a token response on the session (refresh tokens rotate, so always take the new one)."""
    session.access_token = tokens["access_token"]
    session.refresh_token = tokens.get("refresh_token", session.refresh_token)
    session.id_token = tokens.get("id_token", session.id_token)
    session.access_expires_at = oidc.token_expiry(tokens)


def _refresh_if_needed(db: Session, session: UserSession) -> UserSession:
    if session.access_expires_at - time.time() > settings.refresh_margin_seconds:
        return session
    # Lock the row so parallel requests don't both spend the (single-use) refresh token.
    session = db.get(UserSession, session.id, with_for_update=True, populate_existing=True)
    if session is None:
        raise _unauthorized()
    if session.access_expires_at - time.time() > settings.refresh_margin_seconds:
        db.commit()  # another request refreshed it while we waited
        return session
    try:
        apply_token_set(session, oidc.refresh(session.refresh_token))
    except oidc.OIDCError:
        db.delete(session)  # SSO session ended upstream → force a new login
        db.commit()
        raise _unauthorized()
    db.commit()
    return session


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    # 1) Bearer token (E2E tests / machine clients) — stateless, no cookie, no CSRF risk
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            claims = oidc.validate_access_token(auth[7:].strip())
        except oidc.OIDCError:
            raise _unauthorized()
        return CurrentUser(sub=claims["sub"], username=claims.get("preferred_username"))

    # 2) Browser session cookie
    session_id = request.cookies.get(settings.session_cookie_name)
    session = db.get(UserSession, session_id) if session_id else None
    if session is None:
        raise _unauthorized()

    # CSRF: cookie-authenticated writes must come from our own origin
    if request.method in UNSAFE_METHODS and request.headers.get("origin") != settings.public_base_url:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cross-origin request blocked")

    session = _refresh_if_needed(db, session)
    try:
        claims = oidc.validate_access_token(session.access_token)
    except oidc.OIDCError:
        db.delete(session)
        db.commit()
        raise _unauthorized()
    return CurrentUser(sub=claims["sub"], username=session.username)
