"""Integratietests voor de Supabase-loginwissel en het klant-accountbeheer.

De Supabase-laag zelf is gemockt (unit-getest in test_supabase_auth.py);
hier gaat het om de koppeling: token -> mail.users -> onze sessie-cookie
met tenant-binding, en de admin-endpoints voor uitnodigen/verwijderen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from app.config import get_settings
from app.deps import SessionInfo, current_session_info, get_supabase_auth
from app.main import app
from app.middleware import session_claims
from app.repositories import tenants as tenants_repo
from app.repositories import users as users_repo
from app.schemas import TenantCreate
from app.services.supabase_auth import SupabaseAuthError


@dataclass
class FakeSupabase:
    """Vervangt SupabaseAuth in de routes: identiteit is hier al 'geverifieerd'."""

    identity: dict | None = None
    verify_error: Exception | None = None
    next_invite_id: uuid.UUID = field(default_factory=uuid.uuid4)
    invited: list = field(default_factory=list)
    deleted: list = field(default_factory=list)

    def verify_access_token(self, access_token: str) -> dict:
        if self.verify_error is not None:
            raise self.verify_error
        assert self.identity is not None
        return self.identity

    def invite_user(self, email: str, *, redirect_to: str) -> uuid.UUID:
        self.invited.append({"email": email, "redirect_to": redirect_to})
        return self.next_invite_id

    def delete_auth_user(self, user_id: uuid.UUID) -> None:
        self.deleted.append(user_id)


@pytest.fixture
def fake_supabase():
    fake = FakeSupabase()
    app.dependency_overrides[get_supabase_auth] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_supabase_auth, None)


@pytest.fixture
def with_lock():
    """Zet het wachtwoord-slot aan (zoals in productie) en herstel na de test."""
    settings = get_settings()
    old_access, old_admin = settings.access_password, settings.admin_password
    settings.access_password, settings.admin_password = "team-wachtwoord", "admin-wachtwoord"
    yield settings
    settings.access_password, settings.admin_password = old_access, old_admin


def _tenant(session, slug: str):
    return tenants_repo.create_tenant(
        session, TenantCreate(slug=slug, name=slug, config={"brand_name": slug})
    )


# -- POST /login/supabase -----------------------------------------------------


def test_known_user_gets_tenant_bound_cookie(client, session, fake_supabase, with_lock) -> None:
    tenant = _tenant(session, f"sb-{uuid.uuid4().hex[:6]}")
    auth_id = uuid.uuid4()
    users_repo.create_user(session, user_id=auth_id, tenant_id=tenant.id, email="klant@bedrijf.nl")
    fake_supabase.identity = {"sub": str(auth_id), "email": "klant@bedrijf.nl"}

    resp = client.post("/login/supabase", json={"access_token": "geldig-token"})

    assert resp.status_code == 200
    cookie = resp.headers.get("set-cookie", "")
    token = cookie.split("nb_session=", 1)[1].split(";", 1)[0]
    assert session_claims(token, "team-wachtwoord") == ("company", str(tenant.id))


def test_unknown_supabase_user_gets_403(client, fake_supabase, with_lock) -> None:
    fake_supabase.identity = {"sub": str(uuid.uuid4()), "email": "vreemd@x.nl"}
    resp = client.post("/login/supabase", json={"access_token": "geldig-token"})
    assert resp.status_code == 403
    assert "niet aan een bedrijf gekoppeld" in resp.json()["detail"]


def test_non_uuid_sub_gets_401_not_500(client, fake_supabase, with_lock) -> None:
    fake_supabase.identity = {"sub": "geen-uuid", "email": "x@y.nl"}
    resp = client.post("/login/supabase", json={"access_token": "geldig-token"})
    assert resp.status_code == 401
    assert "Ongeldig account-id" in resp.json()["detail"]


def test_invalid_token_gets_401(client, fake_supabase, with_lock) -> None:
    fake_supabase.verify_error = SupabaseAuthError("De sessie is verlopen; log opnieuw in.")
    resp = client.post("/login/supabase", json={"access_token": "rot-token"})
    assert resp.status_code == 401
    assert "verlopen" in resp.json()["detail"]


def test_login_supabase_is_rate_limited(client, fake_supabase, with_lock) -> None:
    fake_supabase.verify_error = SupabaseAuthError("Ongeldig login-token")
    for _ in range(5):
        assert client.post("/login/supabase", json={"access_token": "x"}).status_code == 401
    assert client.post("/login/supabase", json={"access_token": "x"}).status_code == 429


def test_scoped_cookie_blocks_other_tenant(client, session, fake_supabase, with_lock) -> None:
    """De hele keten: Supabase-login -> cookie -> bestaande tenant-scheiding."""
    mine = _tenant(session, f"sb-eigen-{uuid.uuid4().hex[:6]}")
    other = _tenant(session, f"sb-ander-{uuid.uuid4().hex[:6]}")
    auth_id = uuid.uuid4()
    users_repo.create_user(session, user_id=auth_id, tenant_id=mine.id, email="k@b.nl")
    fake_supabase.identity = {"sub": str(auth_id), "email": "k@b.nl"}

    resp = client.post("/login/supabase", json={"access_token": "geldig"})
    assert resp.status_code == 200
    # TestClient bewaart de cookie; volgende requests zijn de klant-sessie.
    assert client.get(f"/tenants/{mine.id}").status_code == 200
    assert client.get(f"/tenants/{other.id}").status_code == 403


# -- GET /auth/config ----------------------------------------------------------


def test_auth_config_exposes_url_and_publishable_key(client) -> None:
    settings = get_settings()
    old_url, old_key = settings.supabase_url, settings.supabase_publishable_key
    settings.supabase_url = "https://project.supabase.co"
    settings.supabase_publishable_key = "sb_publishable_x"
    try:
        data = client.get("/auth/config").json()
        assert data == {
            "supabase_url": "https://project.supabase.co",
            "publishable_key": "sb_publishable_x",
        }
    finally:
        settings.supabase_url, settings.supabase_publishable_key = old_url, old_key


# -- klant-accountbeheer (admin-only) ------------------------------------------


def test_admin_invites_lists_and_deletes_user(client, session, fake_supabase) -> None:
    tenant = _tenant(session, f"acc-{uuid.uuid4().hex[:6]}")
    new_id = uuid.uuid4()
    fake_supabase.next_invite_id = new_id

    created = client.post(f"/tenants/{tenant.id}/users", json={"email": "Klant@Bedrijf.nl"})
    assert created.status_code == 201
    assert created.json()["email"] == "klant@bedrijf.nl"  # genormaliseerd
    assert fake_supabase.invited[0]["email"] == "klant@bedrijf.nl"
    assert fake_supabase.invited[0]["redirect_to"].endswith("/welkom")

    listed = client.get(f"/tenants/{tenant.id}/users").json()
    assert [u["email"] for u in listed] == ["klant@bedrijf.nl"]

    resp = client.delete(f"/tenants/{tenant.id}/users/{new_id}")
    assert resp.status_code == 204
    assert fake_supabase.deleted == [new_id]
    assert client.get(f"/tenants/{tenant.id}/users").json() == []


def test_duplicate_email_gives_409(client, session, fake_supabase) -> None:
    tenant = _tenant(session, f"dub-{uuid.uuid4().hex[:6]}")
    users_repo.create_user(
        session, user_id=uuid.uuid4(), tenant_id=tenant.id, email="klant@bedrijf.nl"
    )
    resp = client.post(f"/tenants/{tenant.id}/users", json={"email": "klant@bedrijf.nl"})
    assert resp.status_code == 409
    assert fake_supabase.invited == []  # geen mail gestuurd


def test_invite_race_on_unique_email_gives_409_and_cleans_up(
    client, session, fake_supabase, monkeypatch
) -> None:
    """Twee gelijktijdige invites: de verliezer van de unique-constraint krijgt
    een 409 en het zojuist aangemaakte Supabase-account wordt opgeruimd."""
    from sqlalchemy.exc import IntegrityError

    from app.routes import tenants as tenants_routes

    tenant = _tenant(session, f"race-{uuid.uuid4().hex[:6]}")
    new_id = uuid.uuid4()
    fake_supabase.next_invite_id = new_id

    def lose_the_race(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("unique_violation"))

    monkeypatch.setattr(tenants_routes.users_repo, "create_user", lose_the_race)
    resp = client.post(f"/tenants/{tenant.id}/users", json={"email": "race@b.nl"})
    assert resp.status_code == 409
    assert fake_supabase.deleted == [new_id]  # wees-account opgeruimd


def test_invite_on_unknown_tenant_gives_404(client, fake_supabase) -> None:
    resp = client.post(f"/tenants/{uuid.uuid4()}/users", json={"email": "a@b.nl"})
    assert resp.status_code == 404


def test_user_management_is_admin_only(client, session, fake_supabase) -> None:
    tenant = _tenant(session, f"adm-{uuid.uuid4().hex[:6]}")
    app.dependency_overrides[current_session_info] = lambda: SessionInfo(
        role="company", tenant_id=tenant.id
    )
    try:
        assert client.get(f"/tenants/{tenant.id}/users").status_code == 403
        assert (
            client.post(f"/tenants/{tenant.id}/users", json={"email": "a@b.nl"}).status_code
            == 403
        )
        assert (
            client.delete(f"/tenants/{tenant.id}/users/{uuid.uuid4()}").status_code == 403
        )
    finally:
        app.dependency_overrides.pop(current_session_info, None)


def test_delete_user_checks_tenant_match(client, session, fake_supabase) -> None:
    a = _tenant(session, f"mx-a-{uuid.uuid4().hex[:6]}")
    b = _tenant(session, f"mx-b-{uuid.uuid4().hex[:6]}")
    user = users_repo.create_user(
        session, user_id=uuid.uuid4(), tenant_id=a.id, email="a@b.nl"
    )
    # Verwijderen via het verkeerde bedrijf: 404, gebruiker blijft bestaan.
    assert client.delete(f"/tenants/{b.id}/users/{user.id}").status_code == 404
    assert users_repo.get_user(session, user.id) is not None


# -- repository + cascade --------------------------------------------------------


def test_users_repo_roundtrip_and_cascade(session) -> None:
    tenant = _tenant(session, f"repo-{uuid.uuid4().hex[:6]}")
    uid = uuid.uuid4()
    users_repo.create_user(session, user_id=uid, tenant_id=tenant.id, email="X@Y.nl ")

    fetched = users_repo.get_user_by_email(session, "x@y.nl")
    assert fetched is not None and fetched.id == uid
    assert [u.id for u in users_repo.list_users(session, tenant.id)] == [uid]

    # Bedrijf weg -> gekoppelde accounts weg (on delete cascade).
    tenants_repo.delete_tenant(session, tenant.id)
    session.expire_all()
    assert users_repo.get_user(session, uid) is None
