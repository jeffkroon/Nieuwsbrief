"""Tests voor per-bedrijf scheiding: token-claims, wachtwoorden en route-toegang."""

from __future__ import annotations

import uuid

import pytest

from app.config import get_settings
from app.deps import current_session_info
from app.main import app
from app.middleware import make_session_token, session_claims
from app.repositories import tenants as tenants_repo
from app.schemas import TenantCreate
from app.services.passwords import hash_password, verify_password

SECRET = "test-secret"


def test_token_carries_tenant_binding() -> None:
    tid = str(uuid.uuid4())
    role, tenant = session_claims(make_session_token(SECRET, "company", tid), SECRET)
    assert (role, tenant) == ("company", tid)
    # Ongebonden token (admin/team) heeft geen tenant.
    assert session_claims(make_session_token(SECRET, "admin"), SECRET) == ("admin", None)


def test_old_token_format_still_valid_as_unbound() -> None:
    import hashlib as h
    import hmac as hm
    import time

    payload = f"company:{int(time.time())}"  # oud formaat zonder tenant
    sig = hm.new(SECRET.encode(), payload.encode(), h.sha256).hexdigest()
    assert session_claims(f"{payload}.{sig}", SECRET) == ("company", None)


def test_password_hash_roundtrip() -> None:
    stored = hash_password("geheim-wachtwoord")
    assert verify_password("geheim-wachtwoord", stored)
    assert not verify_password("fout", stored)
    assert not verify_password("geheim-wachtwoord", None)
    assert not verify_password("geheim-wachtwoord", "kapotte$opslag")
    with pytest.raises(ValueError):
        hash_password("kort")


def _tenant(session, slug: str):
    return tenants_repo.create_tenant(
        session,
        TenantCreate(slug=slug, name=slug, config={"brand_name": slug}),
    )


@pytest.fixture
def as_company_of():
    """Override de sessie-info naar een klant-login voor een gegeven tenant."""
    from app.deps import SessionInfo

    def install(tenant_id):
        app.dependency_overrides[current_session_info] = lambda: SessionInfo(
            role="company", tenant_id=tenant_id
        )

    yield install
    app.dependency_overrides.pop(current_session_info, None)


def test_scoped_session_cannot_touch_other_tenant(client, session, as_company_of) -> None:
    mine = _tenant(session, f"eigen-{uuid.uuid4().hex[:6]}")
    other = _tenant(session, f"ander-{uuid.uuid4().hex[:6]}")
    as_company_of(mine.id)

    # Eigen bedrijf: mag.
    assert client.get(f"/tenants/{mine.id}").status_code == 200
    assert client.get(f"/tenants/{mine.id}/templates").status_code == 200
    # Andermans bedrijf: 403 op detail, templates en chat.
    assert client.get(f"/tenants/{other.id}").status_code == 403
    assert client.get(f"/tenants/{other.id}/templates").status_code == 403
    start = client.post(
        "/conversations", json={"tenant_id": str(other.id), "message": "hoi"}
    )
    assert start.status_code == 403
    # De bedrijvenlijst toont alleen het eigen bedrijf.
    listed = client.get("/tenants").json()
    assert [t["slug"] for t in listed] == [mine.slug]


def test_unbound_team_session_sees_everything(client, session) -> None:
    a = _tenant(session, f"team-a-{uuid.uuid4().hex[:6]}")
    b = _tenant(session, f"team-b-{uuid.uuid4().hex[:6]}")
    # Default in tests: geen slot -> admin; beide bedrijven zichtbaar.
    slugs = {t["slug"] for t in client.get("/tenants").json()}
    assert {a.slug, b.slug} <= slugs
    assert client.get(f"/tenants/{b.id}").status_code == 200


def test_admin_sets_password_and_client_logs_in(client, session) -> None:
    tenant = _tenant(session, f"login-{uuid.uuid4().hex[:6]}")
    resp = client.post(f"/tenants/{tenant.id}/password", json={"password": "SuperGeheim1"})
    assert resp.status_code == 204
    session.expire_all()
    stored = tenants_repo.get_tenant(session, tenant.id).password_hash
    assert stored and stored.startswith("pbkdf2$")
    assert verify_password("SuperGeheim1", stored)

    # Login-flow: met slot aan logt de klant in met bedrijfscode + wachtwoord
    # en krijgt een tenant-gebonden cookie.
    settings = get_settings()
    old_access, old_admin = settings.access_password, settings.admin_password
    settings.access_password, settings.admin_password = "team-wachtwoord", "admin-wachtwoord"
    try:
        resp = client.post(
            "/login",
            data={"username": tenant.slug, "password": "SuperGeheim1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303 and resp.headers["location"] == "/"
        cookie = resp.headers.get("set-cookie", "")
        token = cookie.split("nb_session=", 1)[1].split(";", 1)[0]
        role, bound = session_claims(token, "team-wachtwoord")
        assert role == "company" and bound == str(tenant.id)

        # Fout wachtwoord: terug naar login met fout.
        resp = client.post(
            "/login",
            data={"username": tenant.slug, "password": "FoutWachtwoord"},
            follow_redirects=False,
        )
        assert "error=1" in resp.headers["location"]
    finally:
        settings.access_password, settings.admin_password = old_access, old_admin


def test_password_endpoint_requires_admin(client, session) -> None:
    from app.deps import SessionInfo

    tenant = _tenant(session, f"pwadmin-{uuid.uuid4().hex[:6]}")
    app.dependency_overrides[current_session_info] = lambda: SessionInfo(role="company")
    try:
        resp = client.post(f"/tenants/{tenant.id}/password", json={"password": "SuperGeheim1"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(current_session_info, None)
