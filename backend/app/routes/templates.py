"""Routes voor nieuwsbrief-templates per bedrijf.

Rolverdeling:
- Layout (HTML) toevoegen/bewerken/verwijderen: alleen Dunion-admin (require_admin).
- Stijl (kleuren/lettertype) aanpassen + standaard kiezen: ook bedrijfsgebruikers.

De preview rendert met voorbeeld-inhoud zodat een gebruiker het resultaat ziet
voordat er iets wordt opgeslagen of naar Brevo gaat.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_anthropic_client, get_session, require_admin, require_tenant_access
from app.newsletter.models import Club, Match, NewsletterContent, Section
from app.newsletter.renderer import render_newsletter
from app.newsletter.styles import sanitize_styles
from app.newsletter.template_validation import validate_template_html
from app.newsletter.templates import load_template
from app.newsletter.toolproof import MAX_TEMPLATE_CHARS, make_toolproof
from app.repositories import templates as repo
from app.repositories import tenants as tenants_repo
from app.schemas import (
    TemplateCreate,
    TemplatePreviewRequest,
    TemplateRead,
    TemplateStyleUpdate,
    TemplateSummary,
    TemplateToolproofRequest,
    TemplateToolproofResult,
    TemplateUpdate,
    TemplateValidateRequest,
    TemplateValidation,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}", tags=["templates"],
    # Klant-sessies kunnen alleen bij hun eigen bedrijf (admins/team bij alles).
    dependencies=[Depends(require_tenant_access)],
)

STARTER_TEMPLATE = "voetbalreizenxl-main"

# Voorbeeld-inhoud voor de preview (geen echte data nodig).
_SAMPLE = NewsletterContent(
    theme="Voorbeeldnieuwsbrief",
    subject="Zo ziet jouw nieuwsbriefstijl eruit",
    intro_1="Dit is een voorbeeldtekst zodat je ziet hoe je gekozen kleuren en lettertype "
    "in de nieuwsbrief uitpakken. De echte teksten maakt de assistent samen met jou.",
    intro_2="Pas hieronder de stijl aan en bekijk direct het resultaat.",
    main_cta_text="Bekijk alle wedstrijden",
    main_cta_url="https://example.com",
    slot_cta_text="Plan je voetbalreis",
    slot_cta_url="https://example.com",
    matches=(
        Match(home="Arsenal", away="Chelsea", url="https://example.com/tickets", price="€ 329"),
    ),
    clubs=(
        Club(
            name="Real Madrid",
            url="https://example.com/real-madrid",
            price="€ 199",
            image_url=None,
            stadium="Santiago Bernabeu",
            city="Madrid",
        ),
    ),
    header_title="Voorbeeldnieuwsbrief",
    header_subtitle="Zo ziet jouw stijl eruit",
    header_cta_text="Bekijk alle wedstrijden",
    # Voor shell-templates met de ##SECTIES##-marker toont de preview een voorbeeldopzet.
    sections=(
        Section(kind="text", text="Dit is een voorbeeldtekst in jouw gekozen stijl."),
        Section(kind="blocks"),
        Section(kind="button", text="Bekijk alles", url="https://example.com"),
    ),
)


def _require_tenant(session: Session, tenant_id: uuid.UUID):
    tenant = tenants_repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return tenant


def _require_template(session: Session, tenant_id: uuid.UUID, template_id: uuid.UUID):
    template = repo.get_template(session, template_id)
    if template is None or template.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="template niet gevonden")
    return template


# --- Lezen (iedereen die is ingelogd) -------------------------------------
@router.get("/templates", response_model=list[TemplateSummary])
def list_templates(tenant_id: uuid.UUID, session: Session = Depends(get_session)):
    _require_tenant(session, tenant_id)
    return repo.list_templates(session, tenant_id)


@router.get("/templates/starter", dependencies=[Depends(require_admin)])
def starter_html() -> dict:
    """Geeft de ingebouwde standaard-layout terug als startpunt voor een admin."""
    return {"html": load_template(STARTER_TEMPLATE)}


@router.get("/templates/{template_id}", response_model=TemplateRead)
def get_template(
    tenant_id: uuid.UUID, template_id: uuid.UUID, session: Session = Depends(get_session)
):
    return _require_template(session, tenant_id, template_id)


# --- Layout beheren (alleen admin) ----------------------------------------
@router.post(
    "/templates/validate",
    response_model=TemplateValidation,
    dependencies=[Depends(require_admin)],
)
def validate(tenant_id: uuid.UUID, body: TemplateValidateRequest) -> TemplateValidation:
    errors, warnings = validate_template_html(body.html)
    return TemplateValidation(ok=not errors, errors=errors, warnings=warnings)


@router.post(
    "/templates/toolproof",
    response_model=TemplateToolproofResult,
    dependencies=[Depends(require_admin)],
)
def toolproof(
    tenant_id: uuid.UUID,
    body: TemplateToolproofRequest,
    session: Session = Depends(get_session),
    client=Depends(get_anthropic_client),
) -> TemplateToolproofResult:
    """Zet geplakte statische HTML met AI om naar placeholders, met code-verificatie.

    Slaat niets op: de admin ziet het resultaat + rapport en beslist zelf of het
    wordt opgeslagen (via de normale create-flow).
    """
    _require_tenant(session, tenant_id)
    if len(body.html) > MAX_TEMPLATE_CHARS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Template te groot (max {MAX_TEMPLATE_CHARS} tekens).",
        )
    result = make_toolproof(client, body.html)
    return TemplateToolproofResult(
        ok=result.ok,
        html=result.html,
        applied=result.applied,
        failed=result.failed,
        checks_passed=result.checks_passed,
        checks_failed=result.checks_failed,
        warnings=result.warnings,
        notes=result.notes,
    )


@router.post(
    "/templates",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_template(
    tenant_id: uuid.UUID, body: TemplateCreate, session: Session = Depends(get_session)
):
    _require_tenant(session, tenant_id)
    errors, _ = validate_template_html(body.html)
    if errors:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="template is ongeldig: " + "; ".join(errors),
        )
    try:
        return repo.create_template(
            session,
            tenant_id=tenant_id,
            name=body.name.strip(),
            html=body.html,
            styles=body.styles,
            is_default=body.is_default,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Er bestaat al een template met de naam '{body.name.strip()}' voor dit bedrijf.",
        ) from exc


@router.put(
    "/templates/{template_id}",
    response_model=TemplateRead,
    dependencies=[Depends(require_admin)],
)
def update_template(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    body: TemplateUpdate,
    session: Session = Depends(get_session),
):
    _require_template(session, tenant_id, template_id)
    if body.html is not None:
        errors, _ = validate_template_html(body.html)
        if errors:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="template is ongeldig: " + "; ".join(errors),
            )
    name = body.name.strip() if body.name is not None else None
    try:
        return repo.update_template(
            session, template_id, name=name, html=body.html, styles=body.styles
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Er bestaat al een template met de naam '{name}' voor dit bedrijf.",
        ) from exc


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_template(
    tenant_id: uuid.UUID, template_id: uuid.UUID, session: Session = Depends(get_session)
) -> Response:
    _require_template(session, tenant_id, template_id)
    repo.delete_template(session, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Stijl + standaard (bedrijfsgebruiker mag dit ook) --------------------
@router.patch("/templates/{template_id}/styles", response_model=TemplateRead)
def update_styles(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    body: TemplateStyleUpdate,
    session: Session = Depends(get_session),
):
    _require_template(session, tenant_id, template_id)
    return repo.update_styles(session, template_id, body.styles)


@router.post("/templates/{template_id}/default", response_model=TemplateRead)
def set_default(
    tenant_id: uuid.UUID, template_id: uuid.UUID, session: Session = Depends(get_session)
):
    _require_template(session, tenant_id, template_id)
    return repo.set_default(session, tenant_id, template_id)


# --- Preview (iedereen) ----------------------------------------------------
@router.post("/templates/preview")
def preview(
    tenant_id: uuid.UUID, body: TemplatePreviewRequest, session: Session = Depends(get_session)
) -> Response:
    tenant = _require_tenant(session, tenant_id)
    if body.html is not None:
        html_template = body.html
    elif body.template_id is not None:
        html_template = _require_template(session, tenant_id, body.template_id).html
    else:
        html_template = load_template(STARTER_TEMPLATE)
    brand = {**tenant.config, "styles": sanitize_styles(body.styles)}
    try:
        rendered = render_newsletter(html_template, brand, _SAMPLE)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(content=rendered, media_type="text/html")
