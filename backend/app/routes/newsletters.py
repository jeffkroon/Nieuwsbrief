"""Routes voor de gemaakte nieuwsbrieven van een bedrijf.

De concepten stonden al in de database maar waren nergens terug te zien: de
accountmanager moest zelf in Brevo, Klaviyo of ActiveCampaign gaan zoeken. Deze
routes geven de lijst, de HTML voor een voorbeeld, en een link naar het concept
in het verzendplatform.

Aanmaken gebeurt uitsluitend via de chat (met de toestemming-gate en alle
validaties); hier kan niets worden gemaakt, gewijzigd of verstuurd. Het enige
dat hier naar een platform gaat is het LEZEN van resultaten (open/klik), die we
in de database bewaren.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.deps import get_cipher, get_esp_factories, get_session, require_tenant_access
from app.newsletter.esp_links import campaign_link
from app.repositories import newsletters as repo
from app.repositories import tenants as tenants_repo
from app.schemas import NewsletterResults, NewsletterSummary
from app.services import campaign_results
from app.services.crypto import SecretCipher
from app.services.esp_connection import EspFactories

router = APIRouter(
    prefix="/tenants/{tenant_id}",
    tags=["newsletters"],
    dependencies=[Depends(require_tenant_access)],
)


def _require_tenant(session: Session, tenant_id: uuid.UUID):
    tenant = tenants_repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return tenant


@router.get("/newsletters", response_model=list[NewsletterSummary])
def list_newsletters(
    tenant_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[NewsletterSummary]:
    """Gemaakte concepten, nieuwste eerst, met een link naar het verzendplatform."""
    tenant = _require_tenant(session, tenant_id)
    config = tenant.config or {}
    esp = config.get("esp", "brevo")
    api_url = config.get("activecampaign_api_url", "")

    resultaat = []
    for nieuwsbrief in repo.list_newsletters(session, tenant_id):
        ref = (
            str(nieuwsbrief.brevo_campaign_id)
            if nieuwsbrief.brevo_campaign_id is not None
            else nieuwsbrief.esp_campaign_ref
        )
        link = campaign_link(esp, ref, api_url=api_url) if ref else None
        resultaat.append(
            NewsletterSummary(
                id=nieuwsbrief.id,
                subject=nieuwsbrief.subject,
                theme=nieuwsbrief.theme,
                status=nieuwsbrief.status,
                esp=esp,
                campaign_ref=ref,
                link_url=link.url if link else None,
                link_label=link.label if link else None,
                link_is_deeplink=link.is_deeplink if link else False,
                conversation_id=nieuwsbrief.conversation_id,
                created_at=nieuwsbrief.created_at,
                stats=nieuwsbrief.stats,
                stats_fetched_at=nieuwsbrief.stats_fetched_at,
            )
        )
    return resultaat


def _require_newsletter(session: Session, tenant_id: uuid.UUID, newsletter_id: uuid.UUID):
    nieuwsbrief = repo.get_newsletter(session, newsletter_id)
    if nieuwsbrief is None or nieuwsbrief.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="nieuwsbrief niet gevonden")
    return nieuwsbrief


@router.post("/newsletters/{newsletter_id}/results", response_model=NewsletterResults)
def refresh_newsletter_results(
    tenant_id: uuid.UUID,
    newsletter_id: uuid.UUID,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
    factories: EspFactories = Depends(get_esp_factories),
) -> NewsletterResults:
    """Open- en klikcijfers uit het verzendplatform ophalen (alleen-lezen) en bewaren."""
    tenant = _require_tenant(session, tenant_id)
    nieuwsbrief = _require_newsletter(session, tenant_id, newsletter_id)
    try:
        uitkomst = campaign_results.refresh_results(
            session, cipher, tenant, nieuwsbrief, factories=factories
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return NewsletterResults(
        stats=uitkomst.stats, fetched_at=uitkomst.fetched_at, from_cache=uitkomst.from_cache
    )


@router.get("/newsletters/{newsletter_id}/html")
def newsletter_html(
    tenant_id: uuid.UUID, newsletter_id: uuid.UUID, session: Session = Depends(get_session)
) -> Response:
    """De verstuurde HTML van dit concept, voor het voorbeeld-venster."""
    _require_tenant(session, tenant_id)
    nieuwsbrief = _require_newsletter(session, tenant_id, newsletter_id)
    return Response(content=nieuwsbrief.html or "", media_type="text/html")
