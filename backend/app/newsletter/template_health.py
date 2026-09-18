"""Gezondheidscheck per tenant: is de basis waarop verstuurd wordt in orde?

Zonder deze check moet je met handmatige SQL controleren of een tenant een
geldige standaard-template heeft. Deze functie bundelt de controles: bestaat er
een eigen (standaard) template, doorstaat die de opslag-garantie, en zijn de
verplichte brand-velden aanwezig. Puur leesbaar rapport, geen mutaties.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.newsletter.renderer import REQUIRED_BRAND_FIELDS
from app.newsletter.save_validation import validate_template_for_save
from app.repositories import templates as templates_repo
from app.repositories import tenants as tenants_repo


def tenant_template_health(session: Session, tenant_id: uuid.UUID) -> dict:
    """Geef een groen/rood-rapport over de template-basis van één tenant."""
    tenant = tenants_repo.get_tenant(session, tenant_id)
    if tenant is None:
        return {"ok": False, "reden": "tenant bestaat niet"}

    brand = tenant.config or {}
    ontbrekende_brand_velden = [f for f in REQUIRED_BRAND_FIELDS if not brand.get(f)]

    default = templates_repo.get_default_template(session, tenant_id)
    if default is None:
        return {
            "ok": False,
            "heeft_eigen_template": False,
            "reden": "geen eigen template; de neutrale fallback wordt gebruikt",
            "ontbrekende_brand_velden": ontbrekende_brand_velden,
        }

    opslag_fouten, waarschuwingen = validate_template_for_save(
        default.html, default.styles
    )
    return {
        "ok": not opslag_fouten and not ontbrekende_brand_velden,
        "heeft_eigen_template": True,
        "template_naam": default.name,
        "is_standaard": bool(default.is_default),
        "opslag_fouten": opslag_fouten,
        "waarschuwingen": waarschuwingen,
        "ontbrekende_brand_velden": ontbrekende_brand_velden,
    }
