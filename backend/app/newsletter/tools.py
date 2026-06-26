"""Tool-laag voor de Claude-orchestratie.

Definieert de tools die Claude tijdens een gesprek mag aanroepen, plus de
dispatcher die ze uitvoert tegen de database, de renderer en Brevo. Alle
neveneffecten (DB-writes, Brevo-call) gebeuren hier, niet in het taalmodel.

create_newsletter_draft combineert renderen en het aanmaken van het Brevo-concept
bewust in één tool: zo hoeft de 8 KB HTML nooit door het model heen.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.db.models import Tenant
from app.newsletter.models import Match, NewsletterContent
from app.newsletter.pricing import fetch_match_price
from app.newsletter.renderer import render_newsletter
from app.newsletter.templates import load_template
from app.repositories import newsletters as newsletters_repo
from app.repositories import secrets as secrets_repo
from app.services.brevo import BrevoClient, BrevoError
from app.services.crypto import SecretCipher

DEFAULT_TEMPLATE = "voetbalreizenxl-main"
BREVO_SECRET_KIND = "brevo_api_key"


@dataclass(frozen=True)
class ToolContext:
    session: Session
    tenant_id: uuid.UUID
    cipher: SecretCipher
    conversation_id: uuid.UUID | None = None
    brevo_factory: Callable[[str], BrevoClient] = BrevoClient
    http_client: httpx.Client | None = None


TOOL_DEFINITIONS = [
    {
        "name": "get_brand_config",
        "description": "Haal de merk-configuratie (kleuren, afzender, socials, claude_prompt) "
        "van de huidige tenant op. Roep dit altijd eerst aan.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fetch_match_price",
        "description": "Haal de vanafprijs van een wedstrijdpagina op. Geeft 'op aanvraag' "
        "terug als er geen prijs herkenbaar is.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Volledige wedstrijd-URL"}},
            "required": ["url"],
        },
    },
    {
        "name": "create_newsletter_draft",
        "description": "Render de nieuwsbrief en maak hem aan als CONCEPT in Brevo. "
        "Verstuurt niets. Roep dit als laatste aan met alle inhoud.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "theme": {"type": "string"},
                "intro_1": {"type": "string"},
                "intro_2": {"type": "string"},
                "main_cta_text": {"type": "string"},
                "main_cta_url": {"type": "string"},
                "slot_cta_text": {"type": "string"},
                "slot_cta_url": {"type": "string"},
                "preview_text": {"type": "string"},
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "home": {"type": "string"},
                            "away": {"type": "string"},
                            "slug": {"type": "string"},
                            "price": {"type": "string"},
                        },
                        "required": ["home", "away", "slug"],
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
                "matches",
            ],
        },
    },
]


def _load_tenant(ctx: ToolContext) -> Tenant:
    tenant = ctx.session.get(Tenant, ctx.tenant_id)
    if tenant is None:
        raise ValueError(f"tenant {ctx.tenant_id} bestaat niet")
    return tenant


def _tool_get_brand_config(ctx: ToolContext, _: dict) -> dict:
    return {"config": _load_tenant(ctx).config}


def _tool_fetch_match_price(ctx: ToolContext, tool_input: dict) -> dict:
    url = tool_input["url"]
    return {"price": fetch_match_price(url, client=ctx.http_client)}


def _tool_create_newsletter_draft(ctx: ToolContext, tool_input: dict) -> dict:
    tenant = _load_tenant(ctx)
    brand = tenant.config

    api_key = secrets_repo.get_tenant_secret(ctx.session, ctx.cipher, tenant.id, BREVO_SECRET_KIND)
    if not api_key:
        raise ValueError(
            "geen Brevo API-key ingesteld voor deze tenant (zet die via "
            "PUT /tenants/{id}/secrets)"
        )

    content = NewsletterContent(
        theme=tool_input["theme"],
        subject=tool_input["subject"],
        intro_1=tool_input["intro_1"],
        intro_2=tool_input["intro_2"],
        main_cta_text=tool_input["main_cta_text"],
        main_cta_url=tool_input["main_cta_url"],
        slot_cta_text=tool_input["slot_cta_text"],
        slot_cta_url=tool_input["slot_cta_url"],
        preview_text=tool_input.get("preview_text"),
        matches=tuple(
            Match(home=m["home"], away=m["away"], slug=m["slug"], price=m.get("price", "op aanvraag"))
            for m in tool_input["matches"]
        ),
    )

    template_name = brand.get("template", DEFAULT_TEMPLATE)
    html = render_newsletter(load_template(template_name), brand, content)

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
        "message": "Concept aangemaakt in Brevo. Niets verstuurd; controleer en verstuur handmatig.",
    }


_DISPATCH: dict[str, Callable[[ToolContext, dict], dict]] = {
    "get_brand_config": _tool_get_brand_config,
    "fetch_match_price": _tool_fetch_match_price,
    "create_newsletter_draft": _tool_create_newsletter_draft,
}


def execute_tool(name: str, tool_input: dict, ctx: ToolContext) -> dict:
    handler = _DISPATCH.get(name)
    if handler is None:
        raise ValueError(f"onbekende tool: {name}")
    return handler(ctx, tool_input)
