"""Vanafprijs ophalen van een wedstrijdpagina.

Best-effort scraping: lukt het niet (pagina laadt niet, geen prijs herkenbaar),
dan valt het terug op de tekst "op aanvraag". Nooit een exception naar de
aanroeper; een ontbrekende prijs is geen fout maar een verwachte uitkomst.
"""

from __future__ import annotations

import re

import httpx

from app.newsletter.models import PRICE_ON_REQUEST

# Zoek bedragen vlak na "vanaf" / "v.a." / "from", bijv. "vanaf € 189" of "v.a. €189,-".
_PRICE_NEAR_KEYWORD = re.compile(
    r"(?:vanaf|v\.?a\.?|from)\s*€?\s*(\d{1,4}(?:[.,]\d{2})?)", re.IGNORECASE
)
# Losse euro-bedragen als tweede keus.
_EURO_AMOUNT = re.compile(r"€\s*(\d{1,4}(?:[.,]-|[.,]\d{2})?)")


def parse_price(text: str) -> str:
    """Haal de eerste herkenbare vanafprijs uit tekst. Anders 'op aanvraag'."""
    match = _PRICE_NEAR_KEYWORD.search(text) or _EURO_AMOUNT.search(text)
    if not match:
        return PRICE_ON_REQUEST
    amount = re.sub(r"[.,]-$", "", match.group(1))  # Nederlandse 299,- -> 299
    amount = amount.rstrip(".,")
    return f"€ {amount}"


def fetch_match_price(url: str, *, client: httpx.Client | None = None, timeout: float = 15.0) -> str:
    """Haal de wedstrijdpagina op en lees de vanafprijs. Faalt nooit hard."""
    try:
        if client is not None:
            response = client.get(url)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                response = c.get(url)
        if response.status_code != 200:
            return PRICE_ON_REQUEST
        return parse_price(response.text)
    except httpx.HTTPError:
        return PRICE_ON_REQUEST
