"""Tone of voice per bedrijf: eenmalig analyseren, cachen en hergebruiken.

Zo schrijft de assistent gegarandeerd in de huisstijl: de tone wordt in de
system-prompt geinjecteerd (zie build_system_prompt), niet afhankelijk van of het
model zelf de analyze-tool aanroept. De gecachte waarde staat in tenant.config, dus
het scrapen gebeurt maar een keer per bedrijf (goedkoop). Een refresh her-analyseert.
"""

from __future__ import annotations

import httpx
from sqlalchemy.orm import Session

from app.db.models import Tenant
from app.newsletter import extraction

TONE_CONFIG_KEY = "tone_of_voice"


def get_cached_tone(tenant: Tenant) -> str | None:
    return (tenant.config or {}).get(TONE_CONFIG_KEY) or None


def analyze_and_store_tone(
    session: Session, tenant: Tenant, llm, http_client: httpx.Client | None = None
) -> str | None:
    """Scrape de website, leid de tone af (Haiku) en bewaar in tenant.config.

    Geeft de tone terug, of None als er geen website is of het scrapen/analyseren
    mislukt. Overschrijft een bestaande gecachte tone (gebruikt voor 'opnieuw analyseren').
    """
    url = (tenant.config or {}).get("website_url")
    if not url:
        return None
    status, html = extraction.fetch_page(url, http_client)
    if status != 200 or not html:
        return None
    tone = extraction.extract_tone(llm, html, source_url=url)
    if not tone:
        return None
    tenant.config = {**(tenant.config or {}), TONE_CONFIG_KEY: tone}
    session.commit()
    return tone


def ensure_tone(
    session: Session, tenant: Tenant, llm, http_client: httpx.Client | None = None
) -> str | None:
    """Gecachte tone of voice; analyseer eenmalig als die er nog niet is.

    Tone is nice-to-have: bij een fout (geen netwerk, geen website) geeft dit None
    terug en gaat het gesprek gewoon door (de prompt-instructie blijft dan gelden).
    """
    cached = get_cached_tone(tenant)
    if cached:
        return cached
    try:
        return analyze_and_store_tone(session, tenant, llm, http_client)
    except Exception:
        return None
