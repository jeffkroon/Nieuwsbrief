"""Tests voor de site-agnostische extractie-laag."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from app.newsletter.extraction import (
    extract_links,
    extract_matches,
    extract_price,
    extract_tone,
    fetch_page,
    html_to_text,
)


@dataclass
class FakeText:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list


@dataclass
class FakeMessages:
    payload: dict
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse([FakeText(json.dumps(self.payload))])


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.messages = FakeMessages(payload=payload)


def test_html_to_text_makes_links_absolute_and_strips_tags() -> None:
    html = '<div><script>x()</script><a href="/tickets/chelsea-arsenal/">Chelsea - Arsenal</a> <b>249,-</b></div>'
    text = html_to_text(html, "https://www.voetbalreizenxl.nl/tickets/premier-league/")
    assert "x()" not in text  # script verwijderd
    assert "Chelsea - Arsenal (https://www.voetbalreizenxl.nl/tickets/chelsea-arsenal/)" in text
    assert "249,-" in text
    assert "<" not in text


def test_extract_matches_normalizes_prices() -> None:
    llm = FakeLLM(
        {
            "matches": [
                {"home": "Chelsea", "away": "Brighton & Hove Albion", "url": "https://x/tickets/cb/", "price": "249,-"},
                {"home": "Arsenal", "away": "Coventry City", "url": "https://x/tickets/ac/", "price": None},
            ]
        }
    )
    matches = extract_matches(llm, "<html>...</html>", source_url="https://x/tickets/premier-league/")
    assert matches[0]["price"] == "€ 249"
    assert matches[1]["price"] == "op aanvraag"  # null -> op aanvraag
    # Extractie gebruikt het goedkope model en structured output.
    call = llm.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["output_config"]["format"]["type"] == "json_schema"


def test_extract_links() -> None:
    llm = FakeLLM(
        {"links": [{"label": "Tickets Bayern München", "url": "https://x/tickets/duitsland/bayern-munchen/"}]}
    )
    links = extract_links(llm, "<html>...</html>", source_url="https://x/tickets/", query="bayern")
    assert links[0]["url"].endswith("/bayern-munchen/")


def test_extract_tone() -> None:
    llm = FakeLLM({"tone_of_voice": "Informeel, je-vorm, energiek en sportief."})
    tone = extract_tone(llm, "<html>...</html>", source_url="https://x/")
    assert "sportief" in tone
    assert llm.messages.calls[0]["model"] == "claude-haiku-4-5"


def test_extract_price_single_page() -> None:
    llm = FakeLLM({"price": "€ 299"})
    assert extract_price(llm, "<html>...</html>", source_url="https://x/m/") == "€ 299"


def test_extract_price_null_falls_back() -> None:
    llm = FakeLLM({"price": None})
    assert extract_price(llm, "<html>...</html>", source_url="https://x/m/") == "op aanvraag"


def test_fetch_page_ok_and_error() -> None:
    ok = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>hi</html>"))
    with httpx.Client(transport=ok) as c:
        status, html = fetch_page("https://x/", c)
        assert status == 200 and "hi" in html

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kapot")

    with httpx.Client(transport=httpx.MockTransport(boom)) as c:
        status, html = fetch_page("https://x/", c)
        assert status is None and html == ""


def test_html_to_text_keeps_images_when_asked() -> None:
    html = '<div><img src="/foto/ring.png" alt="x"><a href="/p/ring">Ring</a></div>'
    plain = html_to_text(html, "https://shop.nl")
    with_imgs = html_to_text(html, "https://shop.nl", keep_images=True)
    assert "AFBEELDING" not in plain  # standaard: geen afbeeldingen (bestaand gedrag)
    assert "AFBEELDING(https://shop.nl/foto/ring.png)" in with_imgs
    assert "Ring (https://shop.nl/p/ring)" in with_imgs


def test_extract_og_image() -> None:
    from app.newsletter.extraction import extract_og_image

    html = '<head><meta property="og:image" content="https://cdn.shop.nl/ring.png"></head>'
    assert extract_og_image(html) == "https://cdn.shop.nl/ring.png"
    # attribuut-volgorde omgedraaid + protocol-relatieve URL
    html2 = '<meta content="//cdn.shop.nl/k.png" property="og:image">'
    assert extract_og_image(html2) == "https://cdn.shop.nl/k.png"
    # http wordt https (mailclients blokkeren http-afbeeldingen)
    html3 = '<meta property="og:image" content="http://shop.nl/r.png">'
    assert extract_og_image(html3) == "https://shop.nl/r.png"
    assert extract_og_image("<html>niks</html>") is None


def test_extract_products() -> None:
    from app.newsletter.extraction import extract_products

    payload = {"products": [{
        "name": "Ankh Ring (Goud)", "url": "https://shop.nl/products/ankh",
        "price": "€ 59,95", "image_url": "https://cdn.shop.nl/ankh.png",
    }]}
    llm = FakeLLM(payload)
    products = extract_products(llm, "<html>pagina</html>", source_url="https://shop.nl/collections/ringen")
    assert products == payload["products"]
    # De pagina ging met afbeeldingen mee naar het LLM (keep_images-pad).
    sent = llm.messages.calls[0]["messages"][0]["content"]
    assert "Bron-URL: https://shop.nl/collections/ringen" in sent
