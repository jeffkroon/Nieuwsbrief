"""Unit-tests voor Settings.database_url-normalisatie (geen DB/Docker nodig)."""

from __future__ import annotations

import pytest

from app.config import Settings

KEY = "x" * 44  # placeholder, niet als Fernet-key gebruikt in deze tests


def _settings(conn: str) -> Settings:
    # _env_file=None: negeer de echte .env, gebruik alleen deze kwargs.
    return Settings(
        _env_file=None, supabase_connection_string=conn, secret_encryption_key=KEY
    )


@pytest.mark.parametrize(
    ("given", "expected_prefix"),
    [
        ("postgresql://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_database_url_normalisation(given: str, expected_prefix: str) -> None:
    assert _settings(given).database_url == expected_prefix


def test_other_scheme_passes_through() -> None:
    # Onbekend schema wordt ongewijzigd doorgegeven (geen stille aanname).
    assert _settings("sqlite:///x.db").database_url == "sqlite:///x.db"
