"""Routes voor de gemaakte nieuwsbrieven van een bedrijf.

De concepten stonden al in de database maar waren nergens terug te zien: de
accountmanager moest zelf in Brevo, Klaviyo of ActiveCampaign gaan zoeken. Deze
routes geven de lijst, de HTML voor een voorbeeld, en een link naar het concept
in het verzendplatform.

Alleen lezen. Aanmaken gebeurt uitsluitend via de chat (met de toestemming-gate
en alle validaties); hier kan niets worden gemaakt, gewijzigd of verstuurd.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.deps import get_session, require_tenant_access
from app.newsletter.esp_links import campaign_link
from app.repositories import newsletters as repo
from app.repositories import tenants as tenants_repo
from app.schemas import NewsletterSummary

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
            )
        )
    return resultaat


@router.get("/newsletters/{newsletter_id}/html")
def newsletter_html(
    tenant_id: uuid.UUID, newsletter_id: uuid.UUID, session: Session = Depends(get_session)
) -> Response:
    """De verstuurde HTML van dit concept, voor het voorbeeld-venster."""
    _require_tenant(session, tenant_id)
    nieuwsbrief = repo.get_newsletter(session, newsletter_id)
    if nieuwsbrief is None or nieuwsbrief.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="nieuwsbrief niet gevonden")
    return Response(content=nieuwsbrief.html or "", media_type="text/html")
