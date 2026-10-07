from urllib.parse import parse_qs, urlparse

from app import oidc
from app.config import settings
from app.db import SessionLocal
from app.models import UserSession

from .conftest import make_token, seed_session


def test_pkce_matches_rfc7636_appendix_b():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert oidc.pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _start_login(client):
    resp = client.get("/api/auth/login")
    assert resp.status_code == 302
    url = urlparse(resp.headers["location"])
    return url, {k: v[0] for k, v in parse_qs(url.query).items()}


def _fake_tokens(monkeypatch, nonce, sub="alice-sub", id_aud=None):
    tokens = {
        "access_token": make_token(sub=sub),
        "id_token": make_token(sub=sub, aud=id_aud or settings.oidc_client_id, nonce=nonce),
        "refresh_token": "rt-1",
        "expires_in": 300,
    }
    monkeypatch.setattr(oidc, "exchange_code", lambda code, verifier: tokens)
    return tokens


def test_login_redirects_to_keycloak_with_pkce(client):
    url, q = _start_login(client)
    assert f"{url.scheme}://{url.netloc}{url.path}" == settings.oidc_auth_url
    assert q["response_type"] == "code"
    assert q["client_id"] == "todo-app"
    assert q["redirect_uri"] == settings.oidc_redirect_uri
    assert q["code_challenge_method"] == "S256"
    assert "openid" in q["scope"].split()
    assert client.cookies.get(settings.state_cookie_name) == q["state"]


def test_callback_creates_session(client, monkeypatch):
    _, q = _start_login(client)
    _fake_tokens(monkeypatch, q["nonce"])

    resp = client.get("/api/auth/callback", params={"code": "c", "state": q["state"]})
    assert resp.status_code == 302 and resp.headers["location"] == "/"
    set_cookie = resp.headers.get_list("set-cookie")
    assert any(c.startswith(f"{settings.session_cookie_name}=") and "HttpOnly" in c for c in set_cookie)

    me = client.get("/api/me")
    assert me.status_code == 200 and me.json()["sub"] == "alice-sub"


def test_callback_rejects_state_mismatch(client, monkeypatch):
    _, q = _start_login(client)
    _fake_tokens(monkeypatch, q["nonce"])
    resp = client.get("/api/auth/callback", params={"code": "c", "state": "forged"})
    assert resp.status_code == 400


def test_callback_rejects_reused_state(client, monkeypatch):
    _, q = _start_login(client)
    _fake_tokens(monkeypatch, q["nonce"])
    first = client.get("/api/auth/callback", params={"code": "c", "state": q["state"]})
    assert first.status_code == 302
    client.cookies.set(settings.state_cookie_name, q["state"], path="/api/auth")
    replay = client.get("/api/auth/callback", params={"code": "c", "state": q["state"]})
    assert replay.status_code == 400


def test_callback_rejects_wrong_nonce(client, monkeypatch):
    _, q = _start_login(client)
    _fake_tokens(monkeypatch, nonce="not-the-nonce")
    resp = client.get("/api/auth/callback", params={"code": "c", "state": q["state"]})
    assert resp.status_code == 400


def test_callback_rejects_id_token_for_other_client(client, monkeypatch):
    _, q = _start_login(client)
    _fake_tokens(monkeypatch, q["nonce"], id_aud="some-other-client")
    resp = client.get("/api/auth/callback", params={"code": "c", "state": q["state"]})
    assert resp.status_code == 400


def test_callback_passes_keycloak_error(client):
    resp = client.get("/api/auth/callback", params={"error": "access_denied"})
    assert resp.status_code == 400


def test_expiring_access_token_is_refreshed(client, monkeypatch):
    sid = seed_session(access_exp_in=5)  # inside the refresh margin
    new_access = make_token(sub="alice-sub")
    monkeypatch.setattr(
        oidc, "refresh", lambda rt: {"access_token": new_access, "refresh_token": "rt-new", "expires_in": 300}
    )
    client.cookies.set(settings.session_cookie_name, sid)
    assert client.get("/api/me").status_code == 200
    with SessionLocal() as db:
        s = db.get(UserSession, sid)
        assert s.refresh_token == "rt-new" and s.access_token == new_access


def test_failed_refresh_ends_session(client, monkeypatch):
    sid = seed_session(access_exp_in=5)

    def boom(rt):
        raise oidc.OIDCError("invalid_grant")

    monkeypatch.setattr(oidc, "refresh", boom)
    client.cookies.set(settings.session_cookie_name, sid)
    assert client.get("/api/me").status_code == 401
    with SessionLocal() as db:
        assert db.get(UserSession, sid) is None


def test_bearer_wrong_audience_or_issuer_rejected(client):
    for token in (
        make_token(aud="account"),
        make_token(iss="http://evil/auth/realms/todo"),
        make_token(exp_in=-120),
        "garbage",
    ):
        resp = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


def test_cross_origin_write_with_cookie_blocked(client):
    client.cookies.set(settings.session_cookie_name, seed_session())
    bad = client.post("/api/todos", json={"title": "x"}, headers={"Origin": "http://evil.example"})
    assert bad.status_code == 403
    ok = client.post("/api/todos", json={"title": "x"}, headers={"Origin": settings.public_base_url})
    assert ok.status_code == 201


def test_logout_clears_session_and_redirects_to_keycloak(client):
    sid = seed_session()
    client.cookies.set(settings.session_cookie_name, sid)
    resp = client.get("/api/auth/logout")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(settings.oidc_logout_url)
    assert "id_token_hint=idt" in resp.headers["location"]
    with SessionLocal() as db:
        assert db.get(UserSession, sid) is None
