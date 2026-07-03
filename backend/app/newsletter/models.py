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
    image_url: str | None = None  # gekozen clubfoto; valt anders terug op dummy
    label: str | None = None  # optioneel badge-label op de kaart, bv. "NIEUW"


@dataclass(frozen=True)
class Club:
    """Eén club-blok in de nieuwsbrief (link naar de clubpagina i.p.v. een wedstrijd)."""

    name: str
    url: str
    price: str = PRICE_ON_REQUEST
    image_url: str | None = None
    stadium: str | None = None
    city: str | None = None
    label: str | None = None  # optioneel badge-label op de kaart, bv. "VROEGBOEKKORTING"


@dataclass(frozen=True)
class Item:
    """Generiek inhoudsblok voor niet-voetbal nieuwsbrieven (case, blog, product, actie).

    Zelfde bouwstenen als Match/Club (titel, subtitel, foto, knop), maar zonder
    voetbal-aannames: prijs is optioneel en de knoptekst is per item instelbaar.
    """

    title: str
    url: str
    subtitle: str | None = None
    price: str | None = None  # None = geen prijs tonen (anders dan "op aanvraag")
    image_url: str | None = None
    label: str | None = None
    button_text: str = "Lees meer"


@dataclass(frozen=True)
class Section:
    """Eén bouwblok in een sectie-gebaseerde nieuwsbrief (opzet-composer).

    Soorten:
    - "hero": klikbare foto over de volle breedte (image_url, optioneel url)
    - "text": een alinea lopende tekst (text)
    - "blocks": de gekozen wedstrijden/clubs/items, als "cards" of "banners" (style)
    - "button": losse gecentreerde knop (text + url)
    """

    kind: str
    text: str | None = None
    url: str | None = None
    image_url: str | None = None
    style: str | None = None  # alleen voor blocks: "cards" (default) of "banners"


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
    clubs: tuple[Club, ...] = ()
    items: tuple[Item, ...] = ()  # generieke blokken (cases, blogs, producten, acties)
    # Opzet-composer: gevuld = de secties worden in deze volgorde gerenderd op de
    # ##SECTIES##-marker; leeg = de vaste placeholder-opzet van de template.
    sections: tuple[Section, ...] = ()
    preview_text: str | None = None
    header_title: str | None = None
    header_subtitle: str | None = None
    header_cta_text: str | None = None
    header_cta_url: str | None = None
    header_image_url: str | None = None  # gekozen bannerfoto; valt anders terug op brand
