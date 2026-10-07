import os
import time

# Must be set before the app (and its settings singleton) is imported.
os.environ.update(
    {
        "PUBLIC_BASE_URL": "http://testserver",
        "DATABASE_URL": "sqlite://",
        "OIDC_CLIENT_SECRET": "test-secret",
        "KEYCLOAK_INTERNAL_URL": "http://keycloak.test:8080/auth",
    }
)

import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import oidc  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import UserSession  # noqa: E402

# Stand-in for Keycloak's realm signing key
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJWKSClient:
    def get_signing_key_from_jwt(self, _token):
        return type("SigningKey", (), {"key": _KEY.public_key()})()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(oidc, "jwks_client", lambda: _FakeJWKSClient())
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app, base_url=settings.public_base_url, follow_redirects=False) as c:
        yield c


def make_token(sub="alice-sub", aud=None, iss=None, exp_in=300, username=None, **extra) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "aud": aud or settings.api_audience,
        "iss": iss or settings.oidc_issuer,
        "iat": now,
        "exp": now + exp_in,
        "preferred_username": username or sub.split("-")[0],
        **extra,
    }
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": "test"})


def bearer(sub="alice-sub") -> dict:
    return {"Authorization": f"Bearer {make_token(sub=sub)}"}


def seed_session(sid="sid-1", sub="alice-sub", access_exp_in=300) -> str:
    now = int(time.time())
    with SessionLocal() as db:
        db.add(
            UserSession(
                id=sid,
                user_id=sub,
                username=sub.split("-")[0],
                access_token=make_token(sub=sub, exp_in=access_exp_in),
                refresh_token="rt-old",
                id_token="idt",
                access_expires_at=now + access_exp_in,
                created_at=now,
            )
        )
        db.commit()
    return sid
