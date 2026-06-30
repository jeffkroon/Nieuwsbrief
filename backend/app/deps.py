"""FastAPI-dependencies: database-sessie en secret-cipher."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.db.session import get_session  # noqa: F401  (re-export als dependency)
from app.middleware import COOKIE_NAME, session_role
from app.services.crypto import SecretCipher


def current_role(request: Request, settings: Settings = Depends(get_settings)) -> str:
    """Rol van de huidige sessie. Zonder slot (lokaal/dev) is iedereen admin."""
    if not settings.access_password:
        return "admin"
    return session_role(request.cookies.get(COOKIE_NAME), settings.access_password) or "company"


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
