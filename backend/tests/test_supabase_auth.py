"""Unit-tests voor de Supabase Auth-laag: JWKS-tokenverificatie en admin-calls.

Geen netwerk: het JWKS-client en het http-client zijn injecteerbaar. Tokens
worden ondertekend met een eigen RSA-keypair; de fake JWKS geeft de publieke
sleutel terug, precies zoals PyJWKClient dat zou doen.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.supabase_auth import SupabaseAuth, SupabaseAuthError

SUPABASE_URL = "https://project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"


@dataclass
class _FakeSigningKey:
    key: object


@dataclass
class _FakeJWKClient:
    """Doet wat PyJWKClient doet: geef de (publieke) sleutel voor een token."""

    public_key: object

    def get_signing_key_from_jwt(self, token: str) -> _FakeSigningKey:
        return _FakeSigningKey(key=self.public_key)


@pytest.fixture(scope="module")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def _make_token(private_key, **overrides) -> str:
    claims = {
        "sub": str(uuid.uuid4()),
        "email": "klant@bedrijf.nl",
        "aud": "authenticated",
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm="RS256")


def _auth(public_key, **kwargs) -> SupabaseAuth:
    return SupabaseAuth(
        SUPABASE_URL, jwk_client=_FakeJWKClient(public_key), **kwargs
    )


def test_valid_token_returns_sub_and_email(keypair) -> None:
    private, public = keypair
    sub = str(uuid.uuid4())
    token = _make_token(private, sub=sub)
    assert _auth(public).verify_access_token(token) == {
        "sub": sub,
        "email": "klant@bedrijf.nl",
    }


def test_expired_token_gives_friendly_error(keypair) -> None:
    private, public = keypair
    token = _make_token(private, exp=int(time.time()) - 10)
    with pytest.raises(SupabaseAuthError, match="verlopen"):
        _auth(public).verify_access_token(token)


def test_wrong_signature_rejected(keypair) -> None:
    _, public = keypair
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_token(other)  # ondertekend met een ANDERE sleutel
    with pytest.raises(SupabaseAuthError, match="Ongeldig"):
        _auth(public).verify_access_token(token)


def test_wrong_audience_rejected(keypair) -> None:
    private, public = keypair
    token = _make_token(private, aud="anon")
    with pytest.raises(SupabaseAuthError, match="Ongeldig"):
        _auth(public).verify_access_token(token)


def test_wrong_issuer_rejected(keypair) -> None:
    private, public = keypair
    token = _make_token(private, iss="https://kwaadaardig.example/auth/v1")
    with pytest.raises(SupabaseAuthError, match="Ongeldig"):
        _auth(public).verify_access_token(token)


def test_missing_sub_rejected(keypair) -> None:
    private, public = keypair
    token = _make_token(private, sub=None)
    with pytest.raises(SupabaseAuthError, match="Ongeldig"):
        _auth(public).verify_access_token(token)


# -- admin-calls (invite/delete) via gemockt http-client --------------------


@dataclass
class _FakeHttp:
    """Minimale httpx.Client-vervanger die vaste responses teruggeeft."""

    response: httpx.Response
    posts: list = field(default_factory=list)
    deletes: list = field(default_factory=list)

    def post(self, url, *, json=None, headers=None) -> httpx.Response:
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self.response

    def delete(self, url, *, headers=None) -> httpx.Response:
        self.deletes.append({"url": url, "headers": headers})
        return self.response


def test_invite_user_returns_auth_user_id(keypair) -> None:
    _, public = keypair
    new_id = uuid.uuid4()
    http = _FakeHttp(httpx.Response(200, json={"id": str(new_id)}))
    auth = _auth(public, service_role_key="service-key", http_client=http)

    result = auth.invite_user("klant@bedrijf.nl", redirect_to="https://app/welkom")

    assert result == new_id
    call = http.posts[0]
    assert call["url"] == f"{SUPABASE_URL}/auth/v1/invite"
    assert call["json"]["email"] == "klant@bedrijf.nl"
    assert call["headers"]["Authorization"] == "Bearer service-key"
    assert call["headers"]["apikey"] == "service-key"


def test_invite_user_surfaces_supabase_error(keypair) -> None:
    _, public = keypair
    http = _FakeHttp(httpx.Response(422, json={"msg": "email bestaat al"}))
    auth = _auth(public, service_role_key="service-key", http_client=http)
    with pytest.raises(SupabaseAuthError, match="email bestaat al"):
        auth.invite_user("klant@bedrijf.nl", redirect_to="https://app/welkom")


def test_invite_without_service_key_fails_clearly(keypair) -> None:
    _, public = keypair
    auth = _auth(public)  # geen service-role-key
    with pytest.raises(SupabaseAuthError, match="SUPABASE_SERVICE_ROLE_KEY"):
        auth.invite_user("klant@bedrijf.nl", redirect_to="https://app/welkom")


def test_generate_invite_link_returns_id_and_link(keypair) -> None:
    _, public = keypair
    new_id = uuid.uuid4()
    http = _FakeHttp(httpx.Response(200, json={
        "id": str(new_id),
        "action_link": "https://project.supabase.co/auth/v1/verify?token=x&type=invite",
    }))
    auth = _auth(public, service_role_key="service-key", http_client=http)

    user_id, link = auth.generate_invite_link("klant@bedrijf.nl", redirect_to="https://app/welkom")

    assert user_id == new_id
    assert link.startswith("https://project.supabase.co/auth/v1/verify")
    call = http.posts[0]
    assert call["url"] == f"{SUPABASE_URL}/auth/v1/admin/generate_link"
    assert call["json"] == {
        "type": "invite",
        "email": "klant@bedrijf.nl",
        "redirect_to": "https://app/welkom",
    }


def test_generate_invite_link_surfaces_errors(keypair) -> None:
    _, public = keypair
    http = _FakeHttp(httpx.Response(422, json={"msg": "email bestaat al"}))
    auth = _auth(public, service_role_key="service-key", http_client=http)
    with pytest.raises(SupabaseAuthError, match="email bestaat al"):
        auth.generate_invite_link("klant@bedrijf.nl", redirect_to="https://app/welkom")

    # Antwoord zonder link is ook een nette fout.
    http2 = _FakeHttp(httpx.Response(200, json={"id": str(uuid.uuid4())}))
    auth2 = _auth(public, service_role_key="service-key", http_client=http2)
    with pytest.raises(SupabaseAuthError, match="geen uitnodigingslink"):
        auth2.generate_invite_link("klant@bedrijf.nl", redirect_to="https://app/welkom")


def test_delete_auth_user_is_best_effort(keypair) -> None:
    _, public = keypair
    http = _FakeHttp(httpx.Response(500, json={}))
    auth = _auth(public, service_role_key="service-key", http_client=http)
    auth.delete_auth_user(uuid.uuid4())  # mag nooit een exception gooien
    assert len(http.deletes) == 1

    # Zelfs zonder service-key: stil overslaan (koppeling is al weg).
    _auth(public).delete_auth_user(uuid.uuid4())
