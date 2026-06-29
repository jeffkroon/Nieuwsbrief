"""Tests voor de rate limiter en de toepassing op login + chat."""

from __future__ import annotations

import pytest

from app.ratelimit import SlidingWindowRateLimiter


def test_allows_up_to_limit_then_blocks() -> None:
    rl = SlidingWindowRateLimiter(max_hits=3, window_seconds=60)
    assert [rl.allow("ip1") for _ in range(5)] == [True, True, True, False, False]


def test_keys_are_independent() -> None:
    rl = SlidingWindowRateLimiter(max_hits=1, window_seconds=60)
    assert rl.allow("a") is True
    assert rl.allow("b") is True  # andere sleutel, eigen budget
    assert rl.allow("a") is False


def test_window_frees_up(monkeypatch) -> None:
    import app.ratelimit as mod

    t = {"now": 1000.0}
    monkeypatch.setattr(mod.time, "time", lambda: t["now"])
    rl = SlidingWindowRateLimiter(max_hits=2, window_seconds=10)
    assert rl.allow("ip") and rl.allow("ip")
    assert rl.allow("ip") is False
    t["now"] += 11  # venster voorbij
    assert rl.allow("ip") is True


def test_login_rate_limited(client) -> None:
    # Zelfde IP > 5 keer -> 6e poging krijgt de rate-limit-redirect.
    from app.config import Settings, get_settings
    from app.main import app
    from app.routes import auth

    auth._login_limiter.reset()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, supabase_connection_string="postgresql://x",
        secret_encryption_key="k", access_user="dunion", access_password="sterkwachtwoord",
    )
    try:
        headers = {"x-forwarded-for": "9.9.9.9"}
        codes = []
        for _ in range(6):
            r = client.post("/login", data={"username": "dunion", "password": "fout"},
                            headers=headers, follow_redirects=False)
            codes.append(r.headers.get("location"))
        assert codes[:5] == ["/login?error=1"] * 5  # fout wachtwoord
        assert codes[5] == "/login?error=2"          # nu rate-limited
    finally:
        app.dependency_overrides.pop(get_settings, None)
        auth._login_limiter.reset()


def test_chat_rate_limit_dependency() -> None:
    from fastapi import HTTPException
    from starlette.datastructures import Headers
    from starlette.requests import Request

    from app.routes import conversations as conv

    conv._chat_limiter.reset()

    def fake_request(ip: str) -> Request:
        scope = {"type": "http", "headers": Headers({"x-forwarded-for": ip}).raw, "client": (ip, 0)}
        return Request(scope)

    req = fake_request("8.8.8.8")
    for _ in range(15):
        conv.chat_rate_limit(req)  # mag
    with pytest.raises(HTTPException) as exc:
        conv.chat_rate_limit(req)  # 16e -> geblokkeerd
    assert exc.value.status_code == 429
    conv._chat_limiter.reset()
