"""Health-check, plus een diagnose voor sites die onze server blokkeren."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_session, require_admin
from app.newsletter.extraction import SITE_HEADERS, USER_AGENT, fetch_page

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("select 1"))
    return {"status": "ok"}


@router.get("/health/uitgaand", dependencies=[Depends(require_admin)])
def uitgaand(url: str | None = None) -> dict:
    """Vanaf welk IP-adres benadert deze server de buitenwereld, en komt hij binnen?

    Bot-bescherming blokkeert meestal het IP, niet de user-agent: dezelfde code
    haalt een pagina lokaal probleemloos op en krijgt vanaf de server een 403. Dit
    laat zien welk adres bij de klant moet worden toegelaten, en test meteen een
    losse URL zodat je niet hoeft te gokken.
    """
    antwoord: dict = {"user_agent": USER_AGENT, "ip": None, "ip_fout": None}
    try:
        with httpx.Client(timeout=8.0) as client:
            antwoord["ip"] = client.get("https://api.ipify.org").text.strip()
    except httpx.HTTPError as exc:
        antwoord["ip_fout"] = f"kon het eigen IP niet bepalen: {exc}"

    if url:
        status, html = fetch_page(url)
        antwoord["test"] = {
            "url": url,
            "status": status,
            "tekens": len(html),
            "geblokkeerd": status == 403,
        }
    antwoord["headers"] = dict(SITE_HEADERS)
    return antwoord
