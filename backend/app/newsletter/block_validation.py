"""Validatie van de blokken in een nieuwsbrief: links, live prijzen en foto's.

Garanties in code: elke URL moet bereikbaar zijn (200), de prijs komt live van de
site tenzij de gebruiker expliciet een eigen prijs gaf, en foto's komen uit de
bibliotheek of van de eigen pagina van het blok; nooit verzonnen.
"""

from __future__ import annotations

import re

from app.newsletter import extraction
from app.newsletter.custom_fields import normalize_custom_fields
from app.newsletter.models import PRICE_ON_REQUEST, Club, Item, Match, Section
from app.newsletter.page_images import best_product_image
from app.newsletter.tool_context import ToolContext, require_llm, validation_cache
from app.repositories import images as images_repo


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_image(ctx: ToolContext, value: str | None) -> str | None:
    """Zet een door de agent gekozen foto-verwijzing om naar de echte opslag-URL.

    Het model kan een bestandsnaam (of 'categorie:bestandsnaam') meegeven; wij zoeken
    de echte URL op in de geüploade foto's van deze tenant. Een volledige http-URL
    wordt overgenomen. Niets gevonden -> None (nette fallback in de renderer).
    """
    if not value:
        return None
    if value.startswith(("http://", "https://")):
        return value
    name = value.split(":")[-1].strip()
    images = images_repo.list_images(ctx.session, ctx.tenant_id)
    for im in images:  # exacte bestandsnaam
        if im.filename == name:
            return im.url
    needle = _norm(name)  # genormaliseerde 'bevat'-match op naam of omschrijving
    if needle:
        for im in images:
            if needle in _norm(im.filename) or needle in _norm(im.description or ""):
                return im.url
    return None


def _resolve_image_for(ctx: ToolContext, explicit: str | None, *fallback_names: str) -> str | None:
    """Resolve de foto via de expliciete verwijzing; lukt dat niet, probeer dan de
    club-/teamnaam (zo blijft de juiste foto staan, ook als de agent de bestandsnaam
    een keer weglaat of net iets anders schrijft)."""
    url = resolve_image(ctx, explicit)
    if url:
        return url
    for name in fallback_names:
        url = resolve_image(ctx, name)
        if url:
            return url
    return None


def _resolve_price(
    ctx: ToolContext, llm, url: str, manual: str | None, override: bool = False,
    vanaf: bool = False,
) -> str:
    """URL moet bereikbaar zijn (200). Standaard wint de live gescrapete site-prijs.

    Alleen als de gebruiker EXPLICIET een eigen prijs heeft opgegeven (override=True)
    wint de handmatige prijs van de site; de URL wordt dan nog steeds gevalideerd.
    Zonder override is de handmatige prijs enkel de terugval als de site er geen heeft.
    """
    price_key = ("min_price" if vanaf else "price", url)
    if override and manual:
        # Expliciete gebruikersprijs: alleen bereikbaarheid checken (gecacht).
        _require_reachable(ctx, url)
        return extraction.normalize_price(manual)
    hit, cached = validation_cache.get(price_key)
    if hit:
        price = cached
    else:
        status, html = extraction.fetch_page(url, ctx.http_client)
        if status != 200:
            raise ValueError(
                extraction.fetch_probleem(url, status) + " "
                "Gebruik find_matches of find_ticket_links voor een geldige link."
            )
        validation_cache.set(("ok", url), True)
        if vanaf:
            # Clubpagina met meerdere wedstrijden: 'vanaf' = de laagste prijs (in code).
            price = extraction.extract_min_price(llm, html, source_url=url)
        else:
            price = extraction.extract_price(llm, html, source_url=url)
        validation_cache.set(price_key, price)
    # Geen prijs op de site? Gebruik de handmatig opgegeven vanafprijs (echte prijs wint).
    if price == PRICE_ON_REQUEST and manual:
        price = extraction.normalize_price(manual)
    return price


def _priced_block(
    ctx: ToolContext, llm, raw: dict, *fallback_names: str, vanaf: bool = False
) -> dict:
    """Gedeelde validatie voor wedstrijd- en clubblokken: prijs + foto.

    Prijs: de URL moet bereikbaar zijn en de live site-prijs wint, tenzij de
    gebruiker expliciet price_override heeft gezet (zie _resolve_price). Voor
    club-blokken (vanaf=True) is de prijs de LAAGSTE wedstrijdprijs op de
    pagina. Foto: de expliciete verwijzing wint; anders de club-/teamnamen.
    """
    return {
        "price": _resolve_price(
            ctx, llm, raw["url"], raw.get("price"),
            override=bool(raw.get("price_override")), vanaf=vanaf,
        ),
        "image_url": _resolve_image_for(ctx, raw.get("image_url"), *fallback_names),
    }


def validated_matches(ctx: ToolContext, raw_matches: list[dict]) -> list[Match]:
    if not raw_matches:
        return []
    llm = require_llm(ctx)
    return [
        Match(
            home=m["home"], away=m["away"], url=m["url"], label=m.get("label"),
            **_priced_block(ctx, llm, m, m["home"], m["away"]),
        )
        for m in raw_matches
    ]


def validated_items(ctx: ToolContext, raw_items: list[dict]) -> list[Item]:
    """Generieke items (producten, cases, blogs): URL moet bereikbaar zijn (200).

    Prijs: geen prijs meegegeven = geen prijsregel. Prijs meegegeven zonder override =
    live her-scrapen van de pagina (de site wint; de meegegeven prijs is terugval).
    Prijs met price_override (expliciet verzoek gebruiker) = die prijs, genormaliseerd.
    Foto: expliciete verwijzing (bibliotheek of volledige URL) wint; anders de og:image
    van de productpagina zelf, zodat productfoto's nooit verzonnen worden.
    """
    items: list[Item] = []
    for it in raw_items:
        url = it["url"]
        page_html: str | None = None  # pas ophalen als een check hem echt nodig heeft

        def _page() -> str:
            nonlocal page_html
            if page_html is None:
                status, fetched = extraction.fetch_page(url, ctx.http_client)
                if status != 200:
                    raise ValueError(
                        extraction.fetch_probleem(url, status) + " "
                        "Gebruik find_products of find_ticket_links voor een geldige link."
                    )
                validation_cache.set(("ok", url), True)
                page_html = fetched
            return page_html

        reachable_hit, _ = validation_cache.get(("ok", url))
        if not reachable_hit:
            _page()

        price = it.get("price")
        if price and it.get("price_override"):
            price = extraction.normalize_price(price)
        elif price:
            hit, cached = validation_cache.get(("price", url))
            if hit:
                scraped = cached
            else:
                scraped = extraction.extract_price(require_llm(ctx), _page(), source_url=url)
                validation_cache.set(("price", url), scraped)
            price = scraped if scraped != PRICE_ON_REQUEST else extraction.normalize_price(price)

        image_url = _resolve_image_for(ctx, it.get("image_url"), it["title"])
        if not image_url:
            hit, cached = validation_cache.get(("og", url))
            if hit:
                image_url = cached
            else:
                # og:image is het betrouwbaarst; ontbreekt die, dan de grootste echte
                # foto op de productpagina zelf (gemeten, geen logo). Nog steeds
                # de eigen pagina van het product, dus niets verzonnen.
                image_url = extraction.extract_og_image(_page()) or best_product_image(
                    _page(), url, client=ctx.http_client
                )
                validation_cache.set(("og", url), image_url)

        items.append(
            Item(
                title=it["title"], url=it["url"], subtitle=it.get("subtitle"),
                price=price, label=it.get("label"), image_url=image_url,
                button_text=it.get("button_text") or "Lees meer",
            )
        )
    return items


def _require_reachable(ctx: ToolContext, url: str) -> None:
    hit, _ok = validation_cache.get(("ok", url))
    if hit:
        return
    status, _ = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(extraction.fetch_probleem(url, status))
    validation_cache.set(("ok", url), True)


def validated_sections(ctx: ToolContext, raw_sections: list[dict]) -> list[Section]:
    """Opzet-secties valideren: hero-foto moet vindbaar zijn, knop-/hero-links moeten
    echt bestaan (200). Garanties in code, niet in het model."""
    sections: list[Section] = []
    for s in raw_sections:
        kind = s.get("kind")
        if kind == "hero":
            image = _resolve_image_for(ctx, s.get("image_url"))
            if not image:
                raise ValueError(
                    "hero-sectie: geen vindbare foto. Gebruik een bestandsnaam uit "
                    "list_images of een volledige URL."
                )
            url = s.get("url")
            if url:
                _require_reachable(ctx, url)
            sections.append(Section(kind="hero", image_url=image, url=url))
        elif kind == "text":
            if not s.get("text"):
                raise ValueError("text-sectie zonder tekst")
            sections.append(Section(kind="text", text=s["text"]))
        elif kind == "button":
            if not (s.get("text") and s.get("url")):
                raise ValueError("button-sectie vereist zowel text als url")
            _require_reachable(ctx, s["url"])
            sections.append(Section(kind="button", text=s["text"], url=s["url"]))
        elif kind == "blocks":
            sections.append(Section(kind="blocks", style=s.get("style")))
        else:
            raise ValueError(f"onbekende sectie-soort: {kind!r}")
    return sections


def validated_custom_fields(raw) -> dict[str, str]:
    """Valideer de template-eigen invulvakken: plat object van tekst naar tekst."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("custom_fields moet een object zijn: {\"VAKNAAM\": \"tekst\"}")
    for key, value in raw.items():
        if not isinstance(value, (str, int, float)):
            raise ValueError(
                f"custom_fields[{key!r}] moet tekst zijn, geen {type(value).__name__}"
            )
    return normalize_custom_fields({k: str(v) for k, v in raw.items()})


def validated_clubs(ctx: ToolContext, raw_clubs: list[dict]) -> list[Club]:
    if not raw_clubs:
        return []
    llm = require_llm(ctx)
    return [
        Club(
            name=c["name"], url=c["url"],
            stadium=c.get("stadium"), city=c.get("city"), label=c.get("label"),
            **_priced_block(ctx, llm, c, c["name"], vanaf=True),
        )
        for c in raw_clubs
    ]
