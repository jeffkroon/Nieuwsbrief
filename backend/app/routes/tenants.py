"""CRUD-routes voor tenants en het zetten van tenant-secrets."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.deps import (
    SessionInfo,
    get_supabase_auth,
    current_session_info,
    get_anthropic_client,
    get_cipher,
    get_session,
    require_admin,
    require_tenant_access,
)
from app.services.passwords import hash_password
from app.repositories import secrets as secrets_repo
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.repositories import tenants as repo
from app.repositories import users as users_repo
from app.services.supabase_auth import SupabaseAuthError
from app.schemas import (
    EspListsRequest,
    EspListsResult,
    TenantCreate,
    TenantPasswordSet,
    TenantUserInvite,
    TenantUserRead,
    TenantPrefillRequest,
    TenantPrefillResult,
    TenantRead,
    TenantSecretSet,
    TenantUpdate,
)
from app.services.brevo import BrevoClient, BrevoError
from app.services.company_prefill import prefill_company
from app.services.crypto import SecretCipher
from app.services.klaviyo import KlaviyoClient, KlaviyoError
from app.services.tone import analyze_and_store_tone, get_cached_tone

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post(
    "",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_tenant(data: TenantCreate, session: Session = Depends(get_session)) -> TenantRead:
    if repo.get_tenant_by_slug(session, data.slug) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"tenant met slug '{data.slug}' bestaat al"
        )
    return repo.create_tenant(session, data)


@router.post(
    "/prefill",
    response_model=TenantPrefillResult,
    dependencies=[Depends(require_admin)],
)
def prefill_tenant(
    body: TenantPrefillRequest,
    client=Depends(get_anthropic_client),
) -> TenantPrefillResult:
    """Vul een bedrijfsvoorstel automatisch vanaf de website (naam + URL volstaan).

    Maakt niets aan: de admin krijgt het voorstel in het formulier en beslist zelf.
    """
    url = body.website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    try:
        result = prefill_company(client, name=body.name.strip(), website_url=url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return TenantPrefillResult(**result)


@router.post(
    "/esp-lists",
    response_model=EspListsResult,
    dependencies=[Depends(require_admin)],
)
def esp_lists(
    body: EspListsRequest,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
) -> EspListsResult:
    """Contactenlijsten van het verzendplatform ophalen (alleen-lezen), zodat de
    admin een lijst kan KIEZEN in plaats van een ID op te zoeken."""
    api_key = (body.api_key or "").strip()
    if not api_key and body.tenant_id:
        kind = "klaviyo_api_key" if body.esp == "klaviyo" else "brevo_api_key"
        api_key = secrets_repo.get_tenant_secret(session, cipher, body.tenant_id, kind) or ""
    if not api_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Geen API-key: plak de key in het formulier of sla 'm eerst op bij het bedrijf.",
        )
    try:
        client = KlaviyoClient(api_key) if body.esp == "klaviyo" else BrevoClient(api_key)
        lists = client.get_lists()
    except (KlaviyoError, BrevoError, ValueError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return EspListsResult(lists=lists)


@router.get("", response_model=list[TenantRead])
def list_tenants(
    session: Session = Depends(get_session),
    info: SessionInfo = Depends(current_session_info),
) -> list[TenantRead]:
    tenants = repo.list_tenants(session)
    if info.tenant_id is not None:  # klant-login: alleen het eigen bedrijf
        tenants = [t for t in tenants if t.id == info.tenant_id]
    return tenants


@router.get("/{tenant_id}", response_model=TenantRead, dependencies=[Depends(require_tenant_access)])
def get_tenant(tenant_id: uuid.UUID, session: Session = Depends(get_session)) -> TenantRead:
    tenant = repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return tenant


@router.patch("/{tenant_id}", response_model=TenantRead, dependencies=[Depends(require_admin)])
def update_tenant(
    tenant_id: uuid.UUID, data: TenantUpdate, session: Session = Depends(get_session)
) -> TenantRead:
    tenant = repo.update_tenant(session, tenant_id, data)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return tenant


@router.delete(
    "/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)]
)
def delete_tenant(tenant_id: uuid.UUID, session: Session = Depends(get_session)) -> Response:
    if not repo.delete_tenant(session, tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{tenant_id}/users",
    response_model=list[TenantUserRead],
    dependencies=[Depends(require_admin)],
)
def list_tenant_users(
    tenant_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[TenantUserRead]:
    if repo.get_tenant(session, tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return users_repo.list_users(session, tenant_id)


@router.post(
    "/{tenant_id}/users",
    response_model=TenantUserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def invite_tenant_user(
    tenant_id: uuid.UUID,
    body: TenantUserInvite,
    request: Request,
    session: Session = Depends(get_session),
    supabase=Depends(get_supabase_auth),
) -> TenantUserRead:
    """Nodig een klant-gebruiker uit: Supabase stuurt de mail, wij koppelen het
    account aan dit bedrijf. Diens login ziet daarna alleen dit bedrijf."""
    if repo.get_tenant(session, tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    email = body.email.strip().lower()
    if users_repo.get_user_by_email(session, email) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="dit e-mailadres heeft al een account"
        )
    settings = get_settings()
    base_url = (settings.app_base_url or str(request.base_url)).rstrip("/")
    try:
        auth_user_id = supabase.invite_user(email, redirect_to=f"{base_url}/welkom")
    except SupabaseAuthError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    try:
        return users_repo.create_user(
            session, user_id=auth_user_id, tenant_id=tenant_id, email=email
        )
    except IntegrityError as exc:
        # Race: tweede invite voor hetzelfde adres won de unique-constraint niet.
        session.rollback()
        supabase.delete_auth_user(auth_user_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="dit e-mailadres heeft al een account"
        ) from exc


@router.delete(
    "/{tenant_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_tenant_user(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session: Session = Depends(get_session),
    supabase=Depends(get_supabase_auth),
) -> Response:
    user = users_repo.get_user(session, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="gebruiker niet gevonden")
    users_repo.delete_user(session, user_id)
    supabase.delete_auth_user(user_id)  # best effort
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{tenant_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def set_tenant_password(
    tenant_id: uuid.UUID, body: TenantPasswordSet, session: Session = Depends(get_session)
) -> Response:
    """Stel het klant-login-wachtwoord voor dit bedrijf in (alleen beheerders).

    Het wachtwoord wordt alleen als hash opgeslagen en is nergens terug te lezen.
    """
    tenant = repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    try:
        tenant.password_hash = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{tenant_id}/tone", dependencies=[Depends(require_tenant_access)])
def get_tone(tenant_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    """De (gecachte) tone of voice van het bedrijf; None als die er nog niet is."""
    tenant = repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    return {"tone_of_voice": get_cached_tone(tenant)}


@router.post("/{tenant_id}/tone/refresh", dependencies=[Depends(require_tenant_access)])
def refresh_tone(
    tenant_id: uuid.UUID,
    session: Session = Depends(get_session),
    client=Depends(get_anthropic_client),
) -> dict:
    """Analyseer de tone of voice opnieuw van de website en cache 'm (voor als de site is vernieuwd)."""
    tenant = repo.get_tenant(session, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    tone = analyze_and_store_tone(session, tenant, client)
    if tone is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Kon de tone of voice niet bepalen (geen website_url of pagina onbereikbaar).",
        )
    return {"tone_of_voice": tone}


@router.put(
    "/{tenant_id}/secrets",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def set_tenant_secret(
    tenant_id: uuid.UUID,
    body: TenantSecretSet,
    session: Session = Depends(get_session),
    cipher: SecretCipher = Depends(get_cipher),
) -> Response:
    if repo.get_tenant(session, tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="tenant niet gevonden")
    secrets_repo.set_tenant_secret(session, cipher, tenant_id, body.kind, body.value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
