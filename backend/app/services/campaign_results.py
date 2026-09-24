"""Resultaten van een nieuwsbrief ophalen uit het verzendplatform en bewaren.

Alleen-lezen richting het platform. Het resultaat wordt in newsletters.stats
bewaard: de Nieuwsbrieven-tab toont het zonder opnieuw te vragen, en de chat-tool
get_recent_newsletters kan zien welke onderwerpregels goed werkten. Een
afkoeltijd voorkomt dat we het platform onnodig bestoken (Klaviyo: 2 rapporten
per minuut, 225 per dag).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Newsletter, Tenant
from app.repositories import newsletters as newsletters_repo
from app.services.crypto import SecretCipher
from app.services.esp import SENT, CampaignNotFound
from app.services.esp_connection import (
    ESP_ERRORS,
    EspFactories,
    belongs_to,
    campaign_ref,
    connect,
    esp_of,
)

COOLDOWN = timedelta(minutes=10)


@dataclass(frozen=True)
class ResultsOutcome:
    stats: dict | None
    fetched_at: datetime | None
    from_cache: bool


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _friendly(label: str, exc: Exception) -> str:
    tekst = str(exc)
    if "403" in tekst or "401" in tekst:
        return (
            f"{label} weigert het ophalen van resultaten: de API-key mist leesrechten "
            "(bij Klaviyo: campaigns:read en metrics:read)."
        )
    return f"{label} gaf geen resultaten: {tekst}"


def refresh_results(
    session: Session,
    cipher: SecretCipher,
    tenant: Tenant,
    newsletter: Newsletter,
    *,
    factories: EspFactories = EspFactories(),
    now: datetime | None = None,
) -> ResultsOutcome:
    """Haal de resultaten op (of geef de recente bewaarde terug). ValueError = nette melding."""
    if newsletter.status == "failed" or not belongs_to(newsletter, esp_of(tenant)):
        raise ValueError("Deze nieuwsbrief heeft geen campagne in het huidige verzendplatform.")
    moment = now or datetime.now(timezone.utc)
    if newsletter.stats is not None and newsletter.stats_fetched_at is not None:
        if moment - _aware(newsletter.stats_fetched_at) < COOLDOWN:
            return ResultsOutcome(newsletter.stats, newsletter.stats_fetched_at, from_cache=True)

    conn = connect(session, cipher, tenant, factories)
    try:
        results = conn.client.get_results(campaign_ref(newsletter))
    except CampaignNotFound as exc:
        raise ValueError(f"Deze campagne bestaat niet meer in {conn.label}.") from exc
    except ESP_ERRORS as exc:
        raise ValueError(_friendly(conn.label, exc)) from exc

    updated = newsletters_repo.update_newsletter(
        session,
        newsletter,
        stats=results.as_dict(),
        stats_fetched_at=func.now(),
        # Verstuurd in het platform? Dan is het geen concept meer: ook de chat
        # werkt het daarna nooit meer bij.
        status="sent" if results.status == SENT else newsletter.status,
    )
    return ResultsOutcome(updated.stats, updated.stats_fetched_at, from_cache=False)
