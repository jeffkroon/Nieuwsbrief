"""FastAPI-applicatie voor het nieuwsbrief-product."""

from __future__ import annotations

from fastapi import FastAPI

from app.routes import health, tenants

app = FastAPI(title="Nieuwsbrief-product", version="0.1.0")

app.include_router(health.router)
app.include_router(tenants.router)
