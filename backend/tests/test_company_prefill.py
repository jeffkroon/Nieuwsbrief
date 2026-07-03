"""Tests voor het automatisch invullen van een nieuw bedrijf vanaf de website."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.services import company_prefill

HOME_HTML = """<html><head>
<meta name="theme-color" content="#1d3557">
<meta property="og:image" content="https://cdn.shop.nl/og-hero.png">
</head><body>
<img class="site-logo" src="/assets/logo.png" alt="Shop logo">
<a href="/pages/contact">Contact</a>
<a href="https://www.facebook.com/shopnl">FB</a>
<a href="https://www.instagram.com/shopnl/">IG</a>
</body></html>"""

CONTACT_HTML = "<html><body>Mail ons: hallo@shop.nl, KVK 12345678</body></html>"

LLM_PAYLOAD = {
    "email": "hallo@shop.nl", "phone": "+31 20 123 4567",
    "address": "Winkelstraat 1", "postcode_city": "1234 AB Amsterdam",
    "kvk": "12345678",
    "content_types": [
        {"name": "Producten", "button_text": "SHOP NU",
         "source_url": "https://shop.nl/collections/alles", "has_price": True},
    ],
}


@dataclass
class _FakeText:
    text: str
    type: str = "text"


@dataclass
class _FakeResp:
    content: list


@dataclass
class _FakeMessages:
    payload: dict
    calls: list = field(default_factory=list)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResp([_FakeText(json.dumps(self.payload))])


class FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.messages = _FakeMessages(payload=payload)


def _fake_fetch(pages: dict):
    def fetch(url, client=None, timeout=20.0):
        return pages.get(url, (404, ""))
    return fetch


def test_deterministic_helpers() -> None:
    assert company_prefill._find_theme_color(HOME_HTML) == "#1d3557"
    assert company_prefill._find_logo(HOME_HTML, "https://shop.nl") == "https://shop.nl/assets/logo.png"
    assert company_prefill._find_contact_url(HOME_HTML, "https://shop.nl") == "https://shop.nl/pages/contact"
    fb = company_prefill._first_social(HOME_HTML, company_prefill._SOCIAL_PATTERNS["facebook_url"])
    assert fb == "https://www.facebook.com/shopnl"
    yt = company_prefill._first_social(HOME_HTML, company_prefill._SOCIAL_PATTERNS["youtube_url"])
    assert yt is None


def test_prefill_company_full_flow(monkeypatch) -> None:
    monkeypatch.setattr(
        company_prefill.extraction, "fetch_page",
        _fake_fetch({"https://shop.nl": (200, HOME_HTML),
                     "https://shop.nl/pages/contact": (200, CONTACT_HTML)}),
    )
    result = company_prefill.prefill_company(
        FakeLLM(LLM_PAYLOAD), name="Shop NL", website_url="https://shop.nl"
    )
    cfg = result["config"]
    assert cfg["brand_name"] == "Shop NL"
    assert cfg["brand_email"] == "hallo@shop.nl"
    assert cfg["brand_kvk"] == "12345678"
    assert cfg["primary_color"] == "#1d3557"
    assert cfg["logo_url"] == "https://shop.nl/assets/logo.png"
    assert cfg["dummy_image_url"] == "https://cdn.shop.nl/og-hero.png"
    assert cfg["facebook_url"] == "https://www.facebook.com/shopnl"
    assert cfg["youtube_url"] == ""  # niet gevonden -> leeg, niet verzonnen
    assert result["content_types"][0]["name"] == "Producten"
    assert any("youtube" in n for n in result["notes"])


def test_prefill_missing_data_stays_empty(monkeypatch) -> None:
    empty = {"email": None, "phone": None, "address": None, "postcode_city": None,
             "kvk": None, "content_types": []}
    monkeypatch.setattr(
        company_prefill.extraction, "fetch_page",
        _fake_fetch({"https://kaal.nl": (200, "<html><body>niks</body></html>")}),
    )
    result = company_prefill.prefill_company(
        FakeLLM(empty), name="Kaal", website_url="https://kaal.nl"
    )
    cfg = result["config"]
    assert cfg["brand_email"] == "" and cfg["brand_kvk"] == ""
    assert cfg["primary_color"] == "#FF7200"  # default, geen themakleur
    assert any("KVK" in n for n in result["notes"])


def test_prefill_unreachable_site(monkeypatch) -> None:
    import pytest

    monkeypatch.setattr(company_prefill.extraction, "fetch_page", _fake_fetch({}))
    with pytest.raises(ValueError, match="onbereikbaar"):
        company_prefill.prefill_company(FakeLLM({}), name="X", website_url="https://weg.nl")
