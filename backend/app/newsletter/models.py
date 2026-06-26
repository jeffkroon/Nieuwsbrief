"""Onveranderlijke domeinmodellen voor nieuwsbrief-content.

Frozen dataclasses: eenmaal opgebouwd verandert content niet meer. De renderer
leest deze waarden en muteert ze nooit.
"""

from __future__ import annotations

from dataclasses import dataclass

PRICE_ON_REQUEST = "op aanvraag"


@dataclass(frozen=True)
class Match:
    """Eén wedstrijd-banner in de nieuwsbrief.

    `url` is de volledige, echte ticket-URL op de klantensite (niet zelf opgebouwd
    uit een slug): zo klopt de link altijd, ongeacht het URL-patroon van de site.
    """

    home: str
    away: str
    url: str
    price: str = PRICE_ON_REQUEST


@dataclass(frozen=True)
class NewsletterContent:
    """Volledige door de gebruiker/Claude bepaalde inhoud van een nieuwsbrief."""

    theme: str
    subject: str
    intro_1: str
    intro_2: str
    main_cta_text: str
    main_cta_url: str
    slot_cta_text: str
    slot_cta_url: str
    matches: tuple[Match, ...]
    preview_text: str | None = None
