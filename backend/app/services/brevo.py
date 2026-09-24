"""Brevo-client die uitsluitend concepten (drafts) aanmaakt en bijwerkt.

Veiligheid by design: deze klasse heeft GEEN methode om te verzenden, te plannen
of de status te wijzigen. Bijwerken (PUT) gebeurt alleen na een statuscheck: een
campagne die niet meer 'draft' is wordt nooit aangeraakt. Er wordt nooit `scheduledAt` meegestuurd en
`/sendNow` of `/status` worden nooit aangeroepen. Een campagne aangemaakt via
POST /emailCampaigns zonder `scheduledAt` blijft draft tot een mens 'm in Brevo
handmatig verstuurt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.services.esp import (
    DRAFT,
    OTHER,
    SENDING,
    SENT,
    CampaignNotFound,
    CampaignResults,
    as_int,
    rate,
    sum_known,
)

BREVO_BASE_URL = "https://api.brevo.com/v3"
HTML_MIN_BYTES = 10
HTML_MAX_BYTES = 1_000_000  # Brevo-limiet: 1 MB
# Brevo-statussen (GET /emailCampaigns/{id}) naar onze genormaliseerde status.
# 'scheduled' bestaat niet in Brevo's lijst; ingeplande campagnes zijn 'queued'.
_STATUS = {
    "draft": DRAFT,
    "sent": SENT,
    "archive": SENT,
    "queued": SENDING,
    "in_process": SENDING,
}


class BrevoError(Exception):
    """Brevo gaf een fout terug of het verzoek kon niet worden afgerond."""


@dataclass(frozen=True)
class BrevoDraft:
    campaign_id: int


class BrevoClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BREVO_BASE_URL,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("BREVO_API_KEY ontbreekt voor deze tenant")
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
        list_ids: list[int] | None = None,
        preview_text: str | None = None,
        reply_to: str | None = None,
    ) -> BrevoDraft:
        """Maak een concept-campagne aan. Verstuurt niets."""
        _check_html(html)

        payload: dict[str, Any] = {
            "name": name,
            "subject": subject,
            "sender": {"name": sender_name, "email": sender_email},
            "type": "classic",
            "htmlContent": html,
            # Bewust GEEN scheduledAt: campagne blijft draft.
        }
        if preview_text:
            payload["previewText"] = preview_text
        if reply_to:
            payload["replyTo"] = reply_to
        if list_ids:
            payload["recipients"] = {"listIds": list_ids}

        body = self._request("POST", "/emailCampaigns", payload, expect=201)
        campaign_id = body.get("id")
        if not isinstance(campaign_id, int):
            raise BrevoError(f"Onverwacht antwoord van Brevo: {body!r}")
        return BrevoDraft(campaign_id=campaign_id)

    def get_lists(self) -> list[dict]:
        """Alle contactenlijsten (id + naam) ophalen, voor de lijst-kiezer. Alleen-lezen."""
        headers = {"api-key": self._api_key, "Accept": "application/json"}
        url = f"{self._base_url}/contacts/lists?limit=50"
        try:
            if self._client is not None:
                response = self._client.get(url, headers=headers)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise BrevoError(f"Brevo-verzoek mislukt: {exc}") from exc
        if response.status_code != 200:
            raise BrevoError(f"Brevo gaf HTTP {response.status_code}: {response.text}")
        return [
            {"id": row.get("id"), "name": row.get("name") or str(row.get("id"))}
            for row in response.json().get("lists", [])
        ]

    def get_campaign_status(self, campaign_id: int) -> str:
        """Genormaliseerde status (draft/sending/sent/other). Alleen-lezen."""
        body = self._request("GET", f"/emailCampaigns/{int(campaign_id)}", expect=200)
        return _STATUS.get(str(body.get("status")), OTHER)

    def update_draft(
        self,
        campaign_id: int,
        *,
        subject: str,
        sender_name: str,
        sender_email: str,
        html: str,
        preview_text: str | None = None,
    ) -> None:
        """Werk een bestaand CONCEPT bij (PUT, 204). Weigert alles wat geen draft is.

        Naam en ontvangers blijven ongemoeid: die kan de klant in Brevo zelf hebben
        aangepast. Brevo staat PUT ook toe op ingeplande campagnes; wij niet.
        """
        _check_html(html)
        status = self.get_campaign_status(campaign_id)
        if status != DRAFT:
            raise BrevoError(f"campagne {campaign_id} is geen concept meer (status {status})")
        payload: dict[str, Any] = {
            "subject": subject,
            "sender": {"name": sender_name, "email": sender_email},
            "htmlContent": html,
        }
        if preview_text:
            payload["previewText"] = preview_text
        self._request("PUT", f"/emailCampaigns/{int(campaign_id)}", payload, expect=204)

    def get_results(self, campaign_id: int) -> CampaignResults:
        """Status en resultaten (globalStats). Brevo geeft geen percentages: die rekenen we."""
        body = self._request(
            "GET", f"/emailCampaigns/{int(campaign_id)}?statistics=globalStats", expect=200
        )
        stats = (body.get("statistics") or {}).get("globalStats") or {}
        delivered = as_int(stats.get("delivered"))
        opens = as_int(stats.get("uniqueViews"))
        clicks = as_int(stats.get("uniqueClicks"))
        return CampaignResults(
            status=_STATUS.get(str(body.get("status")), OTHER),
            sent=as_int(stats.get("sent")),
            delivered=delivered,
            opens_unique=opens,
            clicks_unique=clicks,
            unsubscribes=as_int(stats.get("unsubscriptions")),
            bounces=sum_known(as_int(stats.get("hardBounces")), as_int(stats.get("softBounces"))),
            open_rate=rate(opens, delivered),
            click_rate=rate(clicks, delivered),
        )

    # -- intern ------------------------------------------------------------
    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None, *, expect: int
    ) -> dict[str, Any]:
        headers = {"api-key": self._api_key, "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        url = f"{self._base_url}{path}"
        try:
            if self._client is not None:
                response = self._client.request(method, url, json=payload, headers=headers)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(method, url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise BrevoError(f"Brevo-verzoek mislukt: {exc}") from exc

        if response.status_code == 404 and method != "POST":
            raise CampaignNotFound(f"Brevo kent campagne {path} niet (meer)")
        if response.status_code != expect:
            raise BrevoError(f"Brevo gaf HTTP {response.status_code}: {response.text}")
        # PUT geeft 204 zonder body.
        return response.json() if response.content else {}


def _check_html(html: str) -> None:
    size = len(html.encode("utf-8"))
    if size < HTML_MIN_BYTES:
        raise ValueError("htmlContent is te kort (min 10 bytes)")
    if size > HTML_MAX_BYTES:
        raise ValueError(f"htmlContent te groot ({size} bytes, max {HTML_MAX_BYTES})")
