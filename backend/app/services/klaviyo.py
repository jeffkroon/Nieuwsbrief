"""Klaviyo-client die uitsluitend concepten (drafts) aanmaakt.

Veiligheid by design: deze klasse heeft GEEN methode om te verzenden of te plannen.
Verzenden kan bij Klaviyo alleen via een apart send-job-endpoint dat hier bewust
niet bestaat; een campagne blijft na aanmaken in status Draft tot een mens 'm in
het Klaviyo-dashboard controleert en verstuurt.

Flow (Klaviyo klassieke Campaigns API, revision gepind):
1. POST /api/templates            (eigen HTML, editor_type CODE)
2. POST /api/campaigns            (draft; audience verplicht en niet leeg)
3. POST /api/campaign-message-assign-template (kloont de template aan het bericht)
4. DELETE /api/templates/{id}     (best effort: herbruikbare template opruimen,
                                   accounts hebben een limiet van 1.000 templates;
                                   de kloon aan de campagne blijft bestaan)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

KLAVIYO_BASE_URL = "https://a.klaviyo.com"
# Gepind op de klassieke Campaigns API-vorm; per Klaviyo's deprecation-beleid blijft
# deze revision tot ~2028 werken. Niet blind verhogen: de nieuwe "omni"-API heeft een
# andere request-structuur.
KLAVIYO_REVISION = "2026-04-15"
HTML_MIN_BYTES = 10
# Geen gedocumenteerde API-limiet; boven ~102 KB knipt Gmail de mail af.
HTML_WARN_BYTES = 102_400
UNSUBSCRIBE_TAGS = ("{% unsubscribe %}", "unsubscribe_link")


class KlaviyoError(Exception):
    """Klaviyo gaf een fout terug of het verzoek kon niet worden afgerond."""


@dataclass(frozen=True)
class KlaviyoDraft:
    campaign_id: str  # Klaviyo-ids zijn strings (anders dan Brevo's ints)
    message_id: str


class KlaviyoClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = KLAVIYO_BASE_URL,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("KLAVIYO_API_KEY ontbreekt voor deze tenant")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client  # injecteerbaar voor tests

    def create_draft(
        self,
        *,
        name: str,
        subject: str,
        sender_name: str,
        sender_email: str,
        html: str,
        list_ids: list | None = None,
        preview_text: str | None = None,
        reply_to: str | None = None,
    ) -> KlaviyoDraft:
        """Maak een concept-campagne aan in Klaviyo. Verstuurt niets."""
        if len(html.encode("utf-8")) < HTML_MIN_BYTES:
            raise ValueError("html is te kort")
        if not list_ids:
            raise ValueError(
                "Klaviyo vereist een audience: stel 'klaviyo_list_id' in voor dit bedrijf"
            )
        if not any(tag in html for tag in UNSUBSCRIBE_TAGS):
            # Zonder afmeldlink kan een mens de campagne in het dashboard niet eens
            # inplannen; hard afdwingen in code.
            raise ValueError(
                "Klaviyo vereist een afmeldlink in de template: voeg {% unsubscribe %} toe"
            )

        template_id = self._create_template(name, html)
        try:
            campaign_id, message_id = self._create_campaign(
                name=name, subject=subject, sender_name=sender_name,
                sender_email=sender_email, list_ids=[str(i) for i in list_ids],
                preview_text=preview_text, reply_to=reply_to,
            )
        except Exception:
            self._delete_silent(f"/api/templates/{template_id}")
            raise
        try:
            self._assign_template(message_id, template_id)
        except Exception:
            # Wees-campagne en wees-template best-effort opruimen.
            self._delete_silent(f"/api/campaigns/{campaign_id}")
            self._delete_silent(f"/api/templates/{template_id}")
            raise
        # Herbruikbare template opruimen (de kloon aan het bericht blijft bestaan).
        self._delete_silent(f"/api/templates/{template_id}")
        return KlaviyoDraft(campaign_id=campaign_id, message_id=message_id)

    # -- stappen -------------------------------------------------------------
    def _create_template(self, name: str, html: str) -> str:
        body = self._request(
            "POST",
            "/api/templates",
            {"data": {"type": "template", "attributes": {
                "name": name, "editor_type": "CODE", "html": html,
            }}},
            expect=(201,),
        )
        template_id = (body.get("data") or {}).get("id")
        if not isinstance(template_id, str) or not template_id:
            raise KlaviyoError(f"Onverwacht template-antwoord van Klaviyo: {body!r}")
        return template_id

    def _create_campaign(
        self, *, name: str, subject: str, sender_name: str, sender_email: str,
        list_ids: list[str], preview_text: str | None, reply_to: str | None,
    ) -> tuple[str, str]:
        content: dict[str, Any] = {
            "subject": subject,
            "from_email": sender_email,
            "from_label": sender_name,
            "reply_to_email": reply_to or sender_email,
        }
        if preview_text:
            content["preview_text"] = preview_text
        payload = {"data": {"type": "campaign", "attributes": {
            "name": name,
            "audiences": {"included": list_ids},
            # Bewust GEEN send_strategy/send_options: campagne blijft Draft.
            "campaign-messages": {"data": [{
                "type": "campaign-message",
                "attributes": {"definition": {
                    "channel": "email", "label": "Nieuwsbrief", "content": content,
                }},
            }]},
        }}}
        body = self._request("POST", "/api/campaigns", payload, expect=(201,))
        data = body.get("data") or {}
        campaign_id = data.get("id")
        try:
            message_id = data["relationships"]["campaign-messages"]["data"][0]["id"]
        except (KeyError, IndexError, TypeError):
            message_id = None
        if not isinstance(campaign_id, str) or not isinstance(message_id, str):
            raise KlaviyoError(f"Onverwacht campagne-antwoord van Klaviyo: {body!r}")
        return campaign_id, message_id

    def _assign_template(self, message_id: str, template_id: str) -> None:
        self._request(
            "POST",
            "/api/campaign-message-assign-template",
            {"data": {"type": "campaign-message", "id": message_id, "relationships": {
                "template": {"data": {"type": "template", "id": template_id}},
            }}},
            expect=(200,),
        )

    # -- intern ---------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Klaviyo-API-Key {self._api_key}",
            "revision": KLAVIYO_REVISION,
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
        }

    def _request(
        self, method: str, path: str, payload: dict | None = None,
        expect: tuple[int, ...] = (200, 201), _retried: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            if self._client is not None:
                response = self._client.request(method, url, json=payload, headers=self._headers())
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(method, url, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise KlaviyoError(f"Klaviyo-verzoek mislukt: {exc}") from exc

        if response.status_code == 429 and not _retried:
            retry_after = min(float(response.headers.get("Retry-After", "2") or 2), 15.0)
            time.sleep(retry_after)
            return self._request(method, path, payload, expect, _retried=True)
        if response.status_code not in expect:
            raise KlaviyoError(
                f"Klaviyo gaf HTTP {response.status_code}: {self._error_detail(response)}"
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            errors = response.json().get("errors") or []
            if errors and isinstance(errors[0], dict):
                return errors[0].get("detail") or errors[0].get("title") or response.text
        except ValueError:
            pass
        return response.text

    def _delete_silent(self, path: str) -> None:
        try:
            self._request("DELETE", path, None, expect=(200, 202, 204))
        except KlaviyoError:
            pass  # best effort; nooit de hoofd-flow laten falen op opruimen
