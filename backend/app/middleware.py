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


def make_session_token(secret: str) -> str:
    payload = str(int(time.time()))
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def valid_session_token(token: str | None, secret: str, max_age: int = SESSION_MAX_AGE) -> bool:
    if not token or "." not in token:
        return False
    payload, _, sig = token.partition(".")
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        issued = int(payload)
    except ValueError:
        return False
    return (time.time() - issued) < max_age


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
