"""Tests voor de Brevo concept-client (httpx MockTransport, geen echte calls)."""

from __future__ import annotations

import httpx
import pytest

from app.services.brevo import BrevoClient, BrevoError

VALID_HTML = "<html><body>" + ("x" * 50) + "</body></html>"


def _client(handler) -> BrevoClient:
    transport = httpx.MockTransport(handler)
    return BrevoClient("test-key", client=httpx.Client(transport=transport))


def test_create_draft_posts_to_campaigns_and_returns_id() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("api-key")
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 4242})

    draft = _client(handler).create_draft(
        name="VoetbalreizenXL - Kerst",
        subject="Kerst in Londen",
        sender_name="VoetbalreizenXL",
        sender_email="info@voetbalreizenxl.nl",
        html=VALID_HTML,
        list_ids=[12],
        preview_text="Kerstvoetbal in Londen",
    )

    assert draft.campaign_id == 4242
    assert captured["url"].endswith("/emailCampaigns")
    assert captured["api_key"] == "test-key"
    assert captured["body"]["type"] == "classic"
    assert captured["body"]["recipients"] == {"listIds": [12]}


def test_draft_never_includes_scheduled_at() -> None:
    """Kernbelofte: een concept krijgt nooit scheduledAt mee."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 1})

    _client(handler).create_draft(
        name="x", subject="y", sender_name="n", sender_email="e@e.nl", html=VALID_HTML
    )
    assert "scheduledAt" not in captured["body"]
    assert "sendAtBestTime" not in captured["body"]


def test_client_has_no_send_methods() -> None:
    """By design: er bestaat geen verzend- of statusmethode op de client."""
    forbidden = {"send", "send_now", "sendNow", "send_campaign", "set_status", "schedule"}
    assert forbidden.isdisjoint(dir(BrevoClient))


def test_html_too_short_rejected() -> None:
    with pytest.raises(ValueError, match="te kort"):
        _client(lambda r: httpx.Response(201, json={"id": 1})).create_draft(
            name="x", subject="y", sender_name="n", sender_email="e@e.nl", html="<p>x</p>"
        )


def test_html_too_large_rejected() -> None:
    big = "<html>" + ("x" * 1_000_001) + "</html>"
    with pytest.raises(ValueError, match="te groot"):
        _client(lambda r: httpx.Response(201, json={"id": 1})).create_draft(
            name="x", subject="y", sender_name="n", sender_email="e@e.nl", html=big
        )


def test_empty_api_key_rejected() -> None:
    with pytest.raises(ValueError, match="BREVO_API_KEY"):
        BrevoClient("")


def test_brevo_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "missing_parameter", "message": "subject"})

    with pytest.raises(BrevoError, match="HTTP 400"):
        _client(handler).create_draft(
            name="x", subject="y", sender_name="n", sender_email="e@e.nl", html=VALID_HTML
        )


def test_unexpected_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"geen_id": True})

    with pytest.raises(BrevoError, match="Onverwacht"):
        _client(handler).create_draft(
            name="x", subject="y", sender_name="n", sender_email="e@e.nl", html=VALID_HTML
        )


def test_get_lists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/contacts/lists" in str(request.url)
        return httpx.Response(200, json={"lists": [
            {"id": 12, "name": "Nieuwsbrief", "totalSubscribers": 100},
            {"id": 34, "name": "Klanten"},
        ]})

    lists = _client(handler).get_lists()
    assert lists == [{"id": 12, "name": "Nieuwsbrief"}, {"id": 34, "name": "Klanten"}]
