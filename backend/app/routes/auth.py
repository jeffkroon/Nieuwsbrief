"""Login-/logout-routes voor het wachtwoord-slot (sessie-cookie)."""

from __future__ import annotations

import secrets as pysecrets
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.deps import SessionInfo, current_session_info, get_session
from app.middleware import COOKIE_NAME, SESSION_MAX_AGE, make_session_token
from app.ratelimit import SlidingWindowRateLimiter, client_ip
from app.repositories import tenants as tenants_repo
from app.services.passwords import verify_password

router = APIRouter(tags=["auth"])

# Max 5 loginpogingen per 5 minuten per IP (tegen brute-force).
_login_limiter = SlidingWindowRateLimiter(max_hits=5, window_seconds=300)

_LOGIN_HTML = Path(__file__).resolve().parent.parent / "static" / "login.html"


def _authenticate(
    username: str, password: str, settings: Settings, session: Session
) -> tuple[str, str] | None:
    """Bepaal (rol, tenant-binding) uit de inloggegevens, of None bij fout wachtwoord.

    Drie soorten logins:
    - admin (Dunion-beheer): ziet en mag alles
    - team (gedeeld wachtwoord): ongebonden company-sessie, ziet alles
    - klant: gebruikersnaam = bedrijfscode (slug) + eigen wachtwoord; de sessie
      wordt vergrendeld op dat ene bedrijf
    """
    if settings.admin_password and pysecrets.compare_digest(
        username, settings.admin_user
    ) and pysecrets.compare_digest(password, settings.admin_password):
        return ("admin", "")
    if settings.access_password and pysecrets.compare_digest(
        username, settings.access_user
    ) and pysecrets.compare_digest(password, settings.access_password):
        return ("company", "")
    tenant = tenants_repo.get_tenant_by_slug(session, username.strip().lower())
    if tenant is not None and verify_password(password, tenant.password_hash):
        return ("company", str(tenant.id))
    return None


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
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if not settings.access_password:
        return RedirectResponse("/", status_code=303)
    if not _login_limiter.allow(client_ip(request)):
        return RedirectResponse("/login?error=2", status_code=303)
    result = _authenticate(username, password, settings, session)
    if result is None:
        return RedirectResponse("/login?error=1", status_code=303)
    role, tenant_id = result
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        make_session_token(settings.access_password, role, tenant_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.get("/me", include_in_schema=False)
def me(info: SessionInfo = Depends(current_session_info)) -> dict:
    """Rol + eventuele bedrijfsbinding van de sessie (voor de frontend-UI)."""
    return {
        "role": info.role,
        "is_admin": info.role == "admin",
        "tenant_id": str(info.tenant_id) if info.tenant_id else None,
    }


@router.get("/logout", include_in_schema=False)
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
