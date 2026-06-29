"""Tests voor het wachtwoord-slot (Basic Auth middleware)."""

from __future__ import annotations

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import BasicAuthMiddleware, check_basic_auth


def _basic(user: str, pw: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


def test_check_basic_auth() -> None:
    assert check_basic_auth(_basic("dunion", "geheim"), "dunion", "geheim") is True
    assert check_basic_auth(_basic("dunion", "fout"), "dunion", "geheim") is False
    assert check_basic_auth(None, "dunion", "geheim") is False
    assert check_basic_auth("Bearer xyz", "dunion", "geheim") is False


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware, user="dunion", password="geheim")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/secret")
    def secret():
        return {"ok": True}

    return app


def test_health_is_exempt() -> None:
    client = TestClient(_app())
    assert client.get("/health").status_code == 200  # zonder login


def test_protected_requires_auth() -> None:
    client = TestClient(_app())
    resp = client.get("/secret")
    assert resp.status_code == 401
    assert "Basic" in resp.headers.get("WWW-Authenticate", "")


def test_protected_with_correct_login() -> None:
    client = TestClient(_app())
    resp = client.get("/secret", headers={"Authorization": _basic("dunion", "geheim")})
    assert resp.status_code == 200


def test_protected_with_wrong_password() -> None:
    client = TestClient(_app())
    resp = client.get("/secret", headers={"Authorization": _basic("dunion", "fout")})
    assert resp.status_code == 401
