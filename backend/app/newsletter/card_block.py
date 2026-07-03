"""Template-eigen kaarten: herhaal de kaart-markup van de klant-template per blok.

Waar de ##CARDS##-marker kaarten in óns ontwerp rendert, laat het ##KAART##-blok
het ONTWERP VAN DE KLANT intact: de template bevat één voorbeeldkaart tussen
markers, en de code herhaalt die markup per wedstrijd/club/item en vult de
{{KAART_*}}-placeholders. Zo blijft klant-specifieke vormgeving data (de
template), nooit code.

Markers in de template-HTML:
- <!-- ##KAART## --> ... <!-- /##KAART## -->    : de markup van één kaart
- <!-- ##KAART_RIJ## --> ... <!-- /##KAART_RIJ## --> : (optioneel) de rij-wrapper
  eromheen; met rij-markers worden kaarten per twee in een kopie van de rij gezet.

Placeholders binnen de kaart: {{KAART_TITEL}}, {{KAART_SUBTITEL}}, {{KAART_PRIJS}},
{{KAART_URL}}, {{KAART_IMAGE_URL}}, {{KAART_KNOP_TEKST}}, {{KAART_LABEL}}.
Ongebruikte placeholders worden door de renderer gestript.
"""

from __future__ import annotations

from typing import Callable

from app.newsletter.models import PRICE_ON_REQUEST, NewsletterContent

CARD_ROW_START = "<!-- ##KAART_RIJ## -->"
CARD_ROW_END = "<!-- /##KAART_RIJ## -->"
CARD_TPL_START = "<!-- ##KAART## -->"
CARD_TPL_END = "<!-- /##KAART## -->"

CARDS_PER_ROW = 2

# Slot-token binnen de rij-template waar de gevulde kaarten van die rij komen.
_ROW_SLOT = "%%KAARTEN%%"

ImageFallback = Callable[[str, dict], str]


def has_card_block(html: str) -> bool:
    return CARD_TPL_START in (html or "") and CARD_TPL_END in (html or "")


def _display_price(price: str | None) -> str:
    if not price:
        return ""
    if price == PRICE_ON_REQUEST:
        return "op aanvraag"
    return price


def _card_units(
    content: NewsletterContent, brand: dict, image_fallback: ImageFallback
) -> list[dict]:
    """Vertaal wedstrijden/clubs/items naar generieke kaart-velden, in die volgorde."""
    units: list[dict] = []
    for m in content.matches:
        units.append(
            {
                "titel": m.home,
                "subtitel": f"vs {m.away}",
                "prijs": _display_price(m.price),
                "url": m.url,
                "image_url": m.image_url or image_fallback(m.home, brand),
                "knop_tekst": "Bestel tickets",
                "label": m.label or "",
            }
        )
    for c in content.clubs:
        units.append(
            {
                "titel": c.name,
                "subtitel": " · ".join(p for p in (c.stadium, c.city) if p),
                "prijs": _display_price(c.price),
                "url": c.url,
                "image_url": c.image_url or image_fallback(c.name, brand),
                "knop_tekst": "Bekijk alle wedstrijden",
                "label": c.label or "",
            }
        )
    for it in content.items:
        units.append(
            {
                "titel": it.title,
                "subtitel": it.subtitle or "",
                "prijs": _display_price(it.price),
                "url": it.url,
                "image_url": it.image_url or image_fallback(it.title, brand),
                "knop_tekst": it.button_text,
                "label": it.label or "",
            }
        )
    return units


def _fill_card(card_tpl: str, unit: dict) -> str:
    replacements = {
        "{{KAART_TITEL}}": unit["titel"],
        "{{KAART_SUBTITEL}}": unit["subtitel"],
        "{{KAART_PRIJS}}": unit["prijs"],
        "{{KAART_URL}}": unit["url"],
        "{{KAART_IMAGE_URL}}": unit["image_url"],
        "{{KAART_KNOP_TEKST}}": unit["knop_tekst"],
        "{{KAART_LABEL}}": unit["label"],
    }
    filled = card_tpl
    for placeholder, value in replacements.items():
        filled = filled.replace(placeholder, value)
    return filled


def _extract(html: str, start_marker: str, end_marker: str) -> tuple[int, int, str] | None:
    """Zoek een marker-blok; geef (start, einde-na-endmarker, binnenkant) of None."""
    start = html.find(start_marker)
    if start == -1:
        return None
    inner_start = start + len(start_marker)
    end = html.find(end_marker, inner_start)
    if end == -1:
        return None
    return start, end + len(end_marker), html[inner_start:end]


def render_template_cards(
    html: str,
    brand: dict,
    content: NewsletterContent,
    image_fallback: ImageFallback,
) -> str:
    """Vervang het ##KAART##-blok door de kaart-markup, herhaald per inhoudsblok.

    Zonder kaart-blok in de template komt de HTML ongewijzigd terug. Zonder
    inhoud wordt het hele blok (inclusief rij-wrapper) netjes verwijderd.
    """
    card_region = _extract(html, CARD_TPL_START, CARD_TPL_END)
    if card_region is None:
        return html
    card_start, card_end, card_tpl = card_region

    units = _card_units(content, brand, image_fallback)
    cards = [_fill_card(card_tpl, u) for u in units]

    row_region = _extract(html, CARD_ROW_START, CARD_ROW_END)
    if row_region is None or not (row_region[0] < card_start and card_end <= row_region[1]):
        # Geen (omsluitende) rij-wrapper: herhaal de kaarten op hun plek.
        return html[:card_start] + "".join(cards) + html[card_end:]

    row_start, row_end, row_tpl = row_region
    # De kaart-regio binnen de rij-template vervangen door een slot-token.
    slotted = _extract(row_tpl, CARD_TPL_START, CARD_TPL_END)
    if slotted is None:  # kan niet: de kaart lag binnen de rij
        return html
    row_shell = row_tpl[: slotted[0]] + _ROW_SLOT + row_tpl[slotted[1] :]

    rows = [
        row_shell.replace(_ROW_SLOT, "".join(cards[i : i + CARDS_PER_ROW]))
        for i in range(0, len(cards), CARDS_PER_ROW)
    ]
    return html[:row_start] + "".join(rows) + html[row_end:]
