"""Tools die de klantensite en de fotobibliotheek lezen (niets schrijven naar een ESP).

find_matches/find_products/find_ticket_links laten het LLM echte inhoud van de site
halen; de banner-tools meten foto's in code. Resultaten worden per gesprek
onthouden (tool_memory), zodat dezelfde pagina niet twee keer wordt uitgelezen.
"""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin, urlsplit

import httpx

from app.newsletter import banner_check, catalog, extraction
from app.newsletter.page_images import banner_candidates
from app.newsletter.tool_context import ToolContext, load_tenant, require_llm
from app.newsletter.tool_memory import with_memory
from app.repositories import images as images_repo


def _tool_get_brand_config(ctx: ToolContext, _: dict) -> dict:
    return {"config": load_tenant(ctx).config}


def _tool_list_images(ctx: ToolContext, tool_input: dict) -> dict:
    # Zonder categorie alles: dan hoeft de assistent niet te gokken welke
    # categorienamen dit bedrijf toevallig gebruikt.
    category = (tool_input.get("category") or "").strip().lower() or None
    images = images_repo.list_images(ctx.session, ctx.tenant_id, category)
    return {
        "category": category or "alle",
        "categories": sorted({im.category for im in images}),
        "images": [
            {"filename": im.filename, "description": im.description, "url": im.url} for im in images
        ],
    }


def _tool_analyze_website_tone(ctx: ToolContext, tool_input: dict) -> dict:
    brand = load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("website_url") or brand.get("matches_url")
    if not url:
        raise ValueError("geen website-URL om de tone of voice te analyseren")
    status, html = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(extraction.fetch_probleem(url, status))
    return {"source_url": url, "tone_of_voice": extraction.extract_tone(require_llm(ctx), html, source_url=url)}


def _tool_find_ticket_links(ctx: ToolContext, tool_input: dict) -> dict:
    brand = load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("matches_url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om ticket-links te zoeken")
    query = tool_input["query"]

    def _haal_op() -> dict:
        status, html = extraction.fetch_page(url, ctx.http_client)
        if status != 200:
            raise ValueError(extraction.fetch_probleem(url, status))
        links = extraction.extract_links(require_llm(ctx), html, source_url=url, query=query)
        return {"source_url": url, "count": len(links), "links": links}

    return with_memory(
        ctx.session, ctx.conversation_id, "find_ticket_links", {"url": url, "query": query}, _haal_op
    )


def _catalog_of(ctx: ToolContext, url: str) -> dict:
    """De hele catalogus achter deze URL (Shopify exact, anders alle pagina's)."""
    shop = catalog.shopify_catalog(url, ctx.http_client)
    if shop is None:
        status, html = extraction.fetch_page(url, ctx.http_client)
        if status != 200:
            raise ValueError(extraction.fetch_probleem(url, status))
        shop = catalog.paged_catalog(
            url, html,
            fetch=lambda u: extraction.fetch_page(u, ctx.http_client),
            extract=lambda h, u: extraction.extract_products(require_llm(ctx), h, source_url=u),
        )
    return {
        "source_url": url,
        "products": list(shop.products),
        "total": shop.total,
        "complete": shop.complete,
        "catalog_source": shop.source,
        "pages_read": shop.pages_read,
    }


def _products_message(result: dict, query: str | None, count: int, shown: int) -> str:
    totaal = result["total"]
    if result["complete"]:
        dekking = f"Dit is de VOLLEDIGE catalogus van deze pagina ({totaal} producten)."
    else:
        dekking = (
            f"LET OP: niet volledig gelezen ({result['pages_read']} pagina's, {totaal} "
            "producten gezien). Zeg dus NOOIT dat er niet meer producten zijn; zoek gerichter "
            "met query of op een specifiekere collectiepagina."
        )
    if query and count == 0:
        return (
            f"{dekking} Geen producten gevonden voor {query!r}. Probeer een ruimere zoekterm "
            "(bv. één woord) voordat je concludeert dat het er niet is."
        )
    extra = f" Getoond: de eerste {shown} van {count}; gebruik query om te filteren." if shown < count else ""
    return (
        f"{dekking}{extra} Toon de producten en laat de gebruiker KIEZEN. Gebruik url, prijs en "
        "image_url exact zoals hier teruggegeven; verzin niets."
    )


def _tool_find_products(ctx: ToolContext, tool_input: dict) -> dict:
    """Producten (naam, prijs, foto, URL) van een collectie-/overzichtspagina: ALLE pagina's."""
    brand = load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om producten te zoeken; geef een collectie-URL mee")
    query = (tool_input.get("query") or "").strip() or None

    # De catalogus wordt per URL onthouden; zoeken daarbinnen kost dan niets extra.
    volledig = with_memory(
        ctx.session, ctx.conversation_id, "find_products", {"url": url},
        lambda: _catalog_of(ctx, url),
    )
    gevonden = catalog.filter_products(volledig["products"], query)
    getoond = gevonden[: catalog.MAX_RETURNED]
    result = {
        "source_url": url,
        "query": query,
        "total_in_catalog": volledig["total"],
        "complete": volledig["complete"],
        "count": len(gevonden),
        "products": getoond,
        "message": _products_message(volledig, query, len(gevonden), len(getoond)),
    }
    if volledig.get("from_memory"):
        result["from_memory"] = True
    return result


def _require_image(ctx: ToolContext, url: str) -> None:
    """Garandeer dat de URL een bereikbare afbeelding is (200 + image/*)."""
    try:
        if ctx.http_client is not None:
            resp = ctx.http_client.get(url, headers=extraction.SITE_HEADERS)
        else:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(url, headers=extraction.SITE_HEADERS)
    except httpx.HTTPError as exc:
        raise ValueError(f"banner-URL is onbereikbaar: {url} ({exc})") from exc
    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not content_type.startswith("image/"):
        raise ValueError(
            f"banner-URL is geen bereikbare afbeelding: {url} "
            f"(status {resp.status_code}, type {content_type or 'onbekend'})"
        )


# Bij een pagina zonder eigen banner: hoeveel gelinkte collectiepagina's we maximaal
# nalopen, en hoeveel banner-kandidaten we teruggeven aan de gebruiker.
_BANNER_SCAN_LIMIT = 8
_BANNER_CANDIDATES_LIMIT = 5


def _banner_or_none(ctx: ToolContext, page_url: str, crop: str) -> str | None:
    """De gecheckte banner van één pagina, of None (nooit een exception)."""
    status, html = extraction.fetch_page(page_url, ctx.http_client)
    if status != 200:
        return None
    og_image = extraction.extract_og_image(html)
    if not og_image:
        return None
    banner = extraction.normalize_banner_url(og_image, crop=crop)
    for candidate in (banner, og_image):
        try:
            _require_image(ctx, candidate)
            return candidate
        except ValueError:
            continue
    return None


def _collection_banner_candidates(
    ctx: ToolContext, source_url: str, html: str, crop: str
) -> list[dict]:
    """Banners van collectiepagina's die op deze pagina gelinkt staan.

    Deterministisch (geen LLM): volg de /collections/-links van de pagina zelf en
    geef alleen banners terug die echt bestaan en bereikbaar zijn.
    """
    links: list[str] = []
    for m in re.finditer(r'href="([^"]+)"', html):
        link = urljoin(source_url, html_lib.unescape(m.group(1))).split("#")[0].split("?")[0]
        path = urlsplit(link).path
        if "/collections/" not in path or path.rstrip("/").endswith("/all"):
            continue
        if link != source_url.split("?")[0] and link not in links:
            links.append(link)
    candidates: list[dict] = []
    for link in links[:_BANNER_SCAN_LIMIT]:
        banner = _banner_or_none(ctx, link, crop)
        if banner:
            slug = urlsplit(link).path.rstrip("/").rsplit("/", 1)[-1]
            candidates.append(
                {"name": slug.replace("-", " "), "page_url": link, "banner_url": banner}
            )
        if len(candidates) >= _BANNER_CANDIDATES_LIMIT:
            break
    return candidates


# Hoeveel kandidaten per aanroep een beschrijving krijgen (één Haiku-call per foto).
_DESCRIBE_LIMIT = 6


def _page_banner_candidates(
    ctx: ToolContext, url: str, html: str, *, exclude: tuple = (), limit: int = 6
) -> list[dict]:
    """Foto's van de pagina zelf die als banner kunnen: gemeten, egaal beeld eruit,
    en met een beschrijving van wat erop staat (zodat 'zilver' geen gouden foto krijgt)."""
    uitgesloten = set(exclude)
    resultaat: list[dict] = []
    for beeld in banner_candidates(html, url, client=ctx.http_client, limit=limit + len(exclude) + 2):
        if beeld.url in uitgesloten or banner_check.looks_blank(beeld.url, ctx.http_client):
            continue
        kandidaat = {
            "name": beeld.label(),
            "page_url": url,
            "banner_url": beeld.url,
            "width": beeld.width,
            "height": beeld.height,
            "source": beeld.source,
        }
        if beeld.cropped:
            kandidaat["bijgesneden"] = (
                "vierkante/staande foto, door de webshop liggend bijgesneden uit het midden; "
                "vallen er hoofden of het onderwerp weg, gebruik dan banner_url_bovenkant"
            )
            kandidaat["banner_url_bovenkant"] = beeld.url.replace("crop=center", "crop=top")
        if len(resultaat) < _DESCRIBE_LIMIT:
            beschrijving = banner_check.describe(ctx.llm, beeld.url, ctx.http_client)
            if beschrijving:
                kandidaat["beschrijving"] = beschrijving
        resultaat.append(kandidaat)
        if len(resultaat) >= limit:
            break
    return resultaat


def _tool_find_page_images(ctx: ToolContext, tool_input: dict) -> dict:
    """Welke foto's staan er op deze pagina van de klantensite? Gemeten, zonder ruis."""
    brand = load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om foto's te zoeken; geef een pagina-URL mee")

    def _haal_op() -> dict:
        status, html = extraction.fetch_page(url, ctx.http_client)
        if status != 200:
            raise ValueError(extraction.fetch_probleem(url, status))
        banners = _page_banner_candidates(ctx, url, html, limit=8)
        if banners:
            bericht = (
                "Echte foto's van deze pagina (logo's, iconen, videoframes en egale beelden "
                "zijn er al uit; formaat is gemeten). 'beschrijving' zegt wat er echt op "
                "staat: kies alleen een foto die past bij het thema (zilver is geen goud). "
                "Toon de beste opties met die beschrijving en laat de gebruiker KIEZEN; een "
                "gekozen banner_url mag letterlijk als header_image_url."
            )
        else:
            # Geen LIGGEND beeld gevonden; dat is normaal bij een productpagina (die foto's
            # zijn vaak vierkant/staand). Zeg dat er eventueel toch een og:image bestaat, zodat
            # dit niet wordt gelezen als "geen foto beschikbaar" voor een product/item.
            og_image = extraction.extract_og_image(html)
            if og_image:
                bericht = (
                    f"Op {url} staat geen LIGGENDE foto van minimaal 600px (nodig voor een "
                    "banner). Er is wel een og:image op deze pagina; als dit een product- of "
                    "itempagina is, wordt die foto AUTOMATISCH gebruikt door "
                    "preview_newsletter/create_newsletter_draft. Roep dit hier niet opnieuw voor "
                    "op; controleer na preview_newsletter gewoon image_url in items_used."
                )
            else:
                bericht = f"Op {url} staat geen enkele bruikbare foto, ook geen og:image."
        return {
            "source_url": url,
            "count": len(banners),
            "images": banners,
            "message": bericht,
        }

    return with_memory(ctx.session, ctx.conversation_id, "find_page_images", {"url": url}, _haal_op)


def _tool_find_banner(ctx: ToolContext, tool_input: dict) -> dict:
    """Het eigen bannerbeeld (og:image) van een pagina van de klantensite ophalen.

    Genormaliseerd naar mail-formaat (Shopify-CDN: 1200 breed, standaard 1200x600
    center-crop; instelbaar per bedrijf via config "banner_crop") en in code
    gecheckt: de URL moet een bereikbare afbeelding zijn, anders duidelijke fout.
    Heeft de pagina zelf geen banner, dan worden de banners van de gelinkte
    collectiepagina's als kandidaten teruggegeven.
    """
    brand = load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om een banner te zoeken; geef een pagina-URL mee")
    crop = brand.get("banner_crop") or "landscape"

    def _haal_op() -> dict:
        status, html = extraction.fetch_page(url, ctx.http_client)
        if status != 200:
            raise ValueError(extraction.fetch_probleem(url, status))
        og_image = extraction.extract_og_image(html)
        if not og_image:
            candidates = _collection_banner_candidates(ctx, url, html, crop)
            # Geen og:image en geen collectiebanners: dan de foto's op de pagina zelf,
            # gemeten op formaat zodat alleen liggend beeld van bannerbreedte overblijft.
            candidates += _page_banner_candidates(ctx, url, html)
            if candidates:
                return {
                    "source_url": url,
                    "banner_url": None,
                    "candidates": candidates,
                    "message": "Deze pagina heeft geen eigen og:image-banner, maar er staat "
                    "wel bruikbaar beeld op de site. Toon de opties met naam en formaat en "
                    "laat de gebruiker KIEZEN; gebruik daarna de gekozen banner_url letterlijk.",
                }
            return {
                "source_url": url,
                "banner_url": None,
                "message": f"Op {url} staat geen enkele foto die als banner kan dienen "
                "(liggend, minimaal 600px breed). Probeer find_page_images op een andere "
                "pagina van de site, kies een foto uit list_images of vraag de gebruiker "
                "om er een te uploaden.",
            }
        banner = extraction.normalize_banner_url(og_image, crop=crop)
        try:
            _require_image(ctx, banner)
        except ValueError:
            if banner == og_image:
                raise
            # De bijgesneden variant werkt niet op deze CDN: val terug op het origineel,
            # dat moet dan wel zelf een bereikbare afbeelding zijn.
            _require_image(ctx, og_image)
            banner = og_image
        alternatieven = _page_banner_candidates(ctx, url, html, exclude=(og_image, banner), limit=4)
        if banner_check.looks_blank(banner, ctx.http_client):
            return {
                "source_url": url,
                "banner_url": None,
                "candidates": alternatieven,
                "message": "De eigen banner van deze pagina is (bijna) egaal, bv. een zwart "
                "videoframe, en valt daarom af. Kies uit 'candidates' of zoek met "
                "find_page_images op een andere pagina (homepage, collectie- of productpagina).",
            }
        return {
            "source_url": url,
            "banner_url": banner,
            "beschrijving": banner_check.describe(ctx.llm, banner, ctx.http_client),
            "alternatives": alternatieven,
            "message": "Echte banner van de site (bereikbaarheid gecheckt). 'beschrijving' "
            "zegt wat erop staat: past die niet bij het thema, kies dan een alternatief of "
            "zoek verder. Geef de gekozen volledige URL door als header_image_url nadat de "
            "gebruiker akkoord is; 'alternatives' zijn andere foto's van dezelfde pagina.",
        }

    return with_memory(
        ctx.session, ctx.conversation_id, "find_banner", {"url": url, "crop": crop}, _haal_op
    )


def _tool_find_matches(ctx: ToolContext, tool_input: dict) -> dict:
    brand = load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("matches_url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om wedstrijden te zoeken; zet 'matches_url' in de brand-config")

    def _haal_op() -> dict:
        status, html = extraction.fetch_page(url, ctx.http_client)
        if status != 200:
            raise ValueError(extraction.fetch_probleem(url, status))
        matches = extraction.extract_matches(require_llm(ctx), html, source_url=url)
        return {"source_url": url, "count": len(matches), "matches": matches}

    return with_memory(ctx.session, ctx.conversation_id, "find_matches", {"url": url}, _haal_op)


HANDLERS = {
    "get_brand_config": _tool_get_brand_config,
    "list_images": _tool_list_images,
    "analyze_website_tone": _tool_analyze_website_tone,
    "find_ticket_links": _tool_find_ticket_links,
    "find_products": _tool_find_products,
    "find_banner": _tool_find_banner,
    "find_page_images": _tool_find_page_images,
    "find_matches": _tool_find_matches,
}
