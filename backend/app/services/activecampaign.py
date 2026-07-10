"""ActiveCampaign-client die uitsluitend concepten (drafts) aanmaakt.

Veiligheid by design: deze klasse heeft GEEN methode om te verzenden of te
plannen. Campagnes worden aangemaakt met status 0 (concept) en blijven staan
tot een mens ze in het ActiveCampaign-dashboard controleert en verstuurt.

Flow (v1-API voor het schrijven; de v3-API kan campagne-inhoud niet zetten):
1. POST admin/api.php?api_action=message_add   (onderwerp, afzender, HTML, lijst)
2. POST admin/api.php?api_action=campaign_create (type single, status 0 = concept,
   lijst + message gekoppeld)
Lijsten ophalen gaat wel via de nette v3-API (GET /api/3/lists).

ActiveCampaign heeft een account-specifieke API-URL (https://<account>.api-us1.com);
die is niet geheim en staat in de tenant-config. De API-key is wel geheim en staat
in de versleutelde opslag. Dezelfde key werkt voor v1 en v3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

HTML_MIN_BYTES = 10
# Geen gedocumenteerde API-limiet; boven ~102 KB knipt Gmail de mail af.
HTML_WARN_BYTES = 102_400


class ActiveCampaignError(Exception):
    """ActiveCampaign gaf een fout terug of het verzoek kon niet worden afgerond."""


@dataclass(frozen=True)
class ActiveCampaignDraft:
    campaign_id: str
    message_id: str


def _text_fallback(html: str) -> str:
    """Kale tekstversie voor mailclients zonder HTML (message_add vereist 'text')."""
    text = re.sub(r"(?is)<(style|script).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:20000]


class ActiveCampaignClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("ACTIVECAMPAIGN API-key ontbreekt voor deze tenant")
        if not (api_url or "").startswith(("http://", "https://")):
            raise ValueError(
                "ActiveCampaign API-URL ontbreekt of is ongeldig (verwacht "
                "https://<account>.api-us1.com; zie Settings > Developer in ActiveCampaign)"
            )
        self._base = api_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client  # injecteerbaar voor tests

    # -- http ---------------------------------------------------------------

    def _post_v1(self, action: str, data: dict) -> dict:
        """v1-call: form-encoded POST naar admin/api.php; JSON terug."""
        url = f"{self._base}/admin/api.php"
        params = {"api_key": self._api_key, "api_action": action, "api_output": "json"}
        try:
            if self._client is not None:
                resp = self._client.post(url, params=params, data=data)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.post(url, params=params, data=data)
        except httpx.HTTPError as exc:
            raise ActiveCampaignError(f"ActiveCampaign niet bereikbaar: {exc}") from exc
        if resp.status_code != 200:
            raise ActiveCampaignError(
                f"ActiveCampaign {action} gaf status {resp.status_code}"
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise ActiveCampaignError(
                f"ActiveCampaign {action} gaf geen leesbaar antwoord (verkeerde API-URL?)"
            ) from exc
        if str(body.get("result_code")) != "1":
            raise ActiveCampaignError(
                f"ActiveCampaign {action} mislukt: "
                f"{body.get('result_message') or 'onbekende fout'}"
            )
        return body

    def _get_v3(self, path: str, params: dict | None = None) -> dict:
        url = f"{self._base}/api/3/{path.lstrip('/')}"
        headers = {"Api-Token": self._api_key}
        try:
            if self._client is not None:
                resp = self._client.get(url, params=params, headers=headers)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise ActiveCampaignError(f"ActiveCampaign niet bereikbaar: {exc}") from exc
        if resp.status_code != 200:
            raise ActiveCampaignError(
                f"ActiveCampaign gaf status {resp.status_code} op {path} "
                "(klopt de API-key en de API-URL?)"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise ActiveCampaignError("ActiveCampaign gaf geen leesbaar antwoord") from exc

    # -- publiek ------------------------------------------------------------

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
    ) -> ActiveCampaignDraft:
        """Maak een concept-campagne aan (status 0). Verstuurt niets.

        ActiveCampaign vereist een doellijst om een campagne aan te kunnen maken;
        zonder lijst is er een duidelijke fout in plaats van een half concept.
        preview_text (preheader) kent de v1-API niet en wordt genegeerd.
        """
        if not html or len(html.encode()) < HTML_MIN_BYTES:
            raise ActiveCampaignError("lege of veel te korte HTML; geen concept aangemaakt")
        if not list_ids:
            raise ActiveCampaignError(
                "ActiveCampaign vereist een lijst-ID om een campagne aan te maken; "
                "stel de lijst in bij het bedrijf (Bedrijven-tab > Verzendplatform)"
            )

        message_data: dict = {
            "format": "html",
            "subject": subject,
            "fromname": sender_name,
            "fromemail": sender_email,
            "reply2": sender_email,
            "priority": 3,
            "charset": "utf-8",
            "encoding": "quoted-printable",
            "htmlconstructor": "editor",
            "html": html,
            "textconstructor": "editor",
            "text": _text_fallback(html),
        }
        for list_id in list_ids:
            message_data[f"p[{list_id}]"] = list_id
        message = self._post_v1("message_add", message_data)
        message_id = str(message.get("id") or "")
        if not message_id:
            raise ActiveCampaignError("ActiveCampaign gaf geen message-id terug")

        campaign_data: dict = {
            "type": "single",
            "name": name,
            "status": 0,  # 0 = concept: een mens controleert en verstuurt handmatig
            "public": 0,
            # sdate is verplicht in de API maar wordt bij status 0 niet gebruikt;
            # ruim vooruit zetten voorkomt elke kans op onbedoeld inplannen.
            "sdate": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S"),
            "tracklinks": "all",
            f"m[{message_id}]": 100,  # 100% van de ontvangers krijgt dit bericht
        }
        for list_id in list_ids:
            campaign_data[f"p[{list_id}]"] = list_id
        campaign = self._post_v1("campaign_create", campaign_data)
        campaign_id = str(campaign.get("id") or "")
        if not campaign_id:
            raise ActiveCampaignError("ActiveCampaign gaf geen campagne-id terug")
        return ActiveCampaignDraft(campaign_id=campaign_id, message_id=message_id)

    def get_lists(self, max_pages: int = 10) -> list[dict]:
        """Contactenlijsten (id + naam), gepagineerd opgehaald via de v3-API."""
        lists: list[dict] = []
        offset = 0
        for _ in range(max_pages):
            body = self._get_v3("lists", {"limit": 100, "offset": offset})
            page = body.get("lists") or []
            lists.extend(
                {"id": item.get("id"), "name": item.get("name") or "(zonder naam)"}
                for item in page
            )
            if len(page) < 100:
                break
            offset += 100
        return lists
