"""FastAPI-applicatie voor het nieuwsbrief-product."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.middleware import LoginAuthMiddleware
from app.static_assets import (
    REVALIDATE,
    RevalidatingStaticFiles,
    asset_version,
    versioned_html,
)
from app.routes import (
    admin,
    auth,
    conversations,
    health,
    images,
    newsletters,
    templates,
    tenants,
)

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
app.include_router(templates.router)
app.include_router(newsletters.router)
app.include_router(admin.router)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

# De frontend is opgesplitst in losse bestanden (app.css, core.js, chat.js, ...)
# in plaats van een enkel bestand van tweeduizend regels. Ze zitten achter
# hetzelfde wachtwoord-slot als de rest: de middleware ziet /static net als
# elke andere pagina.
# Altijd hercontroleren en een versie per deploy: zie app/static_assets.py.
app.mount("/static", RevalidatingStaticFiles(directory=_STATIC_DIR), name="static")
_INDEX_VERSIONED = versioned_html(_INDEX_HTML.read_text(), asset_version(_STATIC_DIR))


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    """Serveert de web-chat frontend, met versie-URL's voor css/js."""
    return HTMLResponse(_INDEX_VERSIONED, headers={"Cache-Control": REVALIDATE})
