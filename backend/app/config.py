"""Applicatie-configuratie, gevalideerd aan de systeemgrens.

Leest uit de repo-root `.env`. Secrets (DB-string, encryptie-key) worden hier
gevalideerd; ontbreken ze, dan faalt de app bij opstarten met een duidelijke fout.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py -> app -> backend -> repo-root
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    supabase_connection_string: str
    secret_encryption_key: str
    brevo_api_key: str | None = None
    anthropic_api_key: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    # Publieke (anon/publishable) key: mag in de frontend, nodig voor klant-login.
    supabase_publishable_key: str | None = None
    images_bucket: str = "tenant-images"
    # Optioneel wachtwoord-slot (sessie-cookie). Leeg = geen slot (lokaal/dev).
    access_user: str = "dunion"
    access_password: str | None = None
    # Apart admin-wachtwoord: hiermee inloggen geeft de 'admin'-rol (Dunion), die
    # template-layouts mag beheren. Leeg = geen aparte admin (alleen 'company').
    admin_user: str = "dunion"
    admin_password: str | None = None

    @property
    def database_url(self) -> str:
        """Normaliseer naar de psycopg3-driver voor SQLAlchemy."""
        url = self.supabase_connection_string
        if url.startswith("postgresql+"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
