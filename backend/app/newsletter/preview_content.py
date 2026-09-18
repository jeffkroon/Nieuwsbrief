"""Een eerder gemaakte nieuwsbrief terugvertalen naar content, puur voor preview.

De opgeslagen `input` van een nieuwsbrief is precies wat de assistent destijds aan
`create_newsletter_draft` meegaf. Dat opnieuw door de draft-tool halen zou elke
link en prijs opnieuw live valideren; voor "laat deze template eens met echte
inhoud zien" is dat onnodig en traag.

Daarom deze pure vertaling zonder netwerk en zonder validatie. Uitsluitend voor de
preview: een echt concept loopt altijd via `create_newsletter_draft`, met alle
controles.
"""

from __future__ import annotations

from app.newsletter.models import (
    PRICE_ON_REQUEST,
    Club,
    Item,
    Match,
    NewsletterContent,
    Section,
)


def _tekst(raw: dict, key: str, fallback: str = "") -> str:
    waarde = raw.get(key)
    return waarde.strip() if isinstance(waarde, str) and waarde.strip() else fallback


def _lijst(raw: dict, key: str) -> list[dict]:
    waarde = raw.get(key)
    return [item for item in waarde if isinstance(item, dict)] if isinstance(waarde, list) else []


def content_from_draft_input(raw: dict, *, subject: str = "", theme: str = "") -> NewsletterContent:
    """Bouw preview-content uit de bewaarde draft-invoer; ontbrekende velden blijven leeg."""
    raw = raw or {}
    return NewsletterContent(
        theme=_tekst(raw, "theme", theme),
        subject=_tekst(raw, "subject", subject or "Voorbeeld"),
        intro_1=_tekst(raw, "intro_1"),
        intro_2=_tekst(raw, "intro_2"),
        main_cta_text=_tekst(raw, "main_cta_text", "Bekijk het aanbod"),
        main_cta_url=_tekst(raw, "main_cta_url", "https://example.com"),
        slot_cta_text=_tekst(raw, "slot_cta_text", "Meer informatie"),
        slot_cta_url=_tekst(raw, "slot_cta_url", "https://example.com"),
        matches=tuple(_match(item) for item in _lijst(raw, "matches")),
        clubs=tuple(_club(item) for item in _lijst(raw, "clubs")),
        items=tuple(_item(item) for item in _lijst(raw, "items")),
        sections=tuple(_section(item) for item in _lijst(raw, "sections")),
        custom_fields=tuple(
            (str(naam), str(tekst))
            for naam, tekst in (raw.get("custom_fields") or {}).items()
            if isinstance(raw.get("custom_fields"), dict)
        ),
        preview_text=_tekst(raw, "preview_text") or None,
        header_title=_tekst(raw, "header_title") or None,
        header_subtitle=_tekst(raw, "header_subtitle") or None,
        header_cta_text=_tekst(raw, "header_cta_text") or None,
        header_image_url=_tekst(raw, "header_image_url") or None,
        header_text_color=_tekst(raw, "header_text_color") or None,
    )


def _match(raw: dict) -> Match:
    return Match(
        home=_tekst(raw, "home", "Thuisploeg"),
        away=_tekst(raw, "away", "Uitploeg"),
        url=_tekst(raw, "url", "https://example.com"),
        price=_tekst(raw, "price", PRICE_ON_REQUEST),
        image_url=_tekst(raw, "image_url") or None,
        label=_tekst(raw, "label") or None,
    )


def _club(raw: dict) -> Club:
    return Club(
        name=_tekst(raw, "name", "Club"),
        url=_tekst(raw, "url", "https://example.com"),
        price=_tekst(raw, "price", PRICE_ON_REQUEST),
        image_url=_tekst(raw, "image_url") or None,
        stadium=_tekst(raw, "stadium") or None,
        city=_tekst(raw, "city") or None,
        label=_tekst(raw, "label") or None,
    )


def _item(raw: dict) -> Item:
    return Item(
        title=_tekst(raw, "title", "Item"),
        url=_tekst(raw, "url", "https://example.com"),
        subtitle=_tekst(raw, "subtitle") or None,
        price=_tekst(raw, "price") or None,
        image_url=_tekst(raw, "image_url") or None,
        label=_tekst(raw, "label") or None,
        button_text=_tekst(raw, "button_text", "Lees meer"),
    )


def _section(raw: dict) -> Section:
    return Section(
        kind=_tekst(raw, "kind", "text"),
        text=_tekst(raw, "text") or None,
        url=_tekst(raw, "url") or None,
        image_url=_tekst(raw, "image_url") or None,
        style=_tekst(raw, "style") or None,
    )
