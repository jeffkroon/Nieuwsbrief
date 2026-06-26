"""FastAPI-dependencies: database-sessie en secret-cipher."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.db.session import get_session  # noqa: F401  (re-export als dependency)
from app.services.crypto import SecretCipher


@lru_cache
def get_cipher() -> SecretCipher:
    return SecretCipher(get_settings().secret_encryption_key)


@lru_cache
def get_anthropic_client():
    """Bouwt de Anthropic-client. Faalt duidelijk als de API-key ontbreekt."""
    import anthropic

    key = get_settings().anthropic_api_key
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY ontbreekt in .env")
    return anthropic.Anthropic(api_key=key)
