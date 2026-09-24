"""Concept bijwerken, status en resultaten per verzendplatform (gemockt, geen netwerk).

Veiligheid: bijwerken mag alleen bij status concept; alles daarbuiten wordt
geweigerd voordat er iets wordt geschreven.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.activecampaign import ActiveCampaignClient, ActiveCampaignError
from app.services.brevo import BrevoClient, BrevoError
from app.services.esp import DRAFT, SENT, CampaignNotFound, rate, sum_known
from app.services.klaviyo import KlaviyoClient, KlaviyoError

HTML = "<html><body>Nieuwsbrief met genoeg tekst {% unsubscribe %}</body></html>"
SENDER = {"sender_name": "Merk", "sender_email": "info@merk.nl"}


def _mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---- gedeelde hulpjes -------------------------------------------------------

def test_rate_en_som_zijn_eerlijk_over_ontbrekende_getallen() -> None:
    assert rate(25, 100) == 0.25
    assert rate(None, 100) is None and rate(5, 0) is None
    assert sum_known(None, None) is None
    assert sum_known(2, None, 3) == 5


# ---- Brevo ------------------------------------------------------------------

def _brevo(routes: dict, log: list) -> BrevoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        return routes.get((request.method, request.url.path), httpx.Response(500))

    return BrevoClient("k", client=_mock(handler))


def test_brevo_werkt_concept_bij_met_put() -> None:
    log: list = []
    client = _brevo({
        ("GET", "/v3/emailCampaigns/7"): httpx.Response(200, json={"status": "draft"}),
        ("PUT", "/v3/emailCampaigns/7"): httpx.Response(204),
    }, log)
    client.update_draft(7, subject="Nieuw", html=HTML, preview_text="Pre", **SENDER)
    put = log[-1]
    assert put.method == "PUT"
    body = json.loads(put.content)
    assert body == {
        "subject": "Nieuw",
        "sender": {"name": "Merk", "email": "info@merk.nl"},
        "htmlContent": HTML,
        "previewText": "Pre",
    }
    # Naam, ontvangers en planning worden nooit meegestuurd.
    assert not {"name", "recipients", "scheduledAt"} & set(body)


def test_brevo_weigert_bijwerken_van_verstuurde_campagne() -> None:
    log: list = []
    client = _brevo({("GET", "/v3/emailCampaigns/7"): httpx.Response(200, json={"status": "sent"})}, log)
    with pytest.raises(BrevoError, match="geen concept meer"):
        client.update_draft(7, subject="x", html=HTML, **SENDER)
    assert all(r.method == "GET" for r in log)


def test_brevo_verwijderde_campagne_geeft_not_found() -> None:
    client = _brevo({("GET", "/v3/emailCampaigns/7"): httpx.Response(404, json={})}, [])
    with pytest.raises(CampaignNotFound):
        client.get_campaign_status(7)


def test_brevo_resultaten_uit_global_stats() -> None:
    stats = {"sent": 1000, "delivered": 980, "uniqueViews": 245, "uniqueClicks": 49,
             "unsubscriptions": 3, "hardBounces": 5, "softBounces": 15}
    client = _brevo({("GET", "/v3/emailCampaigns/7"): httpx.Response(
        200, json={"status": "sent", "statistics": {"globalStats": stats}}
    )}, [])
    res = client.get_results(7)
    assert res.status == SENT
    assert (res.sent, res.delivered, res.opens_unique, res.clicks_unique) == (1000, 980, 245, 49)
    assert res.bounces == 20 and res.unsubscribes == 3
    assert res.open_rate == 0.25 and res.click_rate == 0.05


# ---- Klaviyo ----------------------------------------------------------------

def _klaviyo(status: str, templates: list[str], log: list) -> KlaviyoClient:
    """templates: de template-ids die het bericht achtereenvolgens teruggeeft."""
    order = list(templates)

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        key = (request.method, request.url.path)
        if key == ("GET", "/api/campaigns/C1"):
            return httpx.Response(200, json={"data": {"id": "C1", "attributes": {"status": status}}})
        if key == ("GET", "/api/campaigns/C1/campaign-messages"):
            return httpx.Response(200, json={"data": [{"id": "M1"}]})
        if key == ("GET", "/api/campaign-messages/M1/relationships/template"):
            return httpx.Response(200, json={"data": {"id": order.pop(0)}})
        if key == ("PATCH", "/api/campaign-messages/M1"):
            return httpx.Response(200, json={})
        if key == ("POST", "/api/templates"):
            return httpx.Response(201, json={"data": {"id": "T-NIEUW"}})
        if key == ("POST", "/api/campaign-message-assign-template"):
            return httpx.Response(200, json={})
        if key == ("DELETE", "/api/templates/T-NIEUW"):
            return httpx.Response(204)
        return httpx.Response(500, text=f"onverwacht {key}")

    return KlaviyoClient("pk", client=_mock(handler))


def test_klaviyo_werkt_onderwerp_en_html_bij() -> None:
    log: list = []
    _klaviyo("Draft", ["T-OUD", "T-KLOON-2"], log).update_draft(
        "C1", subject="Nieuw", html=HTML, preview_text="Pre", **SENDER
    )
    patch = next(r for r in log if r.method == "PATCH")
    content = json.loads(patch.content)["data"]["attributes"]["definition"]["content"]
    assert content["subject"] == "Nieuw" and content["preview_text"] == "Pre"
    # De losse (herbruikbare) template wordt opgeruimd.
    assert any(r.method == "DELETE" for r in log)


def test_klaviyo_meldt_het_als_de_html_niet_is_vervangen() -> None:
    """De re-assign is niet gedocumenteerd: blijft de oude template staan, dan hard falen."""
    with pytest.raises(KlaviyoError, match="niet aan het concept gekoppeld"):
        _klaviyo("Draft", ["T-OUD", "T-OUD"], []).update_draft(
            "C1", subject="x", html=HTML, **SENDER
        )


def test_klaviyo_weigert_bijwerken_als_campagne_ingepland_is() -> None:
    log: list = []
    with pytest.raises(KlaviyoError, match="geen concept meer"):
        _klaviyo("Scheduled", [], log).update_draft("C1", subject="x", html=HTML, **SENDER)
    assert all(r.method == "GET" for r in log)


def test_klaviyo_resultaten_via_values_report() -> None:
    log: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        path = request.url.path
        if path == "/api/campaigns/C1":
            return httpx.Response(200, json={"data": {"attributes": {"status": "Sent"}}})
        if path == "/api/metrics":
            return httpx.Response(200, json={"data": [
                {"id": "X1", "attributes": {"name": "Opened Email"}},
                {"id": "PO", "attributes": {"name": "Placed Order"}},
            ]})
        if path == "/api/campaign-values-reports":
            return httpx.Response(200, json={"data": {"attributes": {"results": [{
                "statistics": {"recipients": 500, "delivered": 490, "opens_unique": 200,
                               "open_rate": 0.40816, "clicks_unique": 30, "click_rate": 0.06122,
                               "unsubscribes": 2, "bounced": 10},
            }]}}})
        return httpx.Response(500)

    res = KlaviyoClient("pk", client=_mock(handler)).get_results("C1")
    assert res.status == SENT and res.opens_unique == 200 and res.open_rate == 0.4082
    report = json.loads(log[-1].content)["data"]["attributes"]
    assert report["conversion_metric_id"] == "PO"
    assert report["filter"] == 'equals(campaign_id,"C1")'


def test_klaviyo_concept_heeft_nog_geen_resultaten_en_vraagt_geen_rapport() -> None:
    log: list = []
    res = _klaviyo("Draft", [], log).get_results("C1")
    assert res.status == DRAFT and res.sent is None
    assert len(log) == 1  # alleen de status; het schaarse rapport (2/min) niet verspillen


# ---- ActiveCampaign ---------------------------------------------------------

def _ac(campaign: dict, log: list, put_status: int = 200) -> ActiveCampaignClient:
    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        if request.method == "GET" and request.url.path == "/api/3/campaigns/9":
            return httpx.Response(200, json={"campaign": campaign})
        if request.method == "PUT" and request.url.path == "/api/3/messages/44":
            return httpx.Response(put_status, json={})
        return httpx.Response(500)

    return ActiveCampaignClient("https://acct.api-us1.com", "k", client=_mock(handler))


def test_activecampaign_werkt_bericht_bij_inclusief_preheader() -> None:
    log: list = []
    _ac({"status": "0", "message_id": "44"}, log).update_draft(
        "9", subject="Nieuw", html=HTML, preview_text="Pre", **SENDER
    )
    body = json.loads(log[-1].content)["message"]
    assert body["subject"] == "Nieuw" and body["html"] == HTML
    assert body["preheader_text"] == "Pre"


def test_activecampaign_weigert_bijwerken_na_verzending() -> None:
    log: list = []
    with pytest.raises(ActiveCampaignError, match="geen concept meer"):
        _ac({"status": "5", "message_id": "44"}, log).update_draft(
            "9", subject="x", html=HTML, **SENDER
        )
    assert all(r.method == "GET" for r in log)


def test_activecampaign_resultaten_ten_opzichte_van_verzonden() -> None:
    res = _ac({"status": "5", "send_amt": "200", "uniqueopens": "50", "uniquelinkclicks": "10",
               "unsubscribes": "1", "hardbounces": "2", "softbounces": "3"}, []).get_results("9")
    assert res.status == SENT and res.sent == 200 and res.bounces == 5
    assert res.open_rate == 0.25 and res.click_rate == 0.05
    assert res.delivered is None  # AC geeft dit niet; niet verzinnen
