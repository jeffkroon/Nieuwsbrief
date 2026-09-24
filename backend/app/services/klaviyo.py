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

Bijwerken van een bestaand concept (alleen bij status "Draft"):
- onderwerp/preheader/afzender: PATCH /api/campaign-messages/{id} (gedocumenteerd)
- HTML: nieuwe template toewijzen via assign-template. Of dat een bestaande
  toewijzing overschrijft staat NIET in de documentatie; daarom lezen we daarna
  de template-id van het bericht terug. Is die niet veranderd, dan volgt een
  harde fout in plaats van een stil half bijgewerkt concept.

Resultaten: POST /api/campaign-values-reports (limiet 2/min, 225/dag; vereist
conversion_metric_id, dus ook de scope metrics:read).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

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
)

KLAVIYO_BASE_URL = "https://a.klaviyo.com"
# Gepind op de klassieke Campaigns API-vorm; per Klaviyo's deprecation-beleid blijft
# deze revision tot ~2028 werken. Niet blind verhogen: de nieuwe "omni"-API heeft een
# andere request-structuur.
KLAVIYO_REVISION = "2026-04-15"
HTML_MIN_BYTES = 10
# Geen gedocumenteerde API-limiet; boven ~102 KB knipt Gmail de mail af.
HTML_WARN_BYTES = 102_400
# Klaviyo kent alleen zijn eigen schrijfwijze; andere platform-tags zijn hiervoor
# al omgezet (zie app/newsletter/esp_tags.py). Blijft staan als laatste vangnet.
UNSUBSCRIBE_TAGS = ("{% unsubscribe %}", "{%unsubscribe%}", "unsubscribe_link")
# Klaviyo-statussen zijn weergave-teksten met hoofdletters; de rest valt onder OTHER.
_STATUS = {
    "draft": DRAFT,
    "scheduled": SCHEDULED,
    "preparing to schedule": SCHEDULED,
    "sending": SENDING,
    "preparing to send": SENDING,
    "adding recipients": SENDING,
    "sending segments": SENDING,
    "sent": SENT,
    "variations sent": SENT,
}
RESULT_STATISTICS = (
    "recipients", "delivered", "opens_unique", "open_rate",
    "clicks_unique", "click_rate", "unsubscribes", "bounced",
)
PREFERRED_CONVERSION_METRIC = "Placed Order"


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
        _check_html(html)
        if not list_ids:
            raise ValueError(
                "Klaviyo vereist een audience: stel 'klaviyo_list_id' in voor dit bedrijf"
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

    def get_lists(self, max_pages: int = 10) -> list[dict]:
        """Alle lijsten (id + naam) ophalen, voor de lijst-kiezer bij onboarding.

        Alleen-lezen (scope lists:read); volgt de JSON:API-paginatie.
        """
        lists: list[dict] = []
        path = "/api/lists"
        for _ in range(max_pages):
            body = self._request("GET", path, None, expect=(200,))
            for row in body.get("data") or []:
                name = ((row.get("attributes") or {}).get("name")) or row.get("id", "")
                lists.append({"id": row.get("id"), "name": name})
            next_url = (body.get("links") or {}).get("next")
            if not next_url:
                break
            path = next_url.replace(self._base_url, "", 1)
        return lists

    def get_campaign_status(self, campaign_id: str) -> str:
        """Genormaliseerde status van de campagne. Alleen-lezen."""
        body = self._request("GET", f"/api/campaigns/{campaign_id}", None, expect=(200,))
        raw = ((body.get("data") or {}).get("attributes") or {}).get("status") or ""
        return _STATUS.get(str(raw).strip().lower(), OTHER)

    def update_draft(
        self,
        campaign_id: str,
        *,
        subject: str,
        sender_name: str,
        sender_email: str,
        html: str,
        preview_text: str | None = None,
        reply_to: str | None = None,
    ) -> None:
        """Werk een bestaand CONCEPT bij; weigert alles wat geen Draft is."""
        _check_html(html)
        status = self.get_campaign_status(campaign_id)
        if status != DRAFT:
            raise KlaviyoError(f"campagne {campaign_id} is geen concept meer (status {status})")
        message_id = self._message_id(campaign_id)
        # Eerst de HTML: dat is de stap die niet gedocumenteerd is. Mislukt die, dan
        # is er nog niets aan de campagne veranderd (geen half bijgewerkt concept).
        old_template = self._template_of(message_id)
        template_id = self._create_template(f"{subject} (bijgewerkt)", html)
        try:
            self._assign_template(message_id, template_id)
        finally:
            self._delete_silent(f"/api/templates/{template_id}")
        new_template = self._template_of(message_id)
        if not new_template or new_template == old_template:
            raise KlaviyoError(
                "Klaviyo heeft de nieuwe HTML niet aan het concept gekoppeld; "
                "het concept is ongewijzigd gebleven"
            )
        content: dict[str, Any] = {
            "subject": subject,
            "from_email": sender_email,
            "from_label": sender_name,
            "reply_to_email": reply_to or sender_email,
        }
        if preview_text:
            content["preview_text"] = preview_text
        self._request(
            "PATCH",
            f"/api/campaign-messages/{message_id}",
            {"data": {"type": "campaign-message", "id": message_id, "attributes": {
                "definition": {"channel": "email", "content": content},
            }}},
            expect=(200,),
        )

    def get_results(self, campaign_id: str) -> CampaignResults:
        """Status en resultaten via het values-report (laatste 12 maanden)."""
        status = self.get_campaign_status(campaign_id)
        if status not in (SENT, SENDING):
            return CampaignResults(status=status)
        body = self._request(
            "POST",
            "/api/campaign-values-reports",
            {"data": {"type": "campaign-values-report", "attributes": {
                "statistics": list(RESULT_STATISTICS),
                "timeframe": {"key": "last_12_months"},
                "conversion_metric_id": self._conversion_metric_id(),
                "filter": f'equals(campaign_id,"{campaign_id}")',
            }}},
            expect=(200,),
        )
        results = ((body.get("data") or {}).get("attributes") or {}).get("results") or []
        stats = (results[0].get("statistics") or {}) if results else {}
        return CampaignResults(
            status=status,
            sent=as_int(stats.get("recipients")),
            delivered=as_int(stats.get("delivered")),
            opens_unique=as_int(stats.get("opens_unique")),
            clicks_unique=as_int(stats.get("clicks_unique")),
            unsubscribes=as_int(stats.get("unsubscribes")),
            bounces=as_int(stats.get("bounced")),
            open_rate=_as_rate(stats.get("open_rate")),
            click_rate=_as_rate(stats.get("click_rate")),
        )

    def _message_id(self, campaign_id: str) -> str:
        body = self._request(
            "GET", f"/api/campaigns/{campaign_id}/campaign-messages", None, expect=(200,)
        )
        rows = body.get("data") or []
        message_id = rows[0].get("id") if rows and isinstance(rows[0], dict) else None
        if not isinstance(message_id, str) or not message_id:
            raise KlaviyoError(f"campagne {campaign_id} heeft geen e-mailbericht")
        return message_id

    def _template_of(self, message_id: str) -> str | None:
        body = self._request(
            "GET", f"/api/campaign-messages/{message_id}/relationships/template",
            None, expect=(200,),
        )
        template_id = (body.get("data") or {}).get("id")
        return template_id if isinstance(template_id, str) else None

    def _conversion_metric_id(self) -> str:
        """Klaviyo eist een conversiemetriek, ook als we alleen opens/kliks willen."""
        body = self._request("GET", "/api/metrics", None, expect=(200,))
        metrics = [m for m in body.get("data") or [] if isinstance(m, dict) and m.get("id")]
        if not metrics:
            raise KlaviyoError("Klaviyo-account heeft geen metrieken; resultaten niet op te halen")
        preferred = [
            m for m in metrics
            if (m.get("attributes") or {}).get("name") == PREFERRED_CONVERSION_METRIC
        ]
        return (preferred or metrics)[0]["id"]

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

        if response.status_code == 404 and method != "POST":
            raise CampaignNotFound(f"Klaviyo kent {path} niet (meer)")
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
        except (KlaviyoError, CampaignNotFound):
            pass  # best effort; nooit de hoofd-flow laten falen op opruimen


def _check_html(html: str) -> None:
    if len(html.encode("utf-8")) < HTML_MIN_BYTES:
        raise ValueError("html is te kort")
    if not any(tag in html for tag in UNSUBSCRIBE_TAGS):
        # Zonder afmeldlink kan een mens de campagne in het dashboard niet eens
        # inplannen; hard afdwingen in code.
        raise ValueError(
            "Klaviyo vereist een afmeldlink; deze nieuwsbrief heeft er geen. "
            "Voeg {% unsubscribe %} toe aan de template."
        )


def _as_rate(value: Any) -> float | None:
    """Klaviyo geeft percentages als fractie (0.8253)."""
    try:
        return round(float(value), 4) if value is not None else None
    except (TypeError, ValueError):
        return None
