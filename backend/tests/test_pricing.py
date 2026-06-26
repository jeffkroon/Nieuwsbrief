"""Tests voor de vanafprijs-parser en -fetcher."""

from __future__ import annotations

import httpx

from app.newsletter.models import PRICE_ON_REQUEST
from app.newsletter.pricing import fetch_match_price, parse_price


def test_parse_price_vanaf() -> None:
    assert parse_price("Tickets vanaf € 189 per persoon") == "€ 189"


def test_parse_price_va_afkorting() -> None:
    assert parse_price("v.a. €249,-") == "€ 249"


def test_parse_price_from_english() -> None:
    assert parse_price("from € 99,00") == "€ 99,00"


def test_parse_price_loose_euro() -> None:
    assert parse_price("Prijs: € 299,-") == "€ 299"


def test_parse_price_none_found() -> None:
    assert parse_price("Geen prijsinformatie beschikbaar") == PRICE_ON_REQUEST


def test_fetch_price_ok() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="vanaf € 189"))
    with httpx.Client(transport=transport) as client:
        assert fetch_match_price("https://x/wedstrijd", client=client) == "€ 189"


def test_fetch_price_http_error_falls_back() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(404, text="not found"))
    with httpx.Client(transport=transport) as client:
        assert fetch_match_price("https://x/wedstrijd", client=client) == PRICE_ON_REQUEST


def test_fetch_price_network_error_falls_back() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kapot")

    with httpx.Client(transport=httpx.MockTransport(boom)) as client:
        assert fetch_match_price("https://x/wedstrijd", client=client) == PRICE_ON_REQUEST
