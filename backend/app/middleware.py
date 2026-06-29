"""Eenvoudig wachtwoord-slot (HTTP Basic Auth) voor publieke deploys.

Alleen actief als ACCESS_PASSWORD is gezet. /health blijft vrij (voor de
health-check van de hosting). De browser onthoudt de inlog, dus de chat- en
foto-pagina werken daarna zonder gedoe.
"""

from __future__ import annotations

import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

EXEMPT_PATHS = {"/health"}


def check_basic_auth(authorization: str | None, user: str, password: str) -> bool:
    """True als de Authorization-header een geldige Basic-login bevat."""
    if not authorization or not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    given_user, _, given_pw = decoded.partition(":")
    return secrets.compare_digest(given_user, user) and secrets.compare_digest(given_pw, password)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, user: str, password: str) -> None:
        super().__init__(app)
        self._user = user
        self._password = password

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        if check_basic_auth(request.headers.get("Authorization"), self._user, self._password):
            return await call_next(request)
        return PlainTextResponse(
            "Authenticatie vereist",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Nieuwsbrief"'},
        )
