"""ActiveCampaign-client die uitsluitend concepten (drafts) aanmaakt.

Veiligheid by design: deze klasse heeft GEEN methode om te verzenden of te
plannen. Campagnes worden aangemaakt met status 0 (concept) en blijven staan
tot een mens ze in het ActiveCampaign-dashboard controleert en verstuurt.

Flow (v1-API voor het schrijven; de v3-API kan campagne-inhoud niet zetten):
1. POST admin/api.php?api_action=message_add   (onderwerp, afzender, HTML, lijst)
2. POST admin/api.php?api_action=campaign_create (type single, status 0 = concept,
   lijst + message gekoppeld)
Lijsten ophalen gaat wel via de nette v3-API (GET /api/3/lists).

Bijwerken en resultaten via v3: GET /api/3/campaigns/{id} geeft status ("0" =
concept, "5" = verstuurd), message_id en de tellers; PUT /api/3/messages/{id}
werkt de inhoud van het bericht bij. Alleen bij status concept.

ActiveCampaign heeft een account-specifieke API-URL (https://<account>.api-us1.com);
die is niet geheim en staat in de tenant-config. De API-key is wel geheim en staat
in de versleutelde opslag. Dezelfde key werkt voor v1 en v3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from app.services.esp import (
    DRAFT,
    OTHER,
    SCHEDULED,
    SENDING,
    SENT,
    CampaignNotFound,
    CampaignResults,
    as_int,
    rate,
    sum_known,
)

HTML_MIN_BYTES = 10
# Geen gedocumenteerde API-limiet; boven ~102 KB knipt Gmail de mail af.
HTML_WARN_BYTES = 102_400

# Alleen echte ActiveCampaign-hosts: voorkomt dat een (per ongeluk of kwaadwillend)
# ingevulde interne URL server-side wordt aangeroepen met de API-key eraan (SSRF).
# v1-statuscodes (de v3-docs geven geen lijst): 0 concept, 1 gepland, 2 bezig,
# 3 gepauzeerd, 4 gestopt, 5 voltooid.
_STATUS = {"0": DRAFT, "1": SCHEDULED, "2": SENDING, "5": SENT}

_ALLOWED_HOST = re.compile(r"^[a-z0-9-]+\.(api-us[0-9]+\.com|activehosted\.com)$")


def validate_api_url(api_url: str) -> str:
    """Valideer de account-URL hard; geeft de genormaliseerde URL terug."""
    url = (api_url or "").strip().rstrip("/")
    if not url.startswith("https://"):
        raise ValueError(
            "ActiveCampaign API-URL ontbreekt of is ongeldig (verwacht "
            "https://<account>.api-us1.com; zie Settings > Developer in ActiveCampaign)"
        )
    host = url.removeprefix("https://").split("/")[0].lower()
    if not _ALLOWED_HOST.match(host):
        raise ValueError(
            f"ActiveCampaign API-URL wijst niet naar ActiveCampaign ({host}); "
            "verwacht https://<account>.api-us1.com"
        )
    return url


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
        self._base = validate_api_url(api_url)
        self._api_key = api_key
        self._timeout = timeout
        self._client = client  # injecteerbaar voor tests

    # -- http ---------------------------------------------------------------

    def _post_v1(self, action: str, data: dict) -> dict:
        """v1-call: form-encoded POST naar admin/api.php; JSON terug."""
        url = f"{self._base}/admin/api.php"
        # LET OP: de v1-API accepteert de key alleen als query-param. Voeg voor deze
        # client dus nooit request-logging/tracing toe die query-params vastlegt.
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
        return self._request_v3("GET", path, params=params)

    def _request_v3(
        self, method: str, path: str, *, params: dict | None = None, json: dict | None = None
    ) -> dict:
        url = f"{self._base}/api/3/{path.lstrip('/')}"
        headers = {"Api-Token": self._api_key}
        try:
            if self._client is not None:
                resp = self._client.request(method, url, params=params, json=json, headers=headers)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    resp = client.request(method, url, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise ActiveCampaignError(f"ActiveCampaign niet bereikbaar: {exc}") from exc
        if resp.status_code == 404:
            raise CampaignNotFound(f"ActiveCampaign kent {path} niet (meer)")
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

    def _campaign(self, campaign_id: str) -> dict:
        body = self._get_v3(f"campaigns/{campaign_id}")
        campaign = body.get("campaign")
        if not isinstance(campaign, dict):
            raise ActiveCampaignError(f"ActiveCampaign gaf geen campagne {campaign_id} terug")
        return campaign

    def get_campaign_status(self, campaign_id: str) -> str:
        """Genormaliseerde status van de campagne. Alleen-lezen."""
        return _STATUS.get(str(self._campaign(campaign_id).get("status")), OTHER)

    def update_draft(
        self,
        campaign_id: str,
        *,
        subject: str,
        sender_name: str,
        sender_email: str,
        html: str,
        preview_text: str | None = None,
    ) -> None:
        """Werk het bericht van een CONCEPT-campagne bij; weigert alles wat geen concept is."""
        if not html or len(html.encode()) < HTML_MIN_BYTES:
            raise ActiveCampaignError("lege of veel te korte HTML; concept niet bijgewerkt")
        campaign = self._campaign(campaign_id)
        status = _STATUS.get(str(campaign.get("status")), OTHER)
        if status != DRAFT:
            raise ActiveCampaignError(
                f"campagne {campaign_id} is geen concept meer (status {status})"
            )
        message_id = as_int(campaign.get("message_id"))
        if not message_id:
            raise ActiveCampaignError(f"campagne {campaign_id} heeft geen bericht om bij te werken")
        message = {
            "subject": subject,
            "fromname": sender_name,
            "fromemail": sender_email,
            "reply2": sender_email,
            "html": html,
            "text": _text_fallback(html),
        }
        if preview_text:
            message["preheader_text"] = preview_text
        self._request_v3("PUT", f"messages/{message_id}", json={"message": message})

    def get_results(self, campaign_id: str) -> CampaignResults:
        """Tellers van de campagne. AC geeft geen 'afgeleverd': percentages t.o.v. verzonden."""
        campaign = self._campaign(campaign_id)
        sent = as_int(campaign.get("send_amt"))
        opens = as_int(campaign.get("uniqueopens"))
        clicks = as_int(campaign.get("uniquelinkclicks"))
        return CampaignResults(
            status=_STATUS.get(str(campaign.get("status")), OTHER),
            sent=sent,
            opens_unique=opens,
            clicks_unique=clicks,
            unsubscribes=as_int(campaign.get("unsubscribes")),
            bounces=sum_known(
                as_int(campaign.get("hardbounces")), as_int(campaign.get("softbounces"))
            ),
            open_rate=rate(opens, sent),
            click_rate=rate(clicks, sent),
        )
