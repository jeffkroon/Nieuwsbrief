"""Routes voor nieuwsbrief-templates per bedrijf.

Rolverdeling:
- Layout (HTML) toevoegen/bewerken/verwijderen: alleen Dunion-admin (require_admin).
- Stijl (kleuren/lettertype) aanpassen + standaard kiezen: ook bedrijfsgebruikers.

De preview rendert met voorbeeld-inhoud zodat een gebruiker het resultaat ziet
voordat er iets wordt opgeslagen of naar Brevo gaat.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import (
    SessionInfo,
    current_session_info,
    get_anthropic_client,
    get_session,
    get_storage,
    require_admin,
    require_tenant_access,
)
from app.services.llm_usage import TrackingLLM
from app.services.storage import StorageError
from app.newsletter.brand_colors import contrast_waarschuwingen, palette_from_primary
from app.newsletter.capabilities import capability_labels, template_capabilities
from app.newsletter.models import Club, Match, NewsletterContent, Section
from app.newsletter.preview_content import content_from_draft_input
from app.newsletter.renderer import render_newsletter
from app.newsletter.styles import sanitize_styles
from app.newsletter.save_validation import validate_template_for_save
from app.newsletter.template_diff import unified_html_diff
from app.newsletter.template_health import tenant_template_health
from app.newsletter.template_import import TemplateImportError, import_upload
from app.newsletter.templates import load_template
from app.newsletter.toolproof import MAX_TEMPLATE_CHARS, make_toolproof
from app.repositories import newsletters as newsletters_repo
from app.repositories import template_versions as versions_repo
from app.repositories import templates as repo
from app.repositories import tenants as tenants_repo
from app.schemas import (
    TemplateCapabilitiesRequest,
    TemplateCapabilitiesResult,
    TemplateCreate,
    TemplateImportResult,
    TemplatePreviewRequest,
    TemplateRead,
    TemplateStyleCheck,
    TemplateStyleSuggestion,
    TemplateStyleUpdate,
    TemplateSummary,
    TemplateToolproofRequest,
    TemplateToolproofResult,
    TemplateUpdate,
    TemplateValidateRequest,
    TemplateValidation,
    TemplateVersionSummary,
)

router = APIRouter(
    prefix="/tenants/{tenant_id}", tags=["templates"],
    # Klant-sessies kunnen alleen bij hun eigen bedrijf (admins/team bij alles).
    dependencies=[Depends(require_tenant_access)],
)

STARTER_TEMPLATE = "voetbalreizenxl-main"


def _veilige_naam(naam: str) -> str:
    """Bestandsnaam zonder pad, zodat een ZIP niet buiten zijn map kan schrijven."""
    basis = (naam or "afbeelding").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return basis.replace(" ", "-") or "afbeelding"


def _zorg_voor_bucket(storage) -> None:
    """Bucket aanmaken als die er nog niet is; bestaat hij al, dan is dit een no-op."""
    try:
        storage.ensure_bucket()
    except (StorageError, AttributeError):
        pass

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


@router.get("/templates/health", dependencies=[Depends(require_admin)])
def template_health(
    tenant_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict:
    """Groen/rood-rapport: heeft deze tenant een geldige eigen standaard-template?"""
    _require_tenant(session, tenant_id)
    return tenant_template_health(session, tenant_id)


@router.get("/templates/style-suggestion", response_model=TemplateStyleSuggestion)
def style_suggestion(
    tenant_id: uuid.UUID,
    primary: str | None = None,
    session: Session = Depends(get_session),
) -> TemplateStyleSuggestion:
    """Stel een heel palet voor op basis van de huisstijlkleur van dit bedrijf.

    Bewust niet de website scrapen: sites op Bootstrap leveren honderden
    framework-kleuren op en het meest voorkomende is dan Bootstrap-blauw, niet de
    merkkleur. De huisstijlkleur bij het bedrijf is door een mens gecontroleerd.
    """
    tenant = _require_tenant(session, tenant_id)
    # Zelf een kleur kiezen mag; zonder keuze geldt de huisstijlkleur van het bedrijf.
    primair = (primary or "").strip() or (tenant.config or {}).get("primary_color") or ""
    styles = palette_from_primary(primair)
    if not styles:
        return TemplateStyleSuggestion(
            note=(
                "Geen geldige kleur. Zet de huisstijlkleur van dit bedrijf in de "
                "Bedrijven-tab, of kies hier zelf een hoofdkleur."
            )
        )
    return TemplateStyleSuggestion(
        styles=styles,
        primary_color=primair,
        note=(
            "Voorstel op basis van de huisstijlkleur. De knopteksten zijn berekend op "
            "leesbaarheid. Bekijk het voorbeeld en sla op als het klopt."
        ),
    )


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
    errors, warnings = validate_template_for_save(body.html)
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
    result = make_toolproof(
        TrackingLLM(client, session, purpose="toolproof", tenant_id=tenant_id), body.html
    )
    return TemplateToolproofResult(
        ok=result.ok,
        html=result.html,
        diff=unified_html_diff(body.html, result.html),
        capabilities=capability_labels(result.html),
        styles=result.styles,
        applied=result.applied,
        failed=result.failed,
        checks_passed=result.checks_passed,
        checks_failed=result.checks_failed,
        warnings=result.warnings,
        notes=result.notes,
    )


@router.post(
    "/templates/upload",
    response_model=TemplateImportResult,
    dependencies=[Depends(require_admin)],
)
def upload_template(
    tenant_id: uuid.UUID,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    storage=Depends(get_storage),
) -> TemplateImportResult:
    """Een .html-bestand of .zip-export inlezen (nog niet opslaan).

    Bij een ZIP gaan de meegeleverde afbeeldingen naar de beeldopslag van dit
    bedrijf en worden de verwijzingen in de HTML vervangen door de publieke URL;
    anders zou de mail bij de ontvanger met kapotte plaatjes aankomen.
    """
    _require_tenant(session, tenant_id)
    raw = file.file.read()

    def _store(naam: str, inhoud: bytes, content_type: str) -> str:
        pad = f"{tenant_id}/templates/{uuid.uuid4().hex}-{_veilige_naam(naam)}"
        return storage.upload(pad, inhoud, content_type).url

    try:
        _zorg_voor_bucket(storage)
        imported = import_upload(file.filename or "", raw, store=_store)
    except TemplateImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"De afbeeldingen uit de ZIP konden niet worden opgeslagen: {exc}",
        ) from exc

    if len(imported.html) > MAX_TEMPLATE_CHARS:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Template te groot (max {MAX_TEMPLATE_CHARS} tekens).",
        )
    return TemplateImportResult(
        html=imported.html,
        images=[image.path for image in imported.images],
        notes=list(imported.notes),
        capabilities=capability_labels(imported.html),
    )


@router.post(
    "/templates/capabilities",
    response_model=TemplateCapabilitiesResult,
    dependencies=[Depends(require_admin)],
)
def capabilities(
    tenant_id: uuid.UUID,
    body: TemplateCapabilitiesRequest,
    session: Session = Depends(get_session),
) -> TemplateCapabilitiesResult:
    """Wat ondersteunt deze template? Zelfde feiten als de assistent krijgt."""
    if body.html is not None:
        html = body.html
    elif body.template_id is not None:
        html = _require_template(session, tenant_id, body.template_id).html
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Geef html of template_id mee."
        )
    return TemplateCapabilitiesResult(
        summary=capability_labels(html), details=template_capabilities(html)
    )

@router.post(
    "/templates",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_template(
    tenant_id: uuid.UUID,
    body: TemplateCreate,
    session: Session = Depends(get_session),
    info: SessionInfo = Depends(current_session_info),
):
    _require_tenant(session, tenant_id)
    errors, _ = validate_template_for_save(body.html, body.styles)
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
            source=body.source,
            actor=info.role,
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
    info: SessionInfo = Depends(current_session_info),
):
    _require_template(session, tenant_id, template_id)
    if body.html is not None:
        errors, _ = validate_template_for_save(body.html, body.styles)
        if errors:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="template is ongeldig: " + "; ".join(errors),
            )
    name = body.name.strip() if body.name is not None else None
    try:
        return repo.update_template(
            session,
            template_id,
            name=name,
            html=body.html,
            styles=body.styles,
            source=body.source,
            actor=info.role,
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



# --- Versies (alleen admin) ------------------------------------------------
@router.get(
    "/templates/{template_id}/versions",
    response_model=list[TemplateVersionSummary],
    dependencies=[Depends(require_admin)],
)
def list_versions(
    tenant_id: uuid.UUID, template_id: uuid.UUID, session: Session = Depends(get_session)
) -> list:
    _require_template(session, tenant_id, template_id)
    return versions_repo.list_versions(session, template_id)


@router.post(
    "/templates/{template_id}/versions/{version_id}/restore",
    response_model=TemplateRead,
    dependencies=[Depends(require_admin)],
)
def restore_version(
    tenant_id: uuid.UUID,
    template_id: uuid.UUID,
    version_id: uuid.UUID,
    session: Session = Depends(get_session),
    info: SessionInfo = Depends(current_session_info),
):
    """Zet een eerdere layout terug; de huidige blijft als versie bewaard."""
    _require_template(session, tenant_id, template_id)
    version = versions_repo.get_version(session, version_id)
    if version is None or version.template_id != template_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="versie niet gevonden")
    errors, _ = validate_template_for_save(version.html, version.styles)
    if errors:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="deze versie is niet meer geldig: " + "; ".join(errors),
        )
    return repo.update_template(
        session,
        template_id,
        html=version.html,
        styles=version.styles,
        source="terugzetten",
        actor=info.role,
    )



# --- Kleuren: voorstel en leesbaarheidscontrole ---------------------------
@router.post("/templates/style-check", response_model=TemplateStyleCheck)
def style_check(tenant_id: uuid.UUID, body: TemplateStyleUpdate) -> TemplateStyleCheck:
    """Kan de lezer deze kleurcombinatie lezen? Alleen melden, nooit blokkeren."""
    return TemplateStyleCheck(warnings=contrast_waarschuwingen(body.styles))


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
    content = _SAMPLE
    if body.newsletter_id is not None:
        newsletter = newsletters_repo.get_newsletter(session, body.newsletter_id)
        if newsletter is None or newsletter.tenant_id != tenant_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="nieuwsbrief niet gevonden")
        content = content_from_draft_input(
            newsletter.input, subject=newsletter.subject or "", theme=newsletter.theme or ""
        )
    try:
        rendered = render_newsletter(html_template, brand, content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return Response(content=rendered, media_type="text/html")
