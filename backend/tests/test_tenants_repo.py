"""Integratietests voor de tenant- en secret-repositories (echte Postgres)."""

from __future__ import annotations

import uuid

import pytest

from app.repositories import secrets as secrets_repo
from app.repositories import tenants as repo
from app.schemas import TenantCreate, TenantUpdate


def _create(session, slug="voetbalreizenxl") -> object:
    return repo.create_tenant(
        session,
        TenantCreate(slug=slug, name="VoetbalreizenXL", config={"primary_color": "#FF7200"}),
    )


def test_create_and_get_by_id(session) -> None:
    tenant = _create(session)
    assert tenant.id is not None
    fetched = repo.get_tenant(session, tenant.id)
    assert fetched is not None
    assert fetched.slug == "voetbalreizenxl"
    assert fetched.config["primary_color"] == "#FF7200"
    assert fetched.status == "active"


def test_get_by_slug(session) -> None:
    _create(session)
    assert repo.get_tenant_by_slug(session, "voetbalreizenxl") is not None
    assert repo.get_tenant_by_slug(session, "bestaat-niet") is None


def test_list_is_ordered(session) -> None:
    _create(session, "zztop")
    _create(session, "ajax")
    slugs = [t.slug for t in repo.list_tenants(session)]
    assert slugs == ["ajax", "zztop"]


def test_update_partial(session) -> None:
    tenant = _create(session)
    updated = repo.update_tenant(session, tenant.id, TenantUpdate(name="Nieuwe naam"))
    assert updated is not None
    assert updated.name == "Nieuwe naam"
    assert updated.slug == "voetbalreizenxl"  # ongewijzigd


def test_update_missing_returns_none(session) -> None:
    assert repo.update_tenant(session, uuid.uuid4(), TenantUpdate(name="x")) is None


def test_delete(session) -> None:
    tenant = _create(session)
    assert repo.delete_tenant(session, tenant.id) is True
    assert repo.get_tenant(session, tenant.id) is None
    assert repo.delete_tenant(session, tenant.id) is False


def test_secret_set_get_roundtrip(session, cipher) -> None:
    tenant = _create(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim")
    got = secrets_repo.get_tenant_secret(session, cipher, tenant.id, "brevo_api_key")
    assert got == "xkeysib-geheim"


def test_secret_is_stored_encrypted(session, cipher) -> None:
    tenant = _create(session)
    secret = secrets_repo.set_tenant_secret(
        session, cipher, tenant.id, "brevo_api_key", "xkeysib-geheim"
    )
    assert "xkeysib-geheim" not in secret.value_encrypted


def test_secret_upsert_overwrites(session, cipher) -> None:
    tenant = _create(session)
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "oud")
    secrets_repo.set_tenant_secret(session, cipher, tenant.id, "brevo_api_key", "nieuw")
    assert secrets_repo.get_tenant_secret(session, cipher, tenant.id, "brevo_api_key") == "nieuw"


def test_missing_secret_returns_none(session, cipher) -> None:
    tenant = _create(session)
    assert secrets_repo.get_tenant_secret(session, cipher, tenant.id, "brevo_api_key") is None
