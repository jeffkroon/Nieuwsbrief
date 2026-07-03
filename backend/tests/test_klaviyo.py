"""Tests voor de Klaviyo-client (drafts only, 3-call-flow, JSON:API)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.klaviyo import KLAVIYO_REVISION, KlaviyoClient, KlaviyoError

HTML_OK = "<html><body>Nieuwsbrief {% unsubscribe %}</body></html>"


def _client_with(responses: dict, recorder: list) -> KlaviyoClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        key = (request.method, request.url.path)
        if key in responses:
            return responses[key]
        return httpx.Response(500, text=f"onverwacht: {key}")

    return KlaviyoClient(
        "pk_test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _happy_responses() -> dict:
    return {
        ("POST", "/api/templates"): httpx.Response(
            201, json={"data": {"type": "template", "id": "TPL1"}}
        ),
        ("POST", "/api/campaigns"): httpx.Response(
            201,
            json={"data": {"type": "campaign", "id": "CAMP1", "relationships": {
                "campaign-messages": {"data": [{"type": "campaign-message", "id": "MSG1"}]}
            }}},
        ),
        ("POST", "/api/campaign-message-assign-template"): httpx.Response(
            200, json={"data": {"type": "campaign-message", "id": "MSG1"}}
        ),
        ("DELETE", "/api/templates/TPL1"): httpx.Response(204),
    }


def _draft(client: KlaviyoClient):
    return client.create_draft(
        name="Test - Zomer", subject="Onderwerp", sender_name="Shop",
        sender_email="info@shop.nl", html=HTML_OK, list_ids=["LIST1"],
        preview_text="preheader",
    )


def test_happy_path_three_calls_then_cleanup() -> None:
    recorder: list[httpx.Request] = []
    draft = _draft(_client_with(_happy_responses(), recorder))
    assert draft.campaign_id == "CAMP1" and draft.message_id == "MSG1"
    assert [(r.method, r.url.path) for r in recorder] == [
        ("POST", "/api/templates"),
        ("POST", "/api/campaigns"),
        ("POST", "/api/campaign-message-assign-template"),
        ("DELETE", "/api/templates/TPL1"),  # herbruikbare template opgeruimd
    ]
    # Headers: gepinde revision + JSON:API content-type + private key.
    first = recorder[0]
    assert first.headers["revision"] == KLAVIYO_REVISION
    assert first.headers["content-type"] == "application/vnd.api+json"
    assert first.headers["authorization"] == "Klaviyo-API-Key pk_test"
    # Payloads: CODE-template en draft-campagne zonder send_strategy.
    tpl = json.loads(recorder[0].content)
    assert tpl["data"]["attributes"]["editor_type"] == "CODE"
    camp = json.loads(recorder[1].content)["data"]["attributes"]
    assert camp["audiences"]["included"] == ["LIST1"]
    assert "send_strategy" not in camp and "send_options" not in camp
    content = camp["campaign-messages"]["data"][0]["attributes"]["definition"]["content"]
    assert content["subject"] == "Onderwerp" and content["from_email"] == "info@shop.nl"
    assign = json.loads(recorder[2].content)["data"]
    assert assign["id"] == "MSG1"
    assert assign["relationships"]["template"]["data"]["id"] == "TPL1"


def test_requires_audience() -> None:
    client = _client_with({}, [])
    with pytest.raises(ValueError, match="klaviyo_list_id"):
        client.create_draft(name="x", subject="s", sender_name="n", sender_email="e@x.nl",
                            html=HTML_OK, list_ids=None)


def test_requires_unsubscribe_tag() -> None:
    client = _client_with({}, [])
    with pytest.raises(ValueError, match="unsubscribe"):
        client.create_draft(name="x", subject="s", sender_name="n", sender_email="e@x.nl",
                            html="<html>geen afmeldlink</html>", list_ids=["L1"])


def test_assign_failure_cleans_up_campaign_and_template() -> None:
    recorder: list[httpx.Request] = []
    responses = _happy_responses()
    responses[("POST", "/api/campaign-message-assign-template")] = httpx.Response(
        400, json={"errors": [{"detail": "template niet toegestaan"}]}
    )
    responses[("DELETE", "/api/campaigns/CAMP1")] = httpx.Response(204)
    with pytest.raises(KlaviyoError, match="template niet toegestaan"):
        _draft(_client_with(responses, recorder))
    paths = [(r.method, r.url.path) for r in recorder]
    assert ("DELETE", "/api/campaigns/CAMP1") in paths  # wees-campagne opgeruimd
    assert ("DELETE", "/api/templates/TPL1") in paths  # wees-template opgeruimd


def test_jsonapi_error_detail_surfaced() -> None:
    responses = {("POST", "/api/templates"): httpx.Response(
        400, json={"errors": [{"title": "Bad Request", "detail": "html is verplicht"}]}
    )}
    with pytest.raises(KlaviyoError, match="html is verplicht"):
        _draft(_client_with(responses, []))
