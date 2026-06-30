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
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.db.models import Tenant
from app.newsletter import extraction
from app.newsletter.models import PRICE_ON_REQUEST, Club, Match, NewsletterContent
from app.newsletter.renderer import render_newsletter
from app.newsletter.templates import load_template
from app.repositories import images as images_repo
from app.repositories import newsletters as newsletters_repo
from app.repositories import secrets as secrets_repo
from app.repositories import templates as templates_repo
from app.services.brevo import BrevoClient, BrevoError
from app.services.crypto import SecretCipher

DEFAULT_TEMPLATE = "voetbalreizenxl-main"
BREVO_SECRET_KIND = "brevo_api_key"


@dataclass(frozen=True)
class ToolContext:
    session: Session
    tenant_id: uuid.UUID
    cipher: SecretCipher
    llm: object | None = None  # Anthropic-client voor site-extractie
    conversation_id: uuid.UUID | None = None
    brevo_factory: Callable[[str], BrevoClient] = BrevoClient
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
        "description": "Zoek bereikbare ticket-pagina's (club-, competitie- of wedstrijdpagina's) op "
        "de klantensite die passen bij een zoekopdracht. Gebruik dit om een geldige link te vinden "
        "voor een wedstrijd die nog niet als losse wedstrijd op de site staat (bijvoorbeeld de "
        "clubpagina). Optioneel een specifieke pagina-URL om in te zoeken.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Bijvoorbeeld een clubnaam of competitie"},
                "url": {"type": "string", "description": "Optionele pagina-URL om in te zoeken"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_newsletter_draft",
        "description": "Render de nieuwsbrief en maak hem aan als CONCEPT in Brevo. Verstuurt "
        "niets. Gebruik alleen wedstrijden (met hun echte url) uit find_matches. De link en "
        "prijs worden live van de site gevalideerd en gescrapet.",
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
                "header_image_url": {"type": "string", "description": "BESTANDSNAAM van de gekozen bannerfoto uit list_images('banner'), bv. 'allianz-arena.jpg'. Niet de volledige URL."},
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
                            "price": {"type": "string", "description": "Handmatige vanafprijs; ALLEEN gebruiken als de site geen prijs heeft en de gebruiker die heeft opgegeven"},
                            "image_url": {"type": "string", "description": "BESTANDSNAAM van de gematchte foto uit list_images (niet de volledige URL)"},
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
                            "price": {"type": "string", "description": "Handmatige vanafprijs als de site er geen heeft"},
                            "image_url": {"type": "string", "description": "BESTANDSNAAM van de clubfoto uit list_images (niet de volledige URL)"},
                            "stadium": {"type": "string", "description": "Naam van het stadion (klein lettertype in het blok)"},
                            "city": {"type": "string", "description": "Naam van de stad (klein lettertype in het blok)"},
                        },
                        "required": ["name", "url"],
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


def _resolve_price(ctx: ToolContext, llm, url: str, manual: str | None) -> str:
    """URL moet bereikbaar zijn (200). Scrape de prijs; val terug op handmatige prijs."""
    status, html = extraction.fetch_page(url, ctx.http_client)
    if status != 200:
        raise ValueError(
            f"URL bestaat niet of is onbereikbaar: {url} (status {status}). "
            "Gebruik find_matches of find_ticket_links voor een geldige link."
        )
    price = extraction.extract_price(llm, html, source_url=url)
    # Geen prijs op de site? Gebruik de handmatig opgegeven vanafprijs (echte prijs wint).
    if price == PRICE_ON_REQUEST and manual:
        price = extraction.normalize_price(manual)
    return price


def _validated_matches(ctx: ToolContext, raw_matches: list[dict]) -> list[Match]:
    if not raw_matches:
        return []
    llm = _require_llm(ctx)
    return [
        Match(
            home=m["home"], away=m["away"], url=m["url"],
            price=_resolve_price(ctx, llm, m["url"], m.get("price")),
            image_url=_resolve_image(ctx, m.get("image_url")),
        )
        for m in raw_matches
    ]


def _validated_clubs(ctx: ToolContext, raw_clubs: list[dict]) -> list[Club]:
    if not raw_clubs:
        return []
    llm = _require_llm(ctx)
    return [
        Club(
            name=c["name"], url=c["url"],
            price=_resolve_price(ctx, llm, c["url"], c.get("price")),
            image_url=_resolve_image(ctx, c.get("image_url")),
            stadium=c.get("stadium"), city=c.get("city"),
        )
        for c in raw_clubs
    ]


def _resolve_template_html(ctx: ToolContext, tenant, brand: dict) -> tuple[str, dict]:
    """Kies de template-HTML: gekozen (ctx.template_id) > standaard > ingebouwd bestand.

    Geeft de HTML terug plus een brand-dict waarin de stijl van de template is gezet.
    """
    chosen_tpl = None
    if ctx.template_id is not None:
        candidate = templates_repo.get_template(ctx.session, ctx.template_id)
        if candidate is not None and candidate.tenant_id == tenant.id:
            chosen_tpl = candidate
    if chosen_tpl is None:
        chosen_tpl = templates_repo.get_default_template(ctx.session, tenant.id)
    if chosen_tpl is not None:
        return chosen_tpl.html, {**brand, "styles": chosen_tpl.styles or {}}
    return load_template(brand.get("template", DEFAULT_TEMPLATE)), brand


def _build_newsletter(ctx: ToolContext, tool_input: dict):
    """Valideer wedstrijden/clubs, bouw de content, kies de template en render de HTML.

    Gedeeld door preview_newsletter (geen Brevo) en create_newsletter_draft (wel Brevo).
    Geeft (tenant, brand, content, matches, clubs, html) terug.
    """
    tenant = _load_tenant(ctx)
    brand = tenant.config
    matches = _validated_matches(ctx, tool_input.get("matches", []))
    clubs = _validated_clubs(ctx, tool_input.get("clubs", []))
    content = NewsletterContent(
        theme=tool_input["theme"],
        subject=tool_input["subject"],
        header_title=tool_input.get("header_title"),
        header_subtitle=tool_input.get("header_subtitle"),
        header_cta_text=tool_input.get("header_cta_text"),
        header_image_url=_resolve_image(ctx, tool_input.get("header_image_url")),
        intro_1=tool_input["intro_1"],
        intro_2=tool_input["intro_2"],
        main_cta_text=tool_input["main_cta_text"],
        main_cta_url=tool_input["main_cta_url"],
        slot_cta_text=tool_input["slot_cta_text"],
        slot_cta_url=tool_input["slot_cta_url"],
        preview_text=tool_input.get("preview_text"),
        matches=tuple(matches),
        clubs=tuple(clubs),
    )
    template_html, brand = _resolve_template_html(ctx, tenant, brand)
    html = render_newsletter(template_html, brand, content)
    return tenant, brand, content, matches, clubs, html


def _tool_preview_newsletter(ctx: ToolContext, tool_input: dict) -> dict:
    _, _, content, matches, clubs, html = _build_newsletter(ctx, tool_input)
    ctx.preview_holder.append(html)  # frontend toont dit in het voorbeeldpaneel
    return {
        "status": "preview",
        "subject": content.subject,
        "matches_used": [{"home": m.home, "away": m.away, "url": m.url, "price": m.price} for m in matches],
        "clubs_used": [{"name": c.name, "url": c.url, "price": c.price} for c in clubs],
        "message": "Voorbeeld gerenderd en getoond in het paneel naast de chat. Vat kort samen "
        "en vraag de gebruiker om toestemming voordat je create_newsletter_draft (confirmed=true) aanroept.",
    }


def _tool_create_newsletter_draft(ctx: ToolContext, tool_input: dict) -> dict:
    if not tool_input.get("confirmed"):
        raise ValueError(
            "Nog geen toestemming om het concept aan te maken. Vat de nieuwsbrief samen, "
            "vraag de gebruiker eerst om toestemming, en roep dit pas aan met confirmed=true."
        )
    tenant = _load_tenant(ctx)
    api_key = secrets_repo.get_tenant_secret(ctx.session, ctx.cipher, tenant.id, BREVO_SECRET_KIND)
    if not api_key:
        raise ValueError(
            "geen Brevo API-key ingesteld voor deze tenant (zet die via PUT /tenants/{id}/secrets)"
        )

    tenant, brand, content, matches, clubs, html = _build_newsletter(ctx, tool_input)
    list_ids = [tenant.brevo_list_id] if tenant.brevo_list_id else None

    client = ctx.brevo_factory(api_key)
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
    except BrevoError:
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

    newsletter = newsletters_repo.create_newsletter(
        ctx.session,
        tenant_id=tenant.id,
        conversation_id=ctx.conversation_id,
        subject=content.subject,
        theme=content.theme,
        html=html,
        input=tool_input,
        brevo_campaign_id=draft.campaign_id,
        status="ready",
    )
    return {
        "newsletter_id": str(newsletter.id),
        "brevo_campaign_id": draft.campaign_id,
        "status": "ready",
        "matches_used": [{"home": m.home, "away": m.away, "url": m.url, "price": m.price} for m in matches],
        "clubs_used": [{"name": c.name, "url": c.url, "price": c.price} for c in clubs],
        "message": "Concept aangemaakt in Brevo. Niets verstuurd; controleer en verstuur handmatig.",
    }


_DISPATCH: dict[str, Callable[[ToolContext, dict], dict]] = {
    "get_brand_config": _tool_get_brand_config,
    "list_images": _tool_list_images,
    "analyze_website_tone": _tool_analyze_website_tone,
    "find_ticket_links": _tool_find_ticket_links,
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


def execute_tool(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    handler = _DISPATCH.get(name)
    if handler is None:
        raise ValueError(f"onbekende tool: {name}")
    return handler(ctx, tool_input)
