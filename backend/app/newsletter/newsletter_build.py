"""Nieuwsbrief opbouwen en renderen, gedeeld door de preview- en de concept-tool.

Kiest de template, legt stijl-overrides eroverheen, erft ontbrekende velden uit de
vorige preview van het gesprek, controleert blokken en knop-/bannerlinks live en
rendert. Pas na een gelukte render wordt de nieuwe stand van het gesprek bewaard.
preview_newsletter toont het resultaat alleen; er gaat niets naar een verzendplatform.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models import Conversation, Tenant
from app.newsletter.block_validation import (
    validated_clubs,
    validated_cta_link,
    validated_custom_fields,
    validated_header_image,
    validated_items,
    validated_matches,
    validated_sections,
)
from app.newsletter.capabilities import style_key_has_effect
from app.newsletter.custom_fields import find_custom_slots
from app.newsletter.mail_checks import (
    advisory_messages,
    blocking_messages,
    check_newsletter,
)
from app.newsletter.models import Club, Item, Match, NewsletterContent
from app.newsletter.renderer import render_newsletter
from app.newsletter.styles import (
    COLOR_KEYS,
    FONT_KEY,
    SPACING_KEYS,
    effective_styles,
    is_valid_hex_color,
    sanitize_styles,
)
from app.newsletter.templates import load_template
from app.newsletter.tool_context import (
    DEFAULT_TEMPLATE,
    FALLBACK_TEMPLATE_STYLES,
    ToolContext,
    load_tenant,
)
from app.repositories import templates as templates_repo


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
    fallback_styles = {**FALLBACK_TEMPLATE_STYLES, **(brand.get("styles") or {})}
    return (
        load_template(brand.get("template", DEFAULT_TEMPLATE)),
        {**brand, "styles": fallback_styles},
        True,
    )


# Keuzes die per aanroep gelden en nooit mogen meeliften naar een volgende render:
# de toestemming voor het concept, en de keuze voor een apart nieuw concept.
_NOT_INHERITED = frozenset({"confirmed", "new_draft"})


def _without_per_call(values: dict) -> dict:
    return {k: v for k, v in values.items() if k not in _NOT_INHERITED}


def _conversation(ctx: ToolContext) -> Conversation | None:
    if ctx.conversation_id is None:
        return None
    return ctx.session.get(Conversation, ctx.conversation_id)


def _merge_with_last_preview(ctx: ToolContext, tool_input: dict) -> dict:
    """Vul ontbrekende velden aan uit de vorige preview van dit gesprek (puur, slaat niets op).

    Garantie in code: "wijzig één ding en render opnieuw" kan nooit meer velden
    kwijtraken (bv. de bannerfoto) doordat de agent ze vergeet te herhalen.
    Expliciet meegegeven waarden winnen altijd (ook een lege lijst = leegmaken);
    `confirmed` en `new_draft` (zie _NOT_INHERITED) worden nooit geërfd.
    """
    conversation = _conversation(ctx)
    previous = _without_per_call(conversation.last_preview or {}) if conversation else {}
    return {**previous, **tool_input}


def _remember_preview(ctx: ToolContext, merged_input: dict) -> None:
    """Sla de samengevoegde invoer op als nieuwe stand van het gesprek.

    Pas aanroepen NA een gelukte validatie en render: een mislukte poging laat
    de vorige stand zo ongemoeid. De invoer blijft ruw (ongeëscapet), zodat
    erven en opnieuw renderen nooit dubbel escapet.
    """
    conversation = _conversation(ctx)
    if conversation is None:
        return
    conversation.last_preview = merged_input
    ctx.session.commit()


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


@dataclass(frozen=True)
class BuiltNewsletter:
    """Uitkomst van build_newsletter.

    `input` is de samengevoegde RUWE invoer (vorige preview + deze aanroep, zonder
    `confirmed`/`new_draft`): precies wat er gerenderd is, dus ook wat een concept
    moet bewaren. is_fallback=True betekent dat de neutrale ingebouwde template is
    gebruikt.
    """

    tenant: Tenant
    brand: dict
    content: NewsletterContent
    matches: tuple[Match, ...]
    clubs: tuple[Club, ...]
    items: tuple[Item, ...]
    html: str
    unfilled: tuple[str, ...]
    is_fallback: bool
    input: dict


def _header_text_color(tool_input: dict) -> str | None:
    kleur = (tool_input.get("header_text_color") or "").strip() or None
    if kleur and not is_valid_hex_color(kleur):
        raise ValueError(
            f"header_text_color moet een hex-kleur zijn (bv. '#ffffff'), niet {kleur!r}"
        )
    return kleur


def _validated_content(ctx: ToolContext, tool_input: dict) -> NewsletterContent:
    """Valideer alle blokken en links live en bouw de (ruwe) content."""
    matches = validated_matches(ctx, tool_input.get("matches", []))
    clubs = validated_clubs(ctx, tool_input.get("clubs", []))
    items = validated_items(ctx, tool_input.get("items", []))
    sections = validated_sections(ctx, tool_input.get("sections", []))
    custom_fields = validated_custom_fields(tool_input.get("custom_fields"))
    return NewsletterContent(
        theme=tool_input["theme"],
        subject=tool_input["subject"],
        header_title=tool_input.get("header_title"),
        header_subtitle=tool_input.get("header_subtitle"),
        header_cta_text=tool_input.get("header_cta_text"),
        header_image_url=validated_header_image(ctx, tool_input.get("header_image_url")),
        header_text_color=_header_text_color(tool_input),
        intro_1=tool_input["intro_1"],
        intro_2=tool_input["intro_2"],
        main_cta_text=tool_input["main_cta_text"],
        main_cta_url=validated_cta_link(ctx, tool_input["main_cta_url"], veld="main_cta_url"),
        slot_cta_text=tool_input["slot_cta_text"],
        slot_cta_url=validated_cta_link(ctx, tool_input["slot_cta_url"], veld="slot_cta_url"),
        preview_text=tool_input.get("preview_text"),
        matches=tuple(matches),
        clubs=tuple(clubs),
        items=tuple(items),
        sections=tuple(sections),
        custom_fields=tuple(sorted(custom_fields.items())),
    )


def build_newsletter(ctx: ToolContext, tool_input: dict) -> BuiltNewsletter:
    """Valideer wedstrijden/clubs/items/links, bouw de content, kies de template en render.

    Gedeeld door preview_newsletter (geen Brevo) en create_newsletter_draft (wel Brevo).
    Volgorde is een garantie: eerst puur samenvoegen met de vorige preview, dan
    valideren en renderen, en pas na succes de nieuwe stand van het gesprek opslaan.
    """
    merged = _without_per_call(_merge_with_last_preview(ctx, tool_input))
    tenant = load_tenant(ctx)
    content = _validated_content(ctx, merged)
    template_html, brand, is_fallback = _resolve_template_html(ctx, tenant, tenant.config)
    brand = _apply_style_overrides(brand, template_html, merged.get("style_overrides"))
    html = render_newsletter(template_html, brand, content)
    filled = dict(content.custom_fields)
    unfilled = tuple(
        naam for naam in find_custom_slots(template_html) if not (filled.get(naam) or "").strip()
    )
    _remember_preview(ctx, merged)
    return BuiltNewsletter(
        tenant=tenant, brand=brand, content=content, matches=content.matches,
        clubs=content.clubs, items=content.items, html=html, unfilled=unfilled,
        is_fallback=is_fallback, input=merged,
    )


def _tool_preview_newsletter(ctx: ToolContext, tool_input: dict) -> dict:
    built = build_newsletter(ctx, tool_input)
    content, html, unfilled = built.content, built.html, built.unfilled
    matches, clubs, items = built.matches, built.clubs, built.items
    ctx.preview_holder.append(html)  # frontend toont dit in het voorbeeldpaneel
    result_extra = {}
    if built.is_fallback:
        result_extra["let_op_geen_eigen_template"] = (
            "Deze tenant heeft nog geen eigen template; er is een neutrale standaard "
            "gebruikt. Maak via de Bedrijven-tab een eigen template aan voor de juiste "
            "huisstijl."
        )
    if unfilled:
        result_extra["invulvakken_nog_leeg"] = list(unfilled)
        result_extra["invulvakken_hint"] = (
            "Deze template heeft eigen invulvakken die nog leeg zijn; die secties zijn uit "
            "de preview weggelaten. Schrijf zelf passende merkcopy voor de tekstvakken "
            "(tone of voice, zoals de intro's), maar vul vakken die echte feiten vereisen "
            "(personen, projecten, prijzen, quotes, foto-URL's) alleen met informatie van "
            "de gebruiker; vraag ernaar of laat ze bewust leeg."
        )
    bevindingen = check_newsletter(
        html, subject=content.subject, preheader=content.preview_text
    )
    aandachtspunten = blocking_messages(bevindingen) + advisory_messages(bevindingen)
    if aandachtspunten:
        result_extra["aandachtspunten"] = aandachtspunten

    return {
        **result_extra,
        "status": "preview",
        "subject": content.subject,
        "matches_used": [
            {"home": m.home, "away": m.away, "url": m.url, "price": m.price, "image_url": m.image_url}
            for m in matches
        ],
        "clubs_used": [
            {"name": c.name, "url": c.url, "price": c.price, "image_url": c.image_url} for c in clubs
        ],
        "items_used": [
            {"title": i.title, "url": i.url, "price": i.price, "image_url": i.image_url} for i in items
        ],
        "message": "Voorbeeld gerenderd en getoond in het paneel naast de chat. Kijk in "
        "*_used naar image_url om te zien welke foto per blok echt is gebruikt (null = geen "
        "foto gevonden, dan valt het blok terug op de neutrale afbeelding); dat is de "
        "waarheid, niet wat find_page_images/find_banner apart teruggeeft (die zoeken alleen "
        "LIGGEND beeld voor een banner, productfoto's zijn vaak vierkant of staand en tellen "
        "daar dus niet in mee). Vat kort samen en vraag de gebruiker om toestemming voordat "
        "je create_newsletter_draft (confirmed=true) aanroept.",
    }


HANDLERS = {"preview_newsletter": _tool_preview_newsletter}
