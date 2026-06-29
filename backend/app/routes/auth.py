"""Login-/logout-routes voor het wachtwoord-slot (sessie-cookie)."""

from __future__ import annotations

import secrets as pysecrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.config import Settings, get_settings
from app.middleware import COOKIE_NAME, SESSION_MAX_AGE, make_session_token
from app.ratelimit import SlidingWindowRateLimiter, client_ip

router = APIRouter(tags=["auth"])

# Max 5 loginpogingen per 5 minuten per IP (tegen brute-force).
_login_limiter = SlidingWindowRateLimiter(max_hits=5, window_seconds=300)

_LOGIN_HTML = Path(__file__).resolve().parent.parent / "static" / "login.html"


@router.get("/login", include_in_schema=False, response_model=None)
def login_page(settings: Settings = Depends(get_settings)) -> FileResponse | RedirectResponse:
    # Geen slot ingesteld? Dan is er niks om in te loggen.
    if not settings.access_password:
        return RedirectResponse("/", status_code=303)
    return FileResponse(_LOGIN_HTML)


@router.post("/login", include_in_schema=False)
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if not settings.access_password:
        return RedirectResponse("/", status_code=303)
    if not _login_limiter.allow(client_ip(request)):
        return RedirectResponse("/login?error=2", status_code=303)
    ok = pysecrets.compare_digest(username, settings.access_user) and pysecrets.compare_digest(
        password, settings.access_password
    )
    if not ok:
        return RedirectResponse("/login?error=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        make_session_token(settings.access_password),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/logout", include_in_schema=False)
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
