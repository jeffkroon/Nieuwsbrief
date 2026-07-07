"""FastAPI-dependencies: database-sessie en secret-cipher."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.db.session import get_session  # noqa: F401  (re-export als dependency)
from app.middleware import COOKIE_NAME, session_claims
from app.services.crypto import SecretCipher


@dataclass(frozen=True)
class SessionInfo:
    """Wie is er ingelogd: rol + (voor klant-logins) het bedrijf van de sessie.

    tenant_id None = niet aan één bedrijf gebonden: een admin, of een teamlid
    met het gedeelde wachtwoord.
    """

    role: str
    tenant_id: uuid.UUID | None = None


def current_session_info(
    request: Request, settings: Settings = Depends(get_settings)
) -> SessionInfo:
    """Sessie-info van de huidige gebruiker. Zonder slot (lokaal/dev) is iedereen admin."""
    if not settings.access_password:
        return SessionInfo(role="admin")
    claims = session_claims(request.cookies.get(COOKIE_NAME), settings.access_password)
    if claims is None:
        return SessionInfo(role="company")
    role, tenant_raw = claims
    tenant_id: uuid.UUID | None = None
    if tenant_raw:
        try:
            tenant_id = uuid.UUID(tenant_raw)
        except ValueError:
            tenant_id = None
    return SessionInfo(role=role, tenant_id=tenant_id)


def current_role(info: SessionInfo = Depends(current_session_info)) -> str:
    """Rol van de huidige sessie (voor bestaande admin-checks)."""
    return info.role


def require_tenant_access(
    tenant_id: uuid.UUID, info: SessionInfo = Depends(current_session_info)
) -> None:
    """Blokkeer toegang tot andermans bedrijf voor bedrijfsgebonden sessies.

    Admins en ongebonden team-sessies mogen alles; een klant-login (sessie met
    tenant_id) mag alleen het eigen bedrijf benaderen. Werkt via de tenant_id
    uit het URL-pad, dus bruikbaar als router-brede dependency.
    """
    if info.role == "admin" or info.tenant_id is None or info.tenant_id == tenant_id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Geen toegang tot dit bedrijf.")


def require_admin(role: str = Depends(current_role)) -> None:
    """Alleen Dunion-admins mogen template-layouts beheren."""
    if role != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Alleen Dunion-beheerders mogen template-layouts beheren.",
        )


@lru_cache
def get_cipher() -> SecretCipher:
    return SecretCipher(get_settings().secret_encryption_key)


@lru_cache
def get_supabase_auth():
    """Supabase Auth-laag (JWKS-verificatie + uitnodigen). Faalt duidelijk zonder config."""
    from app.services.supabase_auth import SupabaseAuth

    settings = get_settings()
    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL ontbreekt in de omgeving")
    return SupabaseAuth(settings.supabase_url, settings.supabase_service_role_key)


@lru_cache
def get_storage():
    """Bouwt de Supabase Storage-client. Faalt duidelijk als config ontbreekt."""
    from app.services.storage import SupabaseStorage

    settings = get_settings()
    return SupabaseStorage(
        settings.supabase_url,
        settings.supabase_service_role_key,
        bucket=settings.images_bucket,
    )


@lru_cache
def get_anthropic_client():
    """Bouwt de Anthropic-client. Faalt duidelijk als de API-key ontbreekt."""
    import anthropic

    key = get_settings().anthropic_api_key
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY ontbreekt in .env")
    return anthropic.Anthropic(api_key=key)
