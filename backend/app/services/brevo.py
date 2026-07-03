"""Brevo-client die uitsluitend concepten (drafts) aanmaakt.

Veiligheid by design: deze klasse heeft GEEN methode om te verzenden, te plannen
of de status te wijzigen. Er wordt nooit `scheduledAt` meegestuurd en
`/sendNow` of `/status` worden nooit aangeroepen. Een campagne aangemaakt via
POST /emailCampaigns zonder `scheduledAt` blijft draft tot een mens 'm in Brevo
handmatig verstuurt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

BREVO_BASE_URL = "https://api.brevo.com/v3"
HTML_MIN_BYTES = 10
HTML_MAX_BYTES = 1_000_000  # Brevo-limiet: 1 MB


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
        size = len(html.encode("utf-8"))
        if size < HTML_MIN_BYTES:
            raise ValueError("htmlContent is te kort (min 10 bytes)")
        if size > HTML_MAX_BYTES:
            raise ValueError(f"htmlContent te groot ({size} bytes, max {HTML_MAX_BYTES})")

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

        body = self._post("/emailCampaigns", payload)
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

    # -- intern ------------------------------------------------------------
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"api-key": self._api_key, "Content-Type": "application/json"}
        url = f"{self._base_url}{path}"
        try:
            if self._client is not None:
                response = self._client.post(url, json=payload, headers=headers)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise BrevoError(f"Brevo-verzoek mislukt: {exc}") from exc

        if response.status_code != 201:
            raise BrevoError(f"Brevo gaf HTTP {response.status_code}: {response.text}")
        return response.json()
