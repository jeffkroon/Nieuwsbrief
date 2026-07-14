"""Tool-laag voor de Claude-orchestratie.

Definieert de tools die Claude tijdens een gesprek mag aanroepen, plus de
dispatcher die ze uitvoert tegen de database, de site-extractie en Brevo. Alle
neveneffecten (DB-writes, Brevo-call) gebeuren hier, niet in het taalmodel.

Site-agnostisch: `find_matches` laat het LLM de echte wedstrijden + prijzen + URL's
van de klantensite halen. `create_newsletter_draft` valideert elke URL hard
(moet bestaan) en scrapet de prijs live van die pagina, zodat link en prijs altijd
echt zijn, ongeacht hoe de site is opgebouwd.
"""

from __future__ import annotations

import copy
import html as html_lib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy.orm import Session

from app.db.models import Conversation, Tenant
from app.newsletter import extraction
from app.newsletter.models import (
    PRICE_ON_REQUEST,
    Club,
    Item,
    Match,
    NewsletterContent,
    Section,
)
from app.newsletter.capabilities import style_key_has_effect
from app.newsletter.custom_fields import find_custom_slots, normalize_custom_fields
from app.newsletter.renderer import render_newsletter
from app.newsletter.styles import (
    COLOR_KEYS,
    EMAIL_SAFE_FONTS,
    FONT_KEY,
    SPACING_KEYS,
    effective_styles,
    is_valid_hex_color,
    sanitize_styles,
)
from app.newsletter.templates import load_template
from app.newsletter.validation_cache import ValidationCache
from app.repositories import images as images_repo
from app.repositories import newsletters as newsletters_repo
from app.repositories import secrets as secrets_repo
from app.repositories import templates as templates_repo
from app.services.activecampaign import ActiveCampaignClient, ActiveCampaignError
from app.services.brevo import BrevoClient, BrevoError
from app.services.crypto import SecretCipher
from app.services.klaviyo import KlaviyoClient, KlaviyoError

# Neutrale, merk-gekleurde fallback voor tenants zonder eigen template (geen
# voetbal-styling meer). De klant-specifieke voetbal-template blijft bestaan en
# wordt gebruikt zodra een tenant hem als eigen/standaard template heeft of via
# config["template"] expliciet kiest.
DEFAULT_TEMPLATE = "neutraal-basis"
# De oorspronkelijke paddings van de oude fallback-template (zie de tokens in het
# html-bestand); als basis-stijl meegegeven zodat een render die deze tokens wél
# gebruikt identiek blijft. De neutrale template gebruikt ze niet (onschadelijk).
_FALLBACK_TEMPLATE_STYLES = {
    "spacing_banner_intro": 20,
    "spacing_text_button": 16,
    "spacing_intro_products": 4,
    "spacing_products_text": 0,
}
BREVO_SECRET_KIND = "brevo_api_key"
KLAVIYO_SECRET_KIND = "klaviyo_api_key"
ACTIVECAMPAIGN_SECRET_KIND = "activecampaign_api_key"
ESP_LABELS = {"brevo": "Brevo", "klaviyo": "Klaviyo", "activecampaign": "ActiveCampaign"}


@dataclass(frozen=True)
class ToolContext:
    session: Session
    tenant_id: uuid.UUID
    cipher: SecretCipher
    llm: object | None = None  # Anthropic-client voor site-extractie
    conversation_id: uuid.UUID | None = None
    brevo_factory: Callable[[str], BrevoClient] = BrevoClient
    klaviyo_factory: Callable[[str], KlaviyoClient] = KlaviyoClient
    activecampaign_factory: Callable[[str, str], ActiveCampaignClient] = ActiveCampaignClient
    http_client: httpx.Client | None = None
    template_id: uuid.UUID | None = None  # gekozen template in de chat; None = standaard
    # Voorbeeld-HTML wordt hierin gezet door preview_newsletter, zodat de chat-laag het
    # aan de frontend kan teruggeven (apart van het tekstantwoord van de assistent).
    preview_holder: list[str] = field(default_factory=list)


TOOL_DEFINITIONS = [
    {
        "name": "get_brand_config",
        "description": "Haal de merk-configuratie (kleuren, afzender, socials, claude_prompt, "
        "matches_url) van de huidige tenant op. Roep dit altijd eerst aan.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyze_website_tone",
        "description": "Analyseer de tone of voice en schrijfstijl van de klantensite, zodat je "
        "de teksten in dezelfde stijl schrijft. Optioneel een specifieke URL; anders de "
        "website_url uit de brand-config. Roep dit aan voor je teksten schrijft.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optionele pagina-URL om de stijl van te lezen"}
            },
        },
    },
    {
        "name": "list_images",
        "description": "Lijst de geüploade foto's van deze tenant per categorie (bv. 'banner', "
        "'club', 'wedstrijd') met bestandsnaam, omschrijving en url. Gebruik dit om een bannerfoto "
        "te kiezen en per wedstrijd de juiste clubfoto te matchen op bestandsnaam/omschrijving "
        "(bv. een Arsenal-wedstrijd -> een arsenal-foto).",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string", "description": "bv. banner, club, wedstrijd"}},
            "required": ["category"],
        },
    },
    {
        "name": "find_matches",
        "description": "Haal de ECHTE, beschikbare wedstrijden van de klantensite op, met "
        "thuisclub, uitclub, de echte ticket-URL en de vanafprijs. Gebruik UITSLUITEND "
        "wedstrijden uit deze lijst. Optioneel een specifieke listing-URL meegeven; anders "
        "wordt de matches_url uit de brand-config gebruikt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optionele listing-/competitiepagina-URL"}
            },
        },
    },
    {
        "name": "find_ticket_links",
        "description": "Zoek bereikbare pagina's op de klantensite die passen bij een zoekopdracht: "
        "club-, competitie- of wedstrijdpagina's, maar ook cases, blogposts, producten, acties of "
        "andere inhoud. Gebruik dit altijd om een geldige, echte link te vinden voor een blok. "
        "Optioneel een specifieke pagina-URL om in te zoeken (bv. de bron-URL van de nieuwsbrief-soort).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Bijvoorbeeld een clubnaam, competitie, of het soort inhoud ('recente blogposts', 'cases')"},
                "url": {"type": "string", "description": "Optionele pagina-URL om in te zoeken"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_products",
        "description": "Haal de producten van een collectie- of overzichtspagina van de "
        "klantensite: naam, prijs, productfoto en product-URL, alles exact zoals op de "
        "pagina. Gebruik dit voor product-nieuwsbrieven zodat de gebruiker uit ECHTE "
        "producten kiest; foto en prijs komen zo altijd van de site. Zonder url wordt de "
        "bron-URL van de nieuwsbrief-soort of de website gebruikt.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Collectie-/overzichtspagina om te scannen, bv. de source_url van de gekozen nieuwsbrief-soort"},
            },
        },
    },
    {
        "name": "find_banner",
        "description": "Haal het eigen bannerbeeld van een pagina van de klantensite "
        "(bv. de collectiepagina waar de nieuwsbrief over gaat). Het beeld wordt "
        "genormaliseerd naar mail-formaat en in code gecheckt op bereikbaarheid. "
        "Heeft de pagina zelf geen banner, dan krijg je de banners van de gelinkte "
        "collecties als 'candidates' terug: toon die en laat de gebruiker kiezen. "
        "Gebruik dit voor de headerfoto als er geen passende bannerfoto in "
        "list_images('banner') staat; laat de gebruiker het resultaat bevestigen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Pagina-URL om de banner van te pakken, bv. de collectie- of source_url van de gekozen nieuwsbrief-soort"},
            },
        },
    },
    {
        "name": "create_newsletter_draft",
        "description": "Render de nieuwsbrief en maak hem aan als CONCEPT bij het "
        "verzendplatform van dit bedrijf (Brevo of Klaviyo). Verstuurt niets. Gebruik "
        "alleen echte inhoud (find_matches/find_products/find_ticket_links); links en "
        "prijzen worden live gevalideerd.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "theme": {"type": "string"},
                "header_title": {"type": "string", "description": "Korte pakkende kop op de headerfoto"},
                "header_subtitle": {"type": "string", "description": "Korte ondertitel onder de kop"},
                "header_cta_text": {"type": "string", "description": "Tekst van de knop op de headerfoto, bv. 'Bekijk alle wedstrijden'. De link is automatisch gelijk aan main_cta_url."},
                "intro_1": {"type": "string"},
                "intro_2": {"type": "string"},
                "main_cta_text": {"type": "string"},
                "main_cta_url": {"type": "string"},
                "slot_cta_text": {"type": "string"},
                "slot_cta_url": {"type": "string"},
                "preview_text": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "Zet alleen op true NADAT de gebruiker expliciet toestemming heeft gegeven om het concept in Brevo aan te maken"},
                "header_image_url": {"type": "string", "description": "De bannerfoto: een BESTANDSNAAM uit list_images('banner') (bv. 'allianz-arena.jpg'), of de volledige banner_url die find_banner teruggaf. Nooit een zelf verzonnen URL."},
                "header_text_color": {"type": "string", "description": "Optioneel: hex-kleur voor de kop en ondertitel op de bannerfoto, bv. '#ffffff'. Alleen meegeven als de gebruiker om een andere kleur vraagt; standaard geldt de kopkleur uit de stijl-builder."},
                "matches": {
                    "type": "array",
                    "description": "Wedstrijdblokken. Mag leeg zijn voor een ALGEMENE nieuwsbrief "
                    "(zonder losse wedstrijden); zorg dan dat de knoppen naar een bereikbare "
                    "algemene/competitie-/clubpagina verwijzen.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "home": {"type": "string"},
                            "away": {"type": "string"},
                            "url": {"type": "string", "description": "Bereikbare ticket-URL (uit find_matches of find_ticket_links)"},
                            "price": {"type": "string", "description": "Handmatige vanafprijs. Zonder price_override alleen de terugval als de site geen prijs heeft; met price_override=true wint deze prijs van de site."},
                            "price_override": {"type": "boolean", "description": "Zet ALLEEN op true als de gebruiker EXPLICIET een eigen prijs voor dit blok heeft opgegeven; dan wint 'price' van de site-prijs. Nooit op eigen initiatief gebruiken."},
                            "image_url": {"type": "string", "description": "BESTANDSNAAM van de gematchte foto uit list_images (niet de volledige URL)"},
                            "label": {"type": "string", "description": "Optioneel kort badge-label op de kaart, bv. 'NIEUW' of 'TOPPER'. Alleen zetten als de gebruiker erom vraagt of het duidelijk klopt."},
                        },
                        "required": ["home", "away", "url"],
                    },
                },
                "clubs": {
                    "type": "array",
                    "description": "Club-blokken (i.p.v. of naast wedstrijden): per club een naam en "
                    "een bereikbare clubpagina-URL (uit find_ticket_links). Optioneel price/image_url.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "url": {"type": "string", "description": "Bereikbare clubpagina-URL"},
                            "price": {"type": "string", "description": "Handmatige vanafprijs. Zonder price_override alleen de terugval als de site geen prijs heeft; met price_override=true wint deze prijs van de site."},
                            "price_override": {"type": "boolean", "description": "Zet ALLEEN op true als de gebruiker EXPLICIET een eigen prijs voor dit blok heeft opgegeven; dan wint 'price' van de site-prijs. Nooit op eigen initiatief gebruiken."},
                            "image_url": {"type": "string", "description": "BESTANDSNAAM van de clubfoto uit list_images (niet de volledige URL)"},
                            "stadium": {"type": "string", "description": "Naam van het stadion (klein lettertype in het blok)"},
                            "city": {"type": "string", "description": "Naam van de stad (klein lettertype in het blok)"},
                            "label": {"type": "string", "description": "Optioneel kort badge-label op de kaart, bv. 'VROEGBOEKKORTING' of 'NIEUW'. Alleen zetten als de gebruiker erom vraagt of het duidelijk klopt."},
                        },
                        "required": ["name", "url"],
                    },
                },
                "items": {
                    "type": "array",
                    "description": "Generieke inhoudsblokken voor niet-voetbal nieuwsbrieven "
                    "(cases, blogposts, producten, acties, vacatures). Per item een titel, "
                    "korte subtitel en een BEREIKBARE pagina-URL (uit find_ticket_links).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "subtitle": {"type": "string", "description": "Korte ondertitel (klein lettertype in het blok)"},
                            "url": {"type": "string", "description": "Bereikbare pagina-URL (uit find_ticket_links)"},
                            "button_text": {"type": "string", "description": "Knoptekst van dit blok, bv. 'Lees de case' of 'SHOP NU'. Gebruik de knoptekst van de nieuwsbrief-soort."},
                            "price": {"type": "string", "description": "Optionele prijs (bv. uit find_products). Wordt zonder price_override live her-gecheckt op de pagina (site wint). Weglaten = geen prijs tonen."},
                            "price_override": {"type": "boolean", "description": "Zet ALLEEN op true als de gebruiker EXPLICIET een eigen prijs voor dit blok heeft opgegeven; dan wint 'price' van de site-prijs. Nooit op eigen initiatief gebruiken."},
                            "image_url": {"type": "string", "description": "Foto: de image_url uit find_products (volledige URL) of een BESTANDSNAAM uit list_images. Weglaten = automatisch de productfoto (og:image) van de pagina."},
                            "label": {"type": "string", "description": "Optioneel kort badge-label, bv. 'NIEUW'"},
                        },
                        "required": ["title", "url"],
                    },
                },
                "custom_fields": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "Template-eigen invulvakken: sommige templates hebben vrije "
                    "tekstvakken ({{VAK_*}}). De preview-uitvoer meldt welke vakken de gekozen "
                    "template heeft. Vul per vak de tekst, sleutel = vaknaam (bv. 'ARTIKEL_TITEL'). "
                    "COPY SCHRIJF JE ZELF, FEITEN NOOIT: merk-/marketingteksten (artikelen, "
                    "kolommen, Q&A over het assortiment, banners) schrijf je zelf in de tone of "
                    "voice en passend bij het thema, precies zoals de intro's. Maar vakken die "
                    "echte feiten vereisen (namen van personen, interviews, projecten, prijzen, "
                    "quotes, datums, foto-URL's) vul je ALLEEN met informatie die de gebruiker gaf "
                    "of die je met tools hebt opgehaald; ontbreekt die, laat het vak dan leeg of "
                    "vraag ernaar. Vakken die je leeg laat zijn veilig: een ##SECTIE##-blok zonder "
                    "inhoud wordt automatisch uit de mail weggelaten (een los vak buiten zo'n blok "
                    "wordt een lege tekst).",
                },
                "sections": {
                    "type": "array",
                    "description": "OPTIONELE opbouw voor templates met de "
                    "<!-- ##SECTIES## --> marker: de secties worden in deze volgorde "
                    "gerenderd (de opzet die je met de gebruiker hebt besproken). "
                    "Weglaten = de vaste opzet van de template.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["hero", "text", "blocks", "button"],
                                     "description": "hero = klikbare foto; text = alinea; blocks = de gekozen wedstrijden/clubs/items; button = losse knop"},
                            "text": {"type": "string", "description": "Tekst (voor text en button)"},
                            "url": {"type": "string", "description": "Bereikbare link (voor hero en button)"},
                            "image_url": {"type": "string", "description": "Hero-foto: BESTANDSNAAM uit list_images of volledige URL"},
                            "style": {"type": "string", "enum": ["cards", "banners"],
                                      "description": "Voor blocks: cards (naast elkaar) of banners (onder elkaar)"},
                        },
                        "required": ["kind"],
                    },
                },
            },
            "required": [
                "subject",
                "theme",
                "intro_1",
                "intro_2",
                "main_cta_text",
                "main_cta_url",
                "slot_cta_text",
                "slot_cta_url",
            ],
        },
    },
]


# Validatie-cache: identieke live-checks (prijs, bereikbaarheid, og-foto) binnen
# 10 minuten niet herhalen. Nieuwe/gewijzigde blokken raken andere sleutels en
# worden dus gewoon gevalideerd; garanties blijven in code.
_validation_cache = ValidationCache()


def _load_tenant(ctx: ToolContext) -> Tenant:
    tenant = ctx.session.get(Tenant, ctx.tenant_id)
    if tenant is None:
        raise ValueError(f"tenant {ctx.tenant_id} bestaat niet")
    return tenant


def _require_llm(ctx: ToolContext):
    if ctx.llm is None:
        raise ValueError("geen LLM beschikbaar voor site-extractie")
    return ctx.llm


def _tool_get_brand_config(ctx: ToolContext, _: dict) -> dict:
    return {"config": _load_tenant(ctx).config}


def _tool_list_images(ctx: ToolContext, tool_input: dict) -> dict:
    category = tool_input["category"].strip().lower()
    images = images_repo.list_images(ctx.session, ctx.tenant_id, category)
    return {
        "category": category,
        "images": [
            {"filename": im.filename, "description": im.description, "url": im.url} for im in images
        ],
    }


def _tool_analyze_website_tone(ctx: ToolContext, tool_input: dict) -> dict:
    brand = _load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("website_url") or brand.get("matches_url")
    if not url:
        raise ValueError("geen website-URL om de tone of voice te analyseren")
    status, html = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(f"kon {url} niet ophalen (status {status})")
    return {"source_url": url, "tone_of_voice": extraction.extract_tone(_require_llm(ctx), html, source_url=url)}


def _tool_find_ticket_links(ctx: ToolContext, tool_input: dict) -> dict:
    brand = _load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("matches_url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om ticket-links te zoeken")
    status, html = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(f"kon {url} niet ophalen (status {status})")
    links = extraction.extract_links(
        _require_llm(ctx), html, source_url=url, query=tool_input["query"]
    )
    return {"source_url": url, "count": len(links), "links": links}


def _tool_find_products(ctx: ToolContext, tool_input: dict) -> dict:
    """Producten (naam, prijs, foto, URL) van een collectie-/overzichtspagina halen."""
    brand = _load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om producten te zoeken; geef een collectie-URL mee")
    status, html = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(f"kon {url} niet ophalen (status {status})")
    products = extraction.extract_products(_require_llm(ctx), html, source_url=url)
    return {
        "source_url": url,
        "count": len(products),
        "products": products,
        "message": "Toon de producten en laat de gebruiker KIEZEN. Gebruik url, prijs en "
        "image_url exact zoals hier teruggegeven; verzin niets.",
    }


def _require_image(ctx: ToolContext, url: str) -> None:
    """Garandeer dat de URL een bereikbare afbeelding is (200 + image/*)."""
    try:
        if ctx.http_client is not None:
            resp = ctx.http_client.get(url)
        else:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(url)
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


def _tool_find_banner(ctx: ToolContext, tool_input: dict) -> dict:
    """Het eigen bannerbeeld (og:image) van een pagina van de klantensite ophalen.

    Genormaliseerd naar mail-formaat (Shopify-CDN: 1200 breed, standaard 1200x600
    center-crop; instelbaar per bedrijf via config "banner_crop") en in code
    gecheckt: de URL moet een bereikbare afbeelding zijn, anders duidelijke fout.
    Heeft de pagina zelf geen banner, dan worden de banners van de gelinkte
    collectiepagina's als kandidaten teruggegeven.
    """
    brand = _load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om een banner te zoeken; geef een pagina-URL mee")
    status, html = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(f"kon {url} niet ophalen (status {status})")
    crop = brand.get("banner_crop") or "landscape"
    og_image = extraction.extract_og_image(html)
    if not og_image:
        candidates = _collection_banner_candidates(ctx, url, html, crop)
        if candidates:
            return {
                "source_url": url,
                "banner_url": None,
                "candidates": candidates,
                "message": "Deze pagina heeft geen eigen bannerbeeld, maar deze "
                "collecties op de site wel. Toon de opties en laat de gebruiker "
                "KIEZEN; gebruik daarna de gekozen banner_url letterlijk.",
            }
        return {
            "source_url": url,
            "banner_url": None,
            "message": "Deze pagina heeft geen eigen bannerbeeld. Kies een foto uit "
            "list_images('banner') of vraag de gebruiker om er een te uploaden.",
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
    return {
        "source_url": url,
        "banner_url": banner,
        "message": "Echte banner van de site (bereikbaarheid gecheckt). Geef deze "
        "volledige URL door als header_image_url nadat de gebruiker akkoord is.",
    }


def _tool_find_matches(ctx: ToolContext, tool_input: dict) -> dict:
    brand = _load_tenant(ctx).config
    url = tool_input.get("url") or brand.get("matches_url") or brand.get("website_url")
    if not url:
        raise ValueError("geen URL om wedstrijden te zoeken; zet 'matches_url' in de brand-config")
    status, html = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(f"kon {url} niet ophalen (status {status})")
    matches = extraction.extract_matches(_require_llm(ctx), html, source_url=url)
    return {"source_url": url, "count": len(matches), "matches": matches}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _resolve_image(ctx: ToolContext, value: str | None) -> str | None:
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
    url = _resolve_image(ctx, explicit)
    if url:
        return url
    for name in fallback_names:
        url = _resolve_image(ctx, name)
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
    hit, cached = _validation_cache.get(price_key)
    if hit:
        price = cached
    else:
        status, html = extraction.fetch_page(url, ctx.http_client)
        if status != 200:
            raise ValueError(
                f"URL bestaat niet of is onbereikbaar: {url} (status {status}). "
                "Gebruik find_matches of find_ticket_links voor een geldige link."
            )
        _validation_cache.set(("ok", url), True)
        if vanaf:
            # Clubpagina met meerdere wedstrijden: 'vanaf' = de laagste prijs (in code).
            price = extraction.extract_min_price(llm, html, source_url=url)
        else:
            price = extraction.extract_price(llm, html, source_url=url)
        _validation_cache.set(price_key, price)
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


def _validated_matches(ctx: ToolContext, raw_matches: list[dict]) -> list[Match]:
    if not raw_matches:
        return []
    llm = _require_llm(ctx)
    return [
        Match(
            home=m["home"], away=m["away"], url=m["url"], label=m.get("label"),
            **_priced_block(ctx, llm, m, m["home"], m["away"]),
        )
        for m in raw_matches
    ]


def _validated_items(ctx: ToolContext, raw_items: list[dict]) -> list[Item]:
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
                        f"URL bestaat niet of is onbereikbaar: {url} (status {status}). "
                        "Gebruik find_products of find_ticket_links voor een geldige link."
                    )
                _validation_cache.set(("ok", url), True)
                page_html = fetched
            return page_html

        reachable_hit, _ = _validation_cache.get(("ok", url))
        if not reachable_hit:
            _page()

        price = it.get("price")
        if price and it.get("price_override"):
            price = extraction.normalize_price(price)
        elif price:
            hit, cached = _validation_cache.get(("price", url))
            if hit:
                scraped = cached
            else:
                scraped = extraction.extract_price(_require_llm(ctx), _page(), source_url=url)
                _validation_cache.set(("price", url), scraped)
            price = scraped if scraped != PRICE_ON_REQUEST else extraction.normalize_price(price)

        image_url = _resolve_image_for(ctx, it.get("image_url"), it["title"])
        if not image_url:
            hit, cached = _validation_cache.get(("og", url))
            if hit:
                image_url = cached
            else:
                image_url = extraction.extract_og_image(_page())
                _validation_cache.set(("og", url), image_url)

        items.append(
            Item(
                title=it["title"], url=it["url"], subtitle=it.get("subtitle"),
                price=price, label=it.get("label"), image_url=image_url,
                button_text=it.get("button_text") or "Lees meer",
            )
        )
    return items


def _require_reachable(ctx: ToolContext, url: str) -> None:
    hit, _ok = _validation_cache.get(("ok", url))
    if hit:
        return
    status, _ = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(f"URL bestaat niet of is onbereikbaar: {url} (status {status}).")
    _validation_cache.set(("ok", url), True)


def _validated_sections(ctx: ToolContext, raw_sections: list[dict]) -> list[Section]:
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


def _validated_custom_fields(raw) -> dict[str, str]:
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


def _validated_clubs(ctx: ToolContext, raw_clubs: list[dict]) -> list[Club]:
    if not raw_clubs:
        return []
    llm = _require_llm(ctx)
    return [
        Club(
            name=c["name"], url=c["url"],
            stadium=c.get("stadium"), city=c.get("city"), label=c.get("label"),
            **_priced_block(ctx, llm, c, c["name"], vanaf=True),
        )
        for c in raw_clubs
    ]


def _resolve_template_html(
    ctx: ToolContext, tenant, brand: dict
) -> tuple[str, dict, bool]:
    """Kies de template-HTML: gekozen (ctx.template_id) > standaard > ingebouwd bestand.

    Geeft de HTML terug, een brand-dict waarin de stijl van de template is gezet,
    en of de ingebouwde (neutrale) fallback is gebruikt (True = tenant heeft nog
    geen eigen template).
    """
    chosen_tpl = None
    if ctx.template_id is not None:
        candidate = templates_repo.get_template(ctx.session, ctx.template_id)
        if candidate is not None and candidate.tenant_id == tenant.id:
            chosen_tpl = candidate
    if chosen_tpl is None:
        chosen_tpl = templates_repo.get_default_template(ctx.session, tenant.id)
    if chosen_tpl is not None:
        return chosen_tpl.html, {**brand, "styles": chosen_tpl.styles or {}}, False
    # Ingebouwde fallback: de witruimte-tokens staan in het bestand met deze
    # oorspronkelijke waarden als basis; zonder deze styles zouden de globale
    # defaults (80px) de layout ineens veranderen.
    fallback_styles = {**_FALLBACK_TEMPLATE_STYLES, **(brand.get("styles") or {})}
    return (
        load_template(brand.get("template", DEFAULT_TEMPLATE)),
        {**brand, "styles": fallback_styles},
        True,
    )


def _inherit_last_preview(ctx: ToolContext, tool_input: dict) -> dict:
    """Erf ontbrekende velden uit de vorige preview van dit gesprek.

    Garantie in code: "wijzig één ding en render opnieuw" kan nooit meer velden
    kwijtraken (bv. de bannerfoto) doordat de agent ze vergeet te herhalen.
    Expliciet meegegeven waarden winnen altijd (ook een lege lijst = leegmaken);
    `confirmed` (de toestemming voor het echte concept) wordt nooit geërfd.
    """
    if ctx.conversation_id is None:
        return tool_input
    conversation = ctx.session.get(Conversation, ctx.conversation_id)
    if conversation is None:
        return tool_input
    previous = {k: v for k, v in (conversation.last_preview or {}).items() if k != "confirmed"}
    merged = {**previous, **tool_input}
    conversation.last_preview = {k: v for k, v in merged.items() if k != "confirmed"}
    ctx.session.commit()
    return merged


def _apply_style_overrides(brand: dict, template_html: str, raw: dict | None) -> dict:
    """Stijl voor alleen deze nieuwsbrief bovenop de template-basis leggen.

    Garanties in code: ongeldige waarden worden hard geweigerd (nooit stil iets
    anders renderen), witruimte alleen als de template de spacing-tokens heeft,
    en het wijzigen van de productknop-kleur pint de banner-/onderste knop op
    hun huidige kleur zodat alleen de gevraagde knopgroep verandert. De
    template zelf wordt nooit aangepast.
    """
    if not raw:
        return brand
    if not isinstance(raw, dict):
        raise ValueError("style_overrides moet een object met stijlsleutels zijn")
    bekend = {k: v for k, v in raw.items() if k in COLOR_KEYS or k in SPACING_KEYS or k == FONT_KEY}
    clean = sanitize_styles(bekend)
    rejected = sorted(set(raw) - set(clean))
    if rejected:
        raise ValueError(
            f"ongeldige stijl-overrides geweigerd: {', '.join(rejected)} "
            "(kleuren als hex zoals '#000000', witruimte 0-200, bekend lettertype)"
        )
    # Eerlijkheid per sleutel: elke gevraagde witruimte moet zijn eigen token in
    # de template hebben, anders zou de wijziging stil niets doen.
    ontbreekt = [
        k for k in clean
        if k in SPACING_KEYS and ("{{STYLE_" + k.upper() + "}}") not in template_html
    ]
    if ontbreekt:
        raise ValueError(
            f"deze template ondersteunt {', '.join(ontbreekt)} niet (het bijbehorende "
            "spacing-token ontbreekt in de layout). Meld dit eerlijk aan de gebruiker."
        )
    # Zelfde eerlijkheid voor kleuren/lettertype: een sleutel die in deze template
    # nergens effect heeft (geen token en niet gebruikt door de gegenereerde
    # blokken) wordt hard geweigerd in plaats van stil niets te doen.
    zonder_effect = [
        k for k in clean
        if k not in SPACING_KEYS and not style_key_has_effect(k, template_html)
    ]
    if zonder_effect:
        raise ValueError(
            f"deze template gebruikt {', '.join(zonder_effect)} nergens; die aanpassing "
            "zou stil niets doen. Meld dit eerlijk aan de gebruiker."
        )
    basis = dict(brand.get("styles") or {})
    if any(k in clean for k in ("button_bg", "button_text")):
        current = effective_styles(brand)
        for pin_key, base in (
            ("hero_button_bg", "button_bg"),
            ("hero_button_text", "button_text"),
            ("cta_button_bg", "button_bg"),
            ("cta_button_text", "button_text"),
        ):
            if base in clean and pin_key not in basis and pin_key not in clean:
                clean[pin_key] = current[pin_key]
    return {**brand, "styles": {**basis, **clean}}


def _build_newsletter(ctx: ToolContext, tool_input: dict):
    """Valideer wedstrijden/clubs/items, bouw de content, kies de template en render.

    Gedeeld door preview_newsletter (geen Brevo) en create_newsletter_draft (wel Brevo).
    Geeft (tenant, brand, content, matches, clubs, items, html, unfilled, is_fallback)
    terug; is_fallback=True betekent dat de neutrale ingebouwde template is gebruikt.
    """
    tool_input = _inherit_last_preview(ctx, tool_input)
    tenant = _load_tenant(ctx)
    brand = tenant.config
    matches = _validated_matches(ctx, tool_input.get("matches", []))
    clubs = _validated_clubs(ctx, tool_input.get("clubs", []))
    items = _validated_items(ctx, tool_input.get("items", []))
    sections = _validated_sections(ctx, tool_input.get("sections", []))
    header_text_color = (tool_input.get("header_text_color") or "").strip() or None
    if header_text_color and not is_valid_hex_color(header_text_color):
        raise ValueError(
            f"header_text_color moet een hex-kleur zijn (bv. '#ffffff'), "
            f"niet {header_text_color!r}"
        )
    custom_fields = _validated_custom_fields(tool_input.get("custom_fields"))
    content = NewsletterContent(
        theme=tool_input["theme"],
        subject=tool_input["subject"],
        header_title=tool_input.get("header_title"),
        header_subtitle=tool_input.get("header_subtitle"),
        header_cta_text=tool_input.get("header_cta_text"),
        header_image_url=_resolve_image(ctx, tool_input.get("header_image_url")),
        header_text_color=header_text_color,
        intro_1=tool_input["intro_1"],
        intro_2=tool_input["intro_2"],
        main_cta_text=tool_input["main_cta_text"],
        main_cta_url=tool_input["main_cta_url"],
        slot_cta_text=tool_input["slot_cta_text"],
        slot_cta_url=tool_input["slot_cta_url"],
        preview_text=tool_input.get("preview_text"),
        matches=tuple(matches),
        clubs=tuple(clubs),
        items=tuple(items),
        sections=tuple(sections),
        custom_fields=tuple(sorted(custom_fields.items())),
    )
    template_html, brand, is_fallback = _resolve_template_html(ctx, tenant, brand)
    brand = _apply_style_overrides(brand, template_html, tool_input.get("style_overrides"))
    html = render_newsletter(template_html, brand, content)
    slots = find_custom_slots(template_html)
    unfilled = [naam for naam in slots if not (custom_fields.get(naam) or '').strip()]
    return tenant, brand, content, matches, clubs, items, html, unfilled, is_fallback


def _tool_preview_newsletter(ctx: ToolContext, tool_input: dict) -> dict:
    _, _, content, matches, clubs, items, html, unfilled, is_fallback = _build_newsletter(
        ctx, tool_input
    )
    ctx.preview_holder.append(html)  # frontend toont dit in het voorbeeldpaneel
    result_extra = {}
    if is_fallback:
        result_extra["let_op_geen_eigen_template"] = (
            "Deze tenant heeft nog geen eigen template; er is een neutrale standaard "
            "gebruikt. Maak via de Bedrijven-tab een eigen template aan voor de juiste "
            "huisstijl."
        )
    if unfilled:
        result_extra["invulvakken_nog_leeg"] = unfilled
        result_extra["invulvakken_hint"] = (
            "Deze template heeft eigen invulvakken die nog leeg zijn; die secties zijn uit "
            "de preview weggelaten. Schrijf zelf passende merkcopy voor de tekstvakken "
            "(tone of voice, zoals de intro's), maar vul vakken die echte feiten vereisen "
            "(personen, projecten, prijzen, quotes, foto-URL's) alleen met informatie van "
            "de gebruiker; vraag ernaar of laat ze bewust leeg."
        )
    return {
        **result_extra,
        "status": "preview",
        "subject": content.subject,
        "matches_used": [{"home": m.home, "away": m.away, "url": m.url, "price": m.price} for m in matches],
        "clubs_used": [{"name": c.name, "url": c.url, "price": c.price} for c in clubs],
        "items_used": [{"title": i.title, "url": i.url, "price": i.price} for i in items],
        "message": "Voorbeeld gerenderd en getoond in het paneel naast de chat. Vat kort samen "
        "en vraag de gebruiker om toestemming voordat je create_newsletter_draft (confirmed=true) aanroept.",
    }


def _tool_create_newsletter_draft(ctx: ToolContext, tool_input: dict) -> dict:
    if not tool_input.get("confirmed"):
        raise ValueError(
            "Nog geen toestemming om het concept aan te maken. Vat de nieuwsbrief samen, "
            "vraag de gebruiker eerst om toestemming, en roep dit pas aan met confirmed=true."
        )
    # Harde garantie: het DEFINITIEVE concept valideert altijd live. De
    # validatie-cache is er voor preview-re-renders; hier legen we hem, zodat
    # prijzen/links in het concept nooit ouder zijn dan dit moment.
    _validation_cache.clear()
    tenant = _load_tenant(ctx)
    esp = (tenant.config or {}).get("esp", "brevo")
    esp_label = ESP_LABELS.get(esp, "Brevo")
    secret_kind = {
        "klaviyo": KLAVIYO_SECRET_KIND,
        "activecampaign": ACTIVECAMPAIGN_SECRET_KIND,
    }.get(esp, BREVO_SECRET_KIND)
    api_key = secrets_repo.get_tenant_secret(ctx.session, ctx.cipher, tenant.id, secret_kind)
    if not api_key:
        raise ValueError(
            f"geen {esp_label} API-key ingesteld voor deze tenant "
            "(zet die via de Bedrijven-tab of PUT /tenants/{id}/secrets)"
        )
    ac_api_url = ""
    if esp == "activecampaign":
        # Hard valideren VOOR de render: een kapotte URL mag geen dure
        # validatie-ronde kosten en moet een duidelijke fout geven.
        from app.services.activecampaign import validate_api_url

        try:
            ac_api_url = validate_api_url((tenant.config or {}).get("activecampaign_api_url") or "")
        except ValueError as exc:
            raise ValueError(
                f"{exc} Stel de API-URL in via de Bedrijven-tab > Verzendplatform."
            ) from exc

    tenant, brand, content, matches, clubs, items, html, _unfilled, is_fallback = (
        _build_newsletter(ctx, tool_input)
    )
    if esp == "klaviyo":
        client = ctx.klaviyo_factory(api_key)
        list_id = brand.get("klaviyo_list_id")
        list_ids = [list_id] if list_id else None
    elif esp == "activecampaign":
        client = ctx.activecampaign_factory(ac_api_url, api_key)
        list_id = brand.get("activecampaign_list_id")
        list_ids = [list_id] if list_id else None
    else:
        client = ctx.brevo_factory(api_key)
        list_ids = [tenant.brevo_list_id] if tenant.brevo_list_id else None

    try:
        draft = client.create_draft(
            name=f"{brand['brand_name']} - {content.theme}",
            subject=content.subject,
            sender_name=brand["brand_name"],
            sender_email=brand["brand_email"],
            html=html,
            list_ids=list_ids,
            preview_text=content.preview_text,
        )
    except (BrevoError, KlaviyoError, ActiveCampaignError):
        newsletters_repo.create_newsletter(
            ctx.session,
            tenant_id=tenant.id,
            conversation_id=ctx.conversation_id,
            subject=content.subject,
            theme=content.theme,
            html=html,
            input=tool_input,
            status="failed",
        )
        raise

    use_text_ref = esp != "brevo"  # string-ref voor Klaviyo en ActiveCampaign
    newsletter = newsletters_repo.create_newsletter(
        ctx.session,
        tenant_id=tenant.id,
        conversation_id=ctx.conversation_id,
        subject=content.subject,
        theme=content.theme,
        html=html,
        input=tool_input,
        brevo_campaign_id=None if use_text_ref else draft.campaign_id,
        esp_campaign_ref=str(draft.campaign_id) if use_text_ref else None,
        status="ready",
    )
    return {
        "newsletter_id": str(newsletter.id),
        "esp": esp,
        "campaign_id": draft.campaign_id,
        "brevo_campaign_id": None if use_text_ref else draft.campaign_id,
        "status": "ready",
        "matches_used": [{"home": m.home, "away": m.away, "url": m.url, "price": m.price} for m in matches],
        "clubs_used": [{"name": c.name, "url": c.url, "price": c.price} for c in clubs],
        "items_used": [{"title": i.title, "url": i.url, "price": i.price} for i in items],
        "message": f"Concept aangemaakt in {esp_label}. Niets verstuurd; controleer en verstuur handmatig."
        + (
            " Let op: ActiveCampaign ondersteunt geen preheader via de API; de "
            "geschreven preheader staat niet in het concept."
            if esp == "activecampaign" and content.preview_text else ""
        )
        + (
            " Let op: deze tenant heeft nog geen eigen template; het concept gebruikt "
            "de neutrale standaard. Maak een eigen template aan voor de juiste huisstijl."
            if is_fallback else ""
        ),
    }


_DISPATCH: dict[str, Callable[[ToolContext, dict], dict]] = {
    "get_brand_config": _tool_get_brand_config,
    "list_images": _tool_list_images,
    "analyze_website_tone": _tool_analyze_website_tone,
    "find_ticket_links": _tool_find_ticket_links,
    "find_products": _tool_find_products,
    "find_banner": _tool_find_banner,
    "find_matches": _tool_find_matches,
    "preview_newsletter": _tool_preview_newsletter,
    "create_newsletter_draft": _tool_create_newsletter_draft,
}


# preview_newsletter heeft exact dezelfde velden als create_newsletter_draft, maar
# zonder 'confirmed' (er gaat niets naar Brevo). We leiden de schema af zodat de twee
# nooit uit elkaar lopen.
_draft_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_newsletter_draft")
_preview_schema = copy.deepcopy(_draft_def["input_schema"])
_preview_schema["properties"].pop("confirmed", None)
TOOL_DEFINITIONS.append(
    {
        "name": "preview_newsletter",
        "description": "Render een VOORBEELD van de nieuwsbrief en toon het direct aan de "
        "gebruiker in het voorbeeldpaneel naast de chat. Maakt NIETS aan in Brevo. Roep dit "
        "ALTIJD eerst aan en laat de gebruiker het voorbeeld zien, voordat je toestemming "
        "vraagt voor create_newsletter_draft. Zelfde velden (zonder 'confirmed'); links en "
        "prijzen worden net zo live gevalideerd en gescrapet.",
        "input_schema": _preview_schema,
    }
)


_STYLE_KEY_UITLEG = {
    "button_bg": "achtergrondkleur van de knoppen op de product-/wedstrijdkaarten",
    "button_text": "tekstkleur op de kaart-knoppen",
    "hero_button_bg": "achtergrondkleur van de knop op de bannerfoto (volgt button_bg tot je 'm zet)",
    "hero_button_text": "tekstkleur op de bannerknop",
    "cta_button_bg": "achtergrondkleur van de grote knop onderaan (volgt button_bg tot je 'm zet)",
    "cta_button_text": "tekstkleur op de onderste knop",
    "accent": "accentkleur (o.a. banner-elementen en kaart-titels)",
    "heading_color": "kopkleur op de headerfoto",
    "text_color": "kleur van de introtekst",
    "link_color": "linkkleur in lopende tekst",
    "page_bg": "achtergrond van de hele e-mail",
    "footer_bg": "achtergrond van de footer-balk",
    "footer_text": "tekstkleur in de footer",
    "card_bg": "achtergrond van een kaart",
    "card_border": "randkleur van een kaart",
    "block_border": "randkleur van het wedstrijd-/productblok",
    "price_color": "kleur van prijsbedragen",
    "badge_bg": "achtergrond van badge-labels",
    "home_color": "thuisclubnaam in het wedstrijdblok",
    "away_color": "uitclubnaam in het wedstrijdblok",
}

# Stijl voor ALLEEN deze nieuwsbrief: de template blijft de vaste basis; deze
# overrides gaan alleen mee in de render van dit gesprek (en erven mee via
# last_preview). De template zelf pas je aan in de stijl-builder, niet via chat.
_STYLE_OVERRIDES_SCHEMA = {
    "type": "object",
    "description": (
        "Kleuren/lettertype/witruimte voor ALLEEN deze nieuwsbrief; de template "
        "blijft ongewijzigd als basis. Geef alleen de sleutels die moeten "
        "afwijken; hex-kleuren zoals '#000000'. Sleutels: "
        + "; ".join(f"{k} = {v}" for k, v in _STYLE_KEY_UITLEG.items())
        + "; font_family (mail-veilig lettertype); witruimte in px (0-200): "
        + ", ".join(SPACING_KEYS)
        + " (banner->intro, intro->producten, producten->tekst, tekst->onderste "
        "knop). Render daarna altijd opnieuw."
    ),
    "properties": {
        **{key: {"type": "string"} for key in COLOR_KEYS},
        FONT_KEY: {"type": "string", "enum": sorted(EMAIL_SAFE_FONTS)},
        **{key: {"type": "integer"} for key in SPACING_KEYS},
    },
}
_draft_def["input_schema"]["properties"]["style_overrides"] = _STYLE_OVERRIDES_SCHEMA
_preview_schema["properties"]["style_overrides"] = _STYLE_OVERRIDES_SCHEMA



def execute_tool(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    handler = _DISPATCH.get(name)
    if handler is None:
        raise ValueError(f"onbekende tool: {name}")
    return handler(ctx, tool_input)
