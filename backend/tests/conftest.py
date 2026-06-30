"""Test-fixtures. Draait tegen een echte Postgres in een container (testcontainers).

Vereist een draaiende Docker-daemon. Zonder Docker worden de DB-tests
overgeslagen met een duidelijke melding (pure unit-tests draaien wel).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

MAIL_TABLES = (
    "mail.tenant_secrets",
    "mail.messages",
    "mail.newsletters",
    "mail.conversations",
    "mail.templates",
    "mail.audit_events",
    "mail.tenants",
)


@pytest.fixture(scope="session")
def pg_engine() -> Iterator[Engine]:
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers niet geinstalleerd")

    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # pragma: no cover - Docker niet beschikbaar
        pytest.skip(f"Docker/Postgres-container niet beschikbaar: {exc}")

    try:
        from app.db.models import Base

        engine = create_engine(container.get_connection_url(), future=True)
        with engine.begin() as conn:
            conn.execute(text("create schema if not exists mail"))
        Base.metadata.create_all(engine)
        yield engine
    finally:
        container.stop()


@pytest.fixture
def session(pg_engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False, class_=Session)
    with factory() as s:
        yield s
    # Schoon tussen tests: alle mail-tabellen leegmaken.
    with pg_engine.begin() as conn:
        conn.execute(text(f"truncate {', '.join(MAIL_TABLES)} restart identity cascade"))


@pytest.fixture
def cipher():
    from cryptography.fernet import Fernet

    from app.services.crypto import SecretCipher

    return SecretCipher(Fernet.generate_key().decode())


@pytest.fixture
def client(session: Session, cipher) -> Iterator:
    from fastapi.testclient import TestClient

    from app.deps import get_cipher
    from app.db.session import get_session
    from app.main import app

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_cipher] = lambda: cipher
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
