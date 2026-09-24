"""De juiste verzendplatform-client voor een bedrijf, met zijn eigen API-key.

Gedeeld door de concept-tool (chat) en het ophalen van resultaten (Nieuwsbrieven-
tab), zodat de keuze van platform, key en lijst op één plek zit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Newsletter, Tenant
from app.repositories import secrets as secrets_repo
from app.services.activecampaign import (
    ActiveCampaignClient,
    ActiveCampaignError,
    validate_api_url,
)
from app.services.brevo import BrevoClient, BrevoError
from app.services.crypto import SecretCipher
from app.services.esp import EspClient
from app.services.klaviyo import KlaviyoClient, KlaviyoError

BREVO_SECRET_KIND = "brevo_api_key"
KLAVIYO_SECRET_KIND = "klaviyo_api_key"
ACTIVECAMPAIGN_SECRET_KIND = "activecampaign_api_key"
ESP_LABELS = {"brevo": "Brevo", "klaviyo": "Klaviyo", "activecampaign": "ActiveCampaign"}
_SECRET_KINDS = {"klaviyo": KLAVIYO_SECRET_KIND, "activecampaign": ACTIVECAMPAIGN_SECRET_KIND}

# Fouten die een platform kan geven; de aanroeper vertaalt ze naar een nette melding.
ESP_ERRORS = (BrevoError, KlaviyoError, ActiveCampaignError)


@dataclass(frozen=True)
class EspFactories:
    """Injecteerbaar voor tests; standaard de echte clients."""

    brevo: Callable[[str], BrevoClient] = BrevoClient
    klaviyo: Callable[[str], KlaviyoClient] = KlaviyoClient
    activecampaign: Callable[[str, str], ActiveCampaignClient] = ActiveCampaignClient


@dataclass(frozen=True)
class EspConnection:
    esp: str
    label: str
    client: EspClient
    list_ids: list | None


def esp_of(tenant: Tenant) -> str:
    return (tenant.config or {}).get("esp", "brevo")


def connect(
    session: Session,
    cipher: SecretCipher,
    tenant: Tenant,
    factories: EspFactories = EspFactories(),
) -> EspConnection:
    """Client + lijst voor dit bedrijf; ValueError met uitleg als iets ontbreekt."""
    config = tenant.config or {}
    esp = esp_of(tenant)
    label = ESP_LABELS.get(esp, "Brevo")
    api_key = secrets_repo.get_tenant_secret(
        session, cipher, tenant.id, _SECRET_KINDS.get(esp, BREVO_SECRET_KIND)
    )
    if not api_key:
        raise ValueError(
            f"geen {label} API-key ingesteld voor deze tenant "
            "(zet die via de Bedrijven-tab of PUT /tenants/{id}/secrets)"
        )
    if esp == "klaviyo":
        list_id = config.get("klaviyo_list_id")
        return EspConnection(esp, label, factories.klaviyo(api_key), [list_id] if list_id else None)
    if esp == "activecampaign":
        # Hard valideren VOOR de render: een kapotte URL mag geen dure
        # validatie-ronde kosten en moet een duidelijke fout geven.
        try:
            api_url = validate_api_url(config.get("activecampaign_api_url") or "")
        except ValueError as exc:
            raise ValueError(
                f"{exc} Stel de API-URL in via de Bedrijven-tab > Verzendplatform."
            ) from exc
        list_id = config.get("activecampaign_list_id")
        return EspConnection(
            esp, label, factories.activecampaign(api_url, api_key), [list_id] if list_id else None
        )
    list_ids = [tenant.brevo_list_id] if tenant.brevo_list_id else None
    return EspConnection(esp, label, factories.brevo(api_key), list_ids)


def campaign_ref(newsletter: Newsletter) -> Any:
    """De campagne-id in het platform: int bij Brevo, tekst bij Klaviyo/ActiveCampaign."""
    if newsletter.brevo_campaign_id is not None:
        return newsletter.brevo_campaign_id
    return newsletter.esp_campaign_ref


def belongs_to(newsletter: Newsletter, esp: str) -> bool:
    """Hoort deze campagne bij het huidige platform? (bedrijf kan van ESP wisselen)"""
    if campaign_ref(newsletter) is None:
        return False
    return (newsletter.brevo_campaign_id is not None) == (esp == "brevo")
