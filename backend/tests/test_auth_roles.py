"""Unit-tests voor rollen in het sessie-token."""

from __future__ import annotations

import time

from app.middleware import make_session_token, session_role, valid_session_token

SECRET = "test-secret"


def test_role_roundtrips() -> None:
    assert session_role(make_session_token(SECRET, "admin"), SECRET) == "admin"
    assert session_role(make_session_token(SECRET, "company"), SECRET) == "company"


def test_default_role_is_company() -> None:
    assert session_role(make_session_token(SECRET), SECRET) == "company"


def test_tampered_token_is_invalid() -> None:
    token = make_session_token(SECRET, "admin")
    payload, _, sig = token.rpartition(".")
    forged = f"admin:{payload.split(':')[1]}.{'0' * len(sig)}"
    assert session_role(forged, SECRET) is None
    assert valid_session_token(forged, SECRET) is False


def test_wrong_secret_rejected() -> None:
    token = make_session_token(SECRET, "admin")
    assert session_role(token, "other-secret") is None


def test_expired_token_rejected() -> None:
    token = make_session_token(SECRET, "admin")
    # max_age 0 -> meteen verlopen (issued is 'nu', verschil >= 0).
    time.sleep(0.01)
    assert session_role(token, SECRET, max_age=0) is None
