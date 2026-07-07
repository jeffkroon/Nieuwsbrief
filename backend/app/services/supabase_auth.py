"""Supabase Auth-integratie: token-verificatie (JWKS) en gebruikers uitnodigen.

Supabase beantwoordt alleen "wie ben je?" (identiteit, wachtwoorden, mails);
de autorisatie (welk bedrijf mag deze gebruiker zien) blijft in onze eigen
mail.users-tabel en sessie-laag. Verificatie gebeurt asymmetrisch tegen het
JWKS-endpoint van het project (aanbevolen door Supabase; geen gedeeld secret).
"""

from __future__ import annotations

import uuid

import httpx
import jwt
from jwt import PyJWKClient

# Supabase raadt aan JWKS-sleutels maximaal ~10 minuten te cachen (rotatie).
_JWKS_CACHE_SECONDS = 600


class SupabaseAuthError(Exception):
    """Nette fout richting de gebruiker (ongeldig token, uitnodiging mislukt)."""


class SupabaseAuth:
    """Dun laagje om het Supabase Auth-REST-API heen (injecteerbaar in tests)."""

    def __init__(
        self,
        supabase_url: str,
        service_role_key: str | None = None,
        *,
        jwk_client: PyJWKClient | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base = supabase_url.rstrip("/")
        self._service_key = service_role_key
        self._jwk_client = jwk_client or PyJWKClient(
            f"{self._base}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=_JWKS_CACHE_SECONDS,
        )
        self._http = http_client

    # -- identiteit -----------------------------------------------------------

    def verify_access_token(self, access_token: str) -> dict:
        """Verifieer een Supabase-access-token; geef {"sub", "email"} terug.

        Checkt handtekening (JWKS), vervaltijd, uitgever en audience. Elke
        afwijking is een SupabaseAuthError met een duidelijke reden.
        """
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(access_token)
            claims = jwt.decode(
                access_token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience="authenticated",
                issuer=f"{self._base}/auth/v1",
                options={"require": ["exp", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise SupabaseAuthError("De sessie is verlopen; log opnieuw in.") from exc
        except jwt.PyJWTError as exc:
            raise SupabaseAuthError(f"Ongeldig login-token: {exc}") from exc
        return {"sub": claims["sub"], "email": claims.get("email", "")}

    # -- beheer (service-role) -------------------------------------------------

    def _admin_headers(self) -> dict:
        if not self._service_key:
            raise SupabaseAuthError("SUPABASE_SERVICE_ROLE_KEY ontbreekt in de omgeving.")
        return {
            "Authorization": f"Bearer {self._service_key}",
            "apikey": self._service_key,
        }

    def _post(self, path: str, payload: dict) -> httpx.Response:
        url = f"{self._base}{path}"
        try:
            if self._http is not None:
                return self._http.post(url, json=payload, headers=self._admin_headers())
            with httpx.Client(timeout=20.0) as client:
                return client.post(url, json=payload, headers=self._admin_headers())
        except httpx.HTTPError as exc:
            raise SupabaseAuthError(f"Supabase niet bereikbaar: {exc}") from exc

    def invite_user(self, email: str, *, redirect_to: str) -> uuid.UUID:
        """Stuur een uitnodigingsmail; geef het aangemaakte auth-user-id terug."""
        resp = self._post(
            "/auth/v1/invite", {"email": email, "options": {"redirect_to": redirect_to}}
        )
        if resp.status_code not in (200, 201):
            detail = ""
            try:
                body = resp.json()
                detail = body.get("msg") or body.get("message") or body.get("error_description") or ""
            except ValueError:
                pass
            raise SupabaseAuthError(
                f"Uitnodigen mislukt (status {resp.status_code}){': ' + detail if detail else ''}"
            )
        data = resp.json()
        try:
            return uuid.UUID(data["id"])
        except (KeyError, ValueError) as exc:
            raise SupabaseAuthError("Supabase gaf geen gebruikers-id terug.") from exc

    def delete_auth_user(self, user_id: uuid.UUID) -> None:
        """Verwijder het Supabase-account (best effort; fouten niet fataal)."""
        url = f"{self._base}/auth/v1/admin/users/{user_id}"
        try:
            if self._http is not None:
                self._http.delete(url, headers=self._admin_headers())
            else:
                with httpx.Client(timeout=20.0) as client:
                    client.delete(url, headers=self._admin_headers())
        except (httpx.HTTPError, SupabaseAuthError):
            pass  # de koppeling in mail.users is al weg; wees-account is onschadelijk

