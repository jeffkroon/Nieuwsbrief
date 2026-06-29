"""Site-agnostische extractie van wedstrijden en prijzen met een LLM.

In plaats van per-site CSS-selectors: haal de pagina op, zet 'm om naar leesbare
tekst (met absolute links), en laat Claude er gestructureerd wedstrijden +
prijzen + URL's uithalen. Werkt op elke klantensite en blijft werken als de
opmaak verandert. Gegrond: alleen wat echt op de pagina staat, niets verzinnen.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import urljoin

import httpx

from app.newsletter.models import PRICE_ON_REQUEST

EXTRACT_MODEL = "claude-haiku-4-5"  # goedkoop model voor extractie
MAX_PAGE_CHARS = 40000

_MATCHES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "home": {"type": "string"},
                    "away": {"type": "string"},
                    "url": {"type": "string"},
                    "price": {"type": ["string", "null"]},
                },
                "required": ["home", "away", "url", "price"],
            },
        }
    },
    "required": ["matches"],
}

_PRICE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"price": {"type": ["string", "null"]}},
    "required": ["price"],
}

_MATCHES_SYSTEM = (
    "Je krijgt de tekstinhoud van een webpagina met voetbalwedstrijd-tickets. "
    "Geef alle wedstrijden terug die ECHT op de pagina staan, met thuisclub, uitclub, "
    "de volledige ticket-URL (exact zoals in de tekst, absoluut), en de vanafprijs "
    "zoals getoond (bijvoorbeeld '249,-' of '€ 249'), of null als er geen prijs staat. "
    "Verzin niets: geen wedstrijden, prijzen of URL's die niet op de pagina staan. "
    "Kopieer URL's en prijzen letterlijk."
)

_PRICE_SYSTEM = (
    "Je krijgt de tekstinhoud van een ticketpagina van EEN wedstrijd. Geef de vanafprijs "
    "terug zoals op de pagina staat (bijvoorbeeld '249,-' of '€ 249'), of null als er geen "
    "prijs zichtbaar is. Verzin geen prijs."
)

_TONE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"tone_of_voice": {"type": "string"}},
    "required": ["tone_of_voice"],
}

_TONE_SYSTEM = (
    "Je krijgt de tekstinhoud van een webpagina van een merk. Beschrijf in 3 tot 5 korte "
    "bullets de tone of voice en schrijfstijl van dit merk: aanspreekvorm (je/u), register "
    "(formeel/informeel), energie, typische woorden of zinswendingen, en wat je juist vermijdt. "
    "Baseer je alleen op de tekst. Geef een bondige stijlgids terug die een tekstschrijver "
    "kan volgen, niet de paginatekst zelf."
)


def html_to_text(raw_html: str, base_url: str, max_chars: int = MAX_PAGE_CHARS) -> str:
    """Strip HTML naar leesbare tekst; links worden 'tekst (absolute-url)'."""
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw_html)

    def _anchor(match: re.Match) -> str:
        href = match.group(1)
        inner = html_lib.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
        return f" {inner} ({urljoin(base_url, href)}) "

    s = re.sub(r'(?is)<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', _anchor, s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_chars]


def _parse_json(response) -> dict:
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def normalize_price(value: str | None) -> str:
    if not value:
        return PRICE_ON_REQUEST
    digits = re.search(r"([0-9][0-9.,]*)", value)
    if not digits:
        return PRICE_ON_REQUEST
    amount = re.sub(r"[.,]-?$", "", digits.group(1)).rstrip(".,")
    return f"€ {amount}"


def fetch_page(url: str, client: httpx.Client | None = None, timeout: float = 20.0) -> tuple[int | None, str]:
    """Haal een pagina op. Geeft (status, html) terug; (None, '') bij netwerkfout."""
    try:
        if client is not None:
            resp = client.get(url)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                resp = c.get(url)
        return resp.status_code, resp.text
    except httpx.HTTPError:
        return None, ""


def extract_matches(llm, raw_html: str, *, source_url: str, model: str = EXTRACT_MODEL) -> list[dict]:
    """Laat het LLM de wedstrijden uit de pagina halen. Prijzen worden genormaliseerd."""
    text = html_to_text(raw_html, source_url)
    response = llm.messages.create(
        model=model,
        max_tokens=4000,
        system=_MATCHES_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _MATCHES_SCHEMA}},
        messages=[{"role": "user", "content": f"Bron-URL: {source_url}\n\nPagina-inhoud:\n{text}"}],
    )
    matches = _parse_json(response).get("matches", [])
    for m in matches:
        m["price"] = normalize_price(m.get("price"))
    return matches


_LINKS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"label": {"type": "string"}, "url": {"type": "string"}},
                "required": ["label", "url"],
            },
        }
    },
    "required": ["links"],
}

_LINKS_SYSTEM = (
    "Je krijgt de tekstinhoud van een ticket-website (links staan als 'tekst (url)'). "
    "Geef de ticket-links terug die passen bij de zoekopdracht: club-, competitie- of "
    "wedstrijdpagina's. Geef per link een label en de absolute URL, exact zoals in de tekst. "
    "Verzin geen labels of URL's; geef alleen links die echt op de pagina staan."
)


def extract_links(llm, raw_html: str, *, source_url: str, query: str, model: str = EXTRACT_MODEL) -> list[dict]:
    """Vind ticket-links (club/competitie/wedstrijd) op een pagina die bij de query passen."""
    text = html_to_text(raw_html, source_url)
    response = llm.messages.create(
        model=model,
        max_tokens=2000,
        system=_LINKS_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _LINKS_SCHEMA}},
        messages=[{"role": "user", "content": f"Zoekopdracht: {query}\n\nPagina-inhoud:\n{text}"}],
    )
    return _parse_json(response).get("links", [])


def extract_tone(llm, raw_html: str, *, source_url: str, model: str = EXTRACT_MODEL) -> str:
    """Leid de tone of voice / schrijfstijl van het merk af uit de paginatekst."""
    text = html_to_text(raw_html, source_url)
    response = llm.messages.create(
        model=model,
        max_tokens=600,
        system=_TONE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _TONE_SCHEMA}},
        messages=[{"role": "user", "content": f"Pagina-inhoud:\n{text}"}],
    )
    return _parse_json(response).get("tone_of_voice", "") or ""


def extract_price(llm, raw_html: str, *, source_url: str, model: str = EXTRACT_MODEL) -> str:
    """Lees de vanafprijs van een enkele wedstrijdpagina. Anders 'op aanvraag'."""
    text = html_to_text(raw_html, source_url)
    response = llm.messages.create(
        model=model,
        max_tokens=200,
        system=_PRICE_SYSTEM,
        output_config={"format": {"type": "json_schema", "schema": _PRICE_SCHEMA}},
        messages=[{"role": "user", "content": f"Pagina-inhoud:\n{text}"}],
    )
    return normalize_price(_parse_json(response).get("price"))
