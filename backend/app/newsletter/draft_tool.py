"""De concept-tool: nieuwsbrief als CONCEPT klaarzetten bij het verzendplatform.

Verstuurt nooit iets. Vereist expliciete toestemming (confirmed=true), valideert
alles opnieuw live, zet platform-tags om, voegt UTM's toe, inlinet CSS en blokkeert
bij harde mailfouten voordat de ESP wordt aangeroepen.

Is er in dit gesprek al een concept gemaakt, dan wordt DAT concept bijgewerkt in
plaats van telkens een nieuw aan te maken (anders loopt het account van de klant
vol met halve concepten). Alleen zolang het in het platform nog een concept is;
anders, of op verzoek (new_draft=true), komt er een nieuw concept.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.models import Newsletter
from app.newsletter.css_inlining import inline_css
from app.newsletter.esp_tags import localize_esp_tags
from app.newsletter.mail_checks import (
    advisory_messages,
    blocking_messages,
    check_newsletter,
)
from app.newsletter.newsletter_build import build_newsletter
from app.newsletter.tool_context import ToolContext, load_tenant, validation_cache
from app.newsletter.utm import add_utm, utm_params
from app.repositories import newsletters as newsletters_repo
from app.services.esp import CampaignNotFound
from app.services.esp_connection import (
    ESP_ERRORS,
    EspConnection,
    EspFactories,
    belongs_to,
    campaign_ref,
    connect,
)


def _campaign_name(brand_name: str, theme: str, now: datetime | None = None) -> str:
    """Campagnenaam die nooit dubbel is.

    Voorheen "{merk} - {thema}": twee nieuwsbrieven over hetzelfde thema kregen dan
    exact dezelfde naam, en of Brevo/Klaviyo/ActiveCampaign dat weigeren staat nergens
    gedocumenteerd. In plaats van dat op een klantaccount uit te testen, maken we de
    naam uniek met datum en tijd (Europe/Amsterdam), zodat de vraag niet meer bestaat.
    Leesbaar in het dashboard van het platform: "Merk - Thema (24-09-2026 14:05)".
    """
    moment = (now or datetime.now(ZoneInfo("Europe/Amsterdam"))).strftime("%d-%m-%Y %H:%M")
    return f"{brand_name} - {theme} ({moment})"


@dataclass(frozen=True)
class _PreparedHtml:
    html: str
    notes: tuple[str, ...]
    findings: list


def _prepare_html(html: str, esp: str, brand: dict, content) -> _PreparedHtml:
    """Platform-tags, UTM's en inline CSS; blokkeert bij harde mailfouten."""
    # De template is in Brevo-syntax geschreven; Klaviyo en ActiveCampaign kennen
    # een eigen afmeldlink-tag. Zonder deze omzetting komt de mail daar aan met een
    # kapotte afmeldlink, terwijl alle drie de platforms er een verplichten.
    gelokaliseerd = localize_esp_tags(html, esp)
    html = gelokaliseerd.html
    notes = list(gelokaliseerd.notes)

    # UTM's op de eigen links, zodat de klant het resultaat kan meten. Staat uit
    # tot een bedrijf het instelt; externe links blijven altijd ongemoeid.
    parameters = utm_params(brand, campaign=content.theme)
    if parameters:
        html = add_utm(html, parameters, website_url=brand.get("website_url", ""))

    # CSS inline zetten zodat Outlook de opmaak ook toont. Per bedrijf uit te
    # zetten; bij twijfel gebruikt de inliner zelf de originele HTML.
    if brand.get("inline_css", True):
        ingelijnd = inline_css(html)
        html = ingelijnd.html
        if ingelijnd.note:
            notes.append(ingelijnd.note)

    # Laatste controle voor het concept de deur uit gaat. Harde fouten (geen
    # afmeldlink, javascript-link, script-tag) blokkeren: die kosten de klant
    # anders een onbruikbare of niet-verzendbare campagne.
    findings = check_newsletter(html, subject=content.subject, preheader=content.preview_text)
    blokkerend = blocking_messages(findings)
    if blokkerend:
        raise ValueError(
            "De nieuwsbrief kan zo niet als concept worden klaargezet: " + " ".join(blokkerend)
        )
    return _PreparedHtml(html=html, notes=tuple(notes), findings=findings)


def _try_update(
    conn: EspConnection, existing: Newsletter, brand: dict, content, html: str
) -> str | None:
    """Werk het bestaande concept bij. None = gelukt; anders de reden waarom niet."""
    try:
        conn.client.update_draft(
            campaign_ref(existing),
            subject=content.subject,
            sender_name=brand["brand_name"],
            sender_email=brand["brand_email"],
            html=html,
            preview_text=content.preview_text,
        )
        return None
    except CampaignNotFound:
        return f"Het vorige concept bestaat niet meer in {conn.label}"
    except ESP_ERRORS as exc:
        return f"Het vorige concept kon niet worden bijgewerkt ({exc}); het staat nog in {conn.label}"


def _create(ctx: ToolContext, conn: EspConnection, tenant, brand, content, html, tool_input):
    """Nieuw concept aanmaken en vastleggen; een platformfout wordt ook vastgelegd."""
    try:
        draft = conn.client.create_draft(
            name=_campaign_name(brand["brand_name"], content.theme),
            subject=content.subject,
            sender_name=brand["brand_name"],
            sender_email=brand["brand_email"],
            html=html,
            list_ids=conn.list_ids,
            preview_text=content.preview_text,
        )
    except ESP_ERRORS:
        newsletters_repo.create_newsletter(
            ctx.session, tenant_id=tenant.id, conversation_id=ctx.conversation_id,
            subject=content.subject, theme=content.theme, html=html, input=tool_input,
            status="failed",
        )
        raise
    use_text_ref = conn.esp != "brevo"  # string-ref voor Klaviyo en ActiveCampaign
    return newsletters_repo.create_newsletter(
        ctx.session,
        tenant_id=tenant.id,
        conversation_id=ctx.conversation_id,
        subject=content.subject,
        theme=content.theme,
        html=html,
        input=tool_input,
        brevo_campaign_id=None if use_text_ref else draft.campaign_id,
        esp_campaign_ref=str(draft.campaign_id) if use_text_ref else None,
        esp=conn.esp,
        status="ready",
    )


def _message(conn: EspConnection, *, updated: bool, fallback_reason: str | None,
             content, is_fallback: bool) -> str:
    if updated:
        tekst = (
            f"Bestaand concept bijgewerkt in {conn.label} (zelfde campagne, niets "
            f"verstuurd). Let op: wijzigingen die iemand in {conn.label} zelf aan dit "
            "concept had gedaan, zijn overschreven."
        )
    else:
        tekst = f"Concept aangemaakt in {conn.label}. Niets verstuurd; controleer en verstuur handmatig."
        if fallback_reason:
            tekst += f" {fallback_reason}; daarom is er een nieuw concept gemaakt."
        if conn.esp == "activecampaign" and content.preview_text:
            tekst += (
                " Let op: ActiveCampaign ondersteunt geen preheader via de API; de "
                "geschreven preheader staat niet in het concept."
            )
    if is_fallback:
        tekst += (
            " Let op: deze tenant heeft nog geen eigen template; het concept gebruikt "
            "de neutrale standaard. Maak een eigen template aan voor de juiste huisstijl."
        )
    return tekst


def _tool_create_newsletter_draft(ctx: ToolContext, tool_input: dict) -> dict:
    if not tool_input.get("confirmed"):
        raise ValueError(
            "Nog geen toestemming om het concept aan te maken. Vat de nieuwsbrief samen, "
            "vraag de gebruiker eerst om toestemming, en roep dit pas aan met confirmed=true."
        )
    # Harde garantie: het DEFINITIEVE concept valideert altijd live. De
    # validatie-cache is er voor preview-re-renders; hier legen we hem, zodat
    # prijzen/links in het concept nooit ouder zijn dan dit moment.
    validation_cache.clear()
    factories = EspFactories(ctx.brevo_factory, ctx.klaviyo_factory, ctx.activecampaign_factory)
    conn = connect(ctx.session, ctx.cipher, load_tenant(ctx), factories)

    tenant, brand, content, matches, clubs, items, html, _unfilled, is_fallback = (
        build_newsletter(ctx, tool_input)
    )
    prepared = _prepare_html(html, conn.esp, brand, content)

    existing = None
    if not tool_input.get("new_draft"):
        existing = newsletters_repo.find_open_draft(
            ctx.session, tenant_id=tenant.id, conversation_id=ctx.conversation_id
        )
        if existing is not None and not belongs_to(existing, conn.esp):
            existing = None
    fallback_reason = (
        _try_update(conn, existing, brand, content, prepared.html) if existing else None
    )
    updated = existing is not None and fallback_reason is None
    if updated:
        newsletter = newsletters_repo.update_newsletter(
            ctx.session, existing, subject=content.subject, theme=content.theme,
            html=prepared.html, input=tool_input,
        )
    else:
        newsletter = _create(ctx, conn, tenant, brand, content, prepared.html, tool_input)

    ref = campaign_ref(newsletter)
    return {
        "newsletter_id": str(newsletter.id),
        "esp": conn.esp,
        "campaign_id": ref,
        "brevo_campaign_id": newsletter.brevo_campaign_id,
        "status": "ready",
        "updated_existing_draft": updated,
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
        "esp_notes": list(prepared.notes),
        "aandachtspunten": advisory_messages(prepared.findings),
        "message": _message(
            conn, updated=updated, fallback_reason=fallback_reason,
            content=content, is_fallback=is_fallback,
        ),
    }


HANDLERS = {"create_newsletter_draft": _tool_create_newsletter_draft}
