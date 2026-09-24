"""Gedeelde context en hulpjes voor alle chat-tools (tenant, LLM, validatie-cache)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.db.models import Tenant
from app.newsletter.validation_cache import ValidationCache
from app.services.activecampaign import ActiveCampaignClient
from app.services.brevo import BrevoClient
from app.services.crypto import SecretCipher
from app.services.klaviyo import KlaviyoClient

# Neutrale, merk-gekleurde fallback voor tenants zonder eigen template (geen
# voetbal-styling meer). De klant-specifieke voetbal-template blijft bestaan en
# wordt gebruikt zodra een tenant hem als eigen/standaard template heeft of via
# config["template"] expliciet kiest.
DEFAULT_TEMPLATE = "neutraal-basis"
# De oorspronkelijke paddings van de oude fallback-template (zie de tokens in het
# html-bestand); als basis-stijl meegegeven zodat een render die deze tokens wél
# gebruikt identiek blijft. De neutrale template gebruikt ze niet (onschadelijk).
FALLBACK_TEMPLATE_STYLES = {
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


# Validatie-cache: identieke live-checks (prijs, bereikbaarheid, og-foto) binnen
# 10 minuten niet herhalen. Nieuwe/gewijzigde blokken raken andere sleutels en
# worden dus gewoon gevalideerd; garanties blijven in code.
validation_cache = ValidationCache()


def load_tenant(ctx: ToolContext) -> Tenant:
    tenant = ctx.session.get(Tenant, ctx.tenant_id)
    if tenant is None:
        raise ValueError(f"tenant {ctx.tenant_id} bestaat niet")
    return tenant


def require_llm(ctx: ToolContext):
    if ctx.llm is None:
        raise ValueError("geen LLM beschikbaar voor site-extractie")
    return ctx.llm
