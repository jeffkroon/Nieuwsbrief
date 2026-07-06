"""Tests voor het wachtwoord-slot: sessie-cookie + login/logout-flow."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app as real_app
from app.middleware import (
    COOKIE_NAME,
    LoginAuthMiddleware,
    make_session_token,
    valid_session_token,
)
from app.routes import auth

SECRET = "geheim123"


def test_session_token_roundtrip() -> None:
    token = make_session_token(SECRET)
    assert valid_session_token(token, SECRET) is True
    assert valid_session_token(token, "ander-geheim") is False
    assert valid_session_token(None, SECRET) is False
    assert valid_session_token("rommel", SECRET) is False


def test_expired_token_invalid() -> None:
    token = make_session_token(SECRET)
    assert valid_session_token(token, SECRET, max_age=-1) is False


def _guarded_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LoginAuthMiddleware, secret=SECRET)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/secret")
    def secret():
        return PlainTextResponse("geheim")

    return app


def test_health_exempt() -> None:
    assert TestClient(_guarded_app()).get("/health").status_code == 200


def test_page_redirects_to_login_when_not_logged_in() -> None:
    client = TestClient(_guarded_app())
    resp = client.get("/secret", headers={"accept": "text/html"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_api_call_returns_401_when_not_logged_in() -> None:
    client = TestClient(_guarded_app())
    resp = client.get("/secret", headers={"accept": "application/json"})
    assert resp.status_code == 401


def test_valid_cookie_grants_access() -> None:
    client = TestClient(_guarded_app())
    client.cookies.set(COOKIE_NAME, make_session_token(SECRET))
    assert client.get("/secret", headers={"accept": "text/html"}).status_code == 200


# --- login-route flow (op de echte app, met overschreven settings) ---
def _settings_with_password() -> Settings:
    return Settings(
        _env_file=None,
        supabase_connection_string="postgresql://x",
        secret_encryption_key="k",
        access_user="dunion",
        access_password=SECRET,
    )


def test_login_wrong_password_redirects_with_error(session) -> None:
    # get_session overriden: de login doet nu ook een tenant-lookup (klant-logins)
    # en mag in tests nooit de echte database raken.
    from app.deps import get_session

    real_app.dependency_overrides[get_settings] = _settings_with_password
    real_app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(real_app)
        resp = client.post(
            "/login", data={"username": "dunion", "password": "fout"}, follow_redirects=False
        )
        assert resp.status_code == 303 and resp.headers["location"] == "/login?error=1"
    finally:
        real_app.dependency_overrides.pop(get_settings, None)
        real_app.dependency_overrides.pop(get_session, None)


def test_login_correct_sets_cookie() -> None:
    real_app.dependency_overrides[get_settings] = _settings_with_password
    try:
        client = TestClient(real_app)
        resp = client.post(
            "/login", data={"username": "dunion", "password": SECRET}, follow_redirects=False
        )
        assert resp.status_code == 303 and resp.headers["location"] == "/"
        assert COOKIE_NAME in resp.cookies
    finally:
        real_app.dependency_overrides.pop(get_settings, None)
