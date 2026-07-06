"""Wachtwoord-slot met een nette eigen loginpagina (sessie-cookie).

Alleen actief als ACCESS_PASSWORD is gezet. /health, /login en /logout blijven
vrij. Niet-ingelogd: paginaverzoeken worden naar /login gestuurd, API-verzoeken
krijgen 401. De cookie wordt ondertekend met HMAC (geen extra dependency).
"""

from __future__ import annotations

import hashlib
import hmac
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

COOKIE_NAME = "nb_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 dagen
EXEMPT_PATHS = {"/health", "/login", "/logout"}
DEFAULT_ROLE = "company"


def make_session_token(secret: str, role: str = DEFAULT_ROLE, tenant_id: str = "") -> str:
    """Token-payload: rol:tenant:tijdstip. Lege tenant = niet aan één bedrijf gebonden
    (admin, of het gedeelde team-wachtwoord)."""
    payload = f"{role}:{tenant_id}:{int(time.time())}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def session_claims(
    token: str | None, secret: str, max_age: int = SESSION_MAX_AGE
) -> tuple[str, str | None] | None:
    """Geef (rol, tenant_id-of-None) uit een geldig token, of None bij ongeldig/verlopen.

    Oude tokens (rol:tijdstip, van vóór de tenant-binding) blijven de resterende
    cookie-looptijd geldig als ongebonden sessie.
    """
    if not token or "." not in token:
        return None
    payload, _, sig = token.rpartition(".")
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    parts = payload.split(":")
    if len(parts) == 3:
        role, tenant_id, issued_raw = parts
    elif len(parts) == 2:  # oud formaat zonder tenant
        role, issued_raw = parts
        tenant_id = ""
    else:
        return None
    try:
        issued = int(issued_raw)
    except ValueError:
        return None
    if (time.time() - issued) >= max_age:
        return None
    return (role or DEFAULT_ROLE, tenant_id or None)


def session_role(token: str | None, secret: str, max_age: int = SESSION_MAX_AGE) -> str | None:
    """Geef de rol uit een geldig token terug, of None bij ongeldig/verlopen."""
    claims = session_claims(token, secret, max_age)
    return claims[0] if claims else None


def valid_session_token(token: str | None, secret: str, max_age: int = SESSION_MAX_AGE) -> bool:
    return session_role(token, secret, max_age) is not None


class LoginAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, secret: str) -> None:
        super().__init__(app)
        self._secret = secret

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in EXEMPT_PATHS or path.startswith("/login"):
            return await call_next(request)
        if valid_session_token(request.cookies.get(COOKIE_NAME), self._secret):
            return await call_next(request)
        # Niet ingelogd: pagina's -> naar login; API-calls -> 401.
        wants_html = request.method == "GET" and "text/html" in request.headers.get("accept", "")
        if wants_html:
            return RedirectResponse("/login", status_code=303)
        return JSONResponse({"detail": "Niet ingelogd"}, status_code=401)
