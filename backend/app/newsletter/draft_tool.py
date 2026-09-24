"""De concept-tool: nieuwsbrief als CONCEPT klaarzetten bij het verzendplatform.

Verstuurt nooit iets. Vereist expliciete toestemming (confirmed=true), valideert
alles opnieuw live, zet platform-tags om, voegt UTM's toe, inlinet CSS en blokkeert
bij harde mailfouten voordat de ESP wordt aangeroepen.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.newsletter.css_inlining import inline_css
from app.newsletter.esp_tags import localize_esp_tags
from app.newsletter.mail_checks import (
    advisory_messages,
    blocking_messages,
    check_newsletter,
)
from app.newsletter.newsletter_build import build_newsletter
from app.newsletter.tool_context import (
    ACTIVECAMPAIGN_SECRET_KIND,
    BREVO_SECRET_KIND,
    ESP_LABELS,
    KLAVIYO_SECRET_KIND,
    ToolContext,
    load_tenant,
    validation_cache,
)
from app.newsletter.utm import add_utm, utm_params
from app.repositories import newsletters as newsletters_repo
from app.repositories import secrets as secrets_repo
from app.services.activecampaign import ActiveCampaignError
from app.services.brevo import BrevoError
from app.services.klaviyo import KlaviyoError


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
    tenant = load_tenant(ctx)
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
        build_newsletter(ctx, tool_input)
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

    # De template is in Brevo-syntax geschreven; Klaviyo en ActiveCampaign kennen
    # een eigen afmeldlink-tag. Zonder deze omzetting komt de mail daar aan met een
    # kapotte afmeldlink, terwijl alle drie de platforms er een verplichten.
    gelokaliseerd = localize_esp_tags(html, esp)
    html = gelokaliseerd.html

    # UTM's op de eigen links, zodat de klant het resultaat kan meten. Staat uit
    # tot een bedrijf het instelt; externe links blijven altijd ongemoeid.
    parameters = utm_params(brand, campaign=content.theme)
    if parameters:
        html = add_utm(html, parameters, website_url=brand.get("website_url", ""))

    # CSS inline zetten zodat Outlook de opmaak ook toont. Per bedrijf uit te
    # zetten; bij twijfel gebruikt de inliner zelf de originele HTML.
    inline_notes: list[str] = []
    if brand.get("inline_css", True):
        ingelijnd = inline_css(html)
        html = ingelijnd.html
        if ingelijnd.note:
            inline_notes.append(ingelijnd.note)

    # Laatste controle voor het concept de deur uit gaat. Harde fouten (geen
    # afmeldlink, javascript-link, script-tag) blokkeren: die kosten de klant
    # anders een onbruikbare of niet-verzendbare campagne.
    bevindingen = check_newsletter(html, subject=content.subject, preheader=content.preview_text)
    blokkerend = blocking_messages(bevindingen)
    if blokkerend:
        raise ValueError(
            "De nieuwsbrief kan zo niet als concept worden klaargezet: "
            + " ".join(blokkerend)
        )

    try:
        draft = client.create_draft(
            name=_campaign_name(brand["brand_name"], content.theme),
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
        "esp_notes": [*gelokaliseerd.notes, *inline_notes],
        "aandachtspunten": advisory_messages(bevindingen),
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


HANDLERS = {"create_newsletter_draft": _tool_create_newsletter_draft}
