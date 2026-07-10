"""Unit-tests voor de ActiveCampaign-client (geen netwerk; httpx-client gemockt)."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import pytest

from app.services.activecampaign import (
    ActiveCampaignClient,
    ActiveCampaignError,
    _text_fallback,
)

API_URL = "https://account.api-us1.com"
HTML = "<html><body><h1>Nieuwsbrief</h1><p>Inhoud met genoeg tekens.</p></body></html>"


@dataclass
class _FakeHttp:
    """Speelt de v1- (POST) en v3- (GET) antwoorden af, in volgorde."""

    post_responses: list = field(default_factory=list)
    get_responses: list = field(default_factory=list)
    posts: list = field(default_factory=list)
    gets: list = field(default_factory=list)

    def post(self, url, *, params=None, data=None):
        self.posts.append({"url": url, "params": params, "data": data})
        return self.post_responses.pop(0)

    def get(self, url, *, params=None, headers=None):
        self.gets.append({"url": url, "params": params, "headers": headers})
        return self.get_responses.pop(0)


def _client(http) -> ActiveCampaignClient:
    return ActiveCampaignClient(API_URL, "geheime-key", client=http)


def test_requires_api_url_and_key() -> None:
    with pytest.raises(ValueError, match="API-key"):
        ActiveCampaignClient(API_URL, "")
    with pytest.raises(ValueError, match="API-URL"):
        ActiveCampaignClient("account.api-us1.com", "key")  # zonder https://


def test_create_draft_two_step_flow() -> None:
    http = _FakeHttp(post_responses=[
        httpx.Response(200, json={"id": 555, "result_code": 1}),
        httpx.Response(200, json={"id": 777, "result_code": 1}),
    ])
    draft = _client(http).create_draft(
        name="Ohcascas - Zomer", subject="De zomer begint",
        sender_name="Ohcascas", sender_email="info@ohcascas.nl",
        html=HTML, list_ids=[3],
    )
    assert draft.message_id == "555" and draft.campaign_id == "777"

    message_call, campaign_call = http.posts
    assert message_call["url"] == f"{API_URL}/admin/api.php"
    assert message_call["params"]["api_action"] == "message_add"
    assert message_call["params"]["api_key"] == "geheime-key"
    assert message_call["data"]["subject"] == "De zomer begint"
    assert message_call["data"]["fromname"] == "Ohcascas"
    assert message_call["data"]["fromemail"] == "info@ohcascas.nl"
    assert message_call["data"]["html"] == HTML
    assert message_call["data"]["p[3]"] == 3
    assert "Nieuwsbrief" in message_call["data"]["text"]  # tekst-fallback

    assert campaign_call["params"]["api_action"] == "campaign_create"
    assert campaign_call["data"]["type"] == "single"
    assert campaign_call["data"]["status"] == 0  # concept, nooit verzenden
    assert campaign_call["data"]["m[555]"] == 100
    assert campaign_call["data"]["p[3]"] == 3


def test_create_draft_requires_list() -> None:
    with pytest.raises(ActiveCampaignError, match="lijst-ID"):
        _client(_FakeHttp()).create_draft(
            name="x", subject="s", sender_name="n", sender_email="e@x.nl",
            html=HTML, list_ids=None,
        )


def test_v1_error_message_surfaces() -> None:
    http = _FakeHttp(post_responses=[
        httpx.Response(200, json={"result_code": 0, "result_message": "Invalid API key"}),
    ])
    with pytest.raises(ActiveCampaignError, match="Invalid API key"):
        _client(http).create_draft(
            name="x", subject="s", sender_name="n", sender_email="e@x.nl",
            html=HTML, list_ids=[1],
        )


def test_non_json_response_hints_wrong_url() -> None:
    http = _FakeHttp(post_responses=[httpx.Response(200, text="<html>login</html>")])
    with pytest.raises(ActiveCampaignError, match="API-URL"):
        _client(http).create_draft(
            name="x", subject="s", sender_name="n", sender_email="e@x.nl",
            html=HTML, list_ids=[1],
        )


def test_get_lists_via_v3_with_pagination() -> None:
    page1 = {"lists": [{"id": str(i), "name": f"Lijst {i}"} for i in range(100)]}
    page2 = {"lists": [{"id": "100", "name": "Laatste"}]}
    http = _FakeHttp(get_responses=[
        httpx.Response(200, json=page1),
        httpx.Response(200, json=page2),
    ])
    lists = _client(http).get_lists()
    assert len(lists) == 101
    assert lists[-1] == {"id": "100", "name": "Laatste"}
    assert http.gets[0]["url"] == f"{API_URL}/api/3/lists"
    assert http.gets[0]["headers"]["Api-Token"] == "geheime-key"
    assert http.gets[1]["params"]["offset"] == 100


def test_get_lists_bad_status_gives_clear_error() -> None:
    http = _FakeHttp(get_responses=[httpx.Response(403, json={})])
    with pytest.raises(ActiveCampaignError, match="403"):
        _client(http).get_lists()


def test_text_fallback_strips_markup() -> None:
    text = _text_fallback("<style>a{color:red}</style><p>Hoi <b>daar</b></p>")
    assert text == "Hoi daar"
