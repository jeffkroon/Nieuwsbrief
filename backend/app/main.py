"""FastAPI-applicatie voor het nieuwsbrief-product."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import get_settings
from app.middleware import LoginAuthMiddleware
from app.routes import auth, conversations, health, images, tenants

app = FastAPI(title="Nieuwsbrief-product", version="0.1.0")

# Wachtwoord-slot alleen aanzetten als ACCESS_PASSWORD is gezet (bv. op de deploy).
_settings = get_settings()
if _settings.access_password:
    app.add_middleware(LoginAuthMiddleware, secret=_settings.access_password)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(tenants.router)
app.include_router(conversations.router)
app.include_router(images.router)

_INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serveert de web-chat frontend."""
    return FileResponse(_INDEX_HTML)
