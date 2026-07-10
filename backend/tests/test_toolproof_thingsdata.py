"""Regressietest met een echte ActiveCampaign/Stripo-export (Thingsdata).

Deze template liet de tool-proof falen en zichzelf verwerpen (kale template
zonder placeholders opgeslagen). De oorzaken: (1) invulvak-waarden werden
gestript waardoor de byte-round-trip brak, en (2) de KAART-verificatie eiste
een link die dit ontwerp niet heeft. Deze test bewijst dat een realistische
operatie-set nu wél door de verificatie komt en byte-identiek round-tript.
"""

from __future__ import annotations

from pathlib import Path

from app.newsletter.models import Item, NewsletterContent
from app.newsletter.renderer import render_newsletter
from app.newsletter.toolproof import make_toolproof

from tests.test_toolproof import FakeLLM

RAW = (
    '<html><body>'
    '<h3 style="color: #ffffff;"><strong>Connect. Monitor. </strong></h3>'
    '<p style="color: #ffffff;">Reliable IoT connectivity and solutions</p>'
    '<a href class="es-button" target="_blank">Discover our solutions</a>'
    '<p><strong>Hi <span style="color:#ea5b0c;">%FIRSTNAME%</span>,</strong></p>'
    '<p>Bij Thingsdata geloven we in slimme connectiviteit.</p>'
    '<tr><td class="card"><img src="https://x.test/a.jpeg" width="285">'
    '<p style="color: #ea5b0c;"><strong>Update</strong></p>'
    '<p style="font-size: 14px;"><strong>Platform update</strong></p>'
    '<p>Nieuwe features in ons platform.</p>'
    '<p style="color: #ea5b0c;"><strong>Lees meer</strong></p></td></tr>'
    '<tr><td class="card"><img src="https://x.test/b.jpeg" width="285">'
    '<p style="color: #ea5b0c;"><strong>Klantcase</strong></p>'
    '<p style="font-size: 14px;"><strong>Andere titel</strong></p>'
    '<p>Weer een tekst.</p>'
    '<p style="color: #ea5b0c;"><strong>Lees meer</strong></p></td></tr>'
    '<p>Verstuurd naar: %EMAIL%</p>'
    '</body></html>'
)

_KAART1 = (
    '<tr><td class="card"><img src="https://x.test/a.jpeg" width="285">'
    '<p style="color: #ea5b0c;"><strong>Update</strong></p>'
    '<p style="font-size: 14px;"><strong>Platform update</strong></p>'
    '<p>Nieuwe features in ons platform.</p>'
    '<p style="color: #ea5b0c;"><strong>Lees meer</strong></p></td></tr>'
)
_KAART1_TOKENS = (
    '<!-- ##KAART## --><tr><td class="card"><img src="{{KAART_IMAGE_URL}}" width="285">'
    '<p style="color: #ea5b0c;"><strong>{{KAART_LABEL}}</strong></p>'
    '<p style="font-size: 14px;"><strong>{{KAART_TITEL}}</strong></p>'
    '<p>{{KAART_SUBTITEL}}</p>'
    '<p style="color: #ea5b0c;"><strong>{{KAART_KNOP_TEKST}}</strong></p></td></tr><!-- /##KAART## -->'
)
_KAART2 = (
    '<tr><td class="card"><img src="https://x.test/b.jpeg" width="285">'
    '<p style="color: #ea5b0c;"><strong>Klantcase</strong></p>'
    '<p style="font-size: 14px;"><strong>Andere titel</strong></p>'
    '<p>Weer een tekst.</p>'
    '<p style="color: #ea5b0c;"><strong>Lees meer</strong></p></td></tr>'
)

OPS = [
    {"op": "replace", "find": "<strong>Connect. Monitor. </strong>",
     "replace": "<strong>{{VAK_HERO_TITEL}}</strong>", "reason": "hero-titel"},
    {"op": "replace", "find": ">Reliable IoT connectivity and solutions</p>",
     "replace": ">{{VAK_HERO_TEKST}}</p>", "reason": "hero-tekst"},
    {"op": "replace", "find": ">Discover our solutions</a>",
     "replace": ">{{HEADER_CTA_TEKST}}</a>", "reason": "hero-knop"},
    {"op": "replace", "find": "<p>Bij Thingsdata geloven we in slimme connectiviteit.</p>",
     "replace": "<p>{{INTRO_1}}</p>", "reason": "intro"},
    {"op": "replace", "find": _KAART1, "replace": _KAART1_TOKENS, "reason": "voorbeeldkaart"},
    {"op": "replace_range", "from": _KAART2, "to": "<p>Verstuurd naar:",
     "replace": "", "reason": "kaart-kopie verwijderen"},
]


def test_thingsdata_export_toolproofs_and_roundtrips() -> None:
    result = make_toolproof(FakeLLM({"operations": OPS, "notes": []}), RAW)

    # Alle operaties toegepast, niets verworpen, verificatie groen.
    assert result.failed == [], result.failed
    assert result.ok, result.checks_failed
    assert any("byte-identiek" in p for p in result.checks_passed)
    assert "{{VAK_HERO_TITEL}}" in result.html
    assert "<!-- ##KAART## -->" in result.html
    assert "Klantcase" not in result.html  # tweede kaart verwijderd

    # Onafhankelijk bewijs: render met de originele waarden == origineel min kopie.
    brand = {
        "brand_name": "Thingsdata", "brand_email": "info@thingsdata.nl",
        "website_url": "https://thingsdata.com", "logo_url": "https://x.test/logo.png",
        "dummy_image_url": "https://x.test/d.png", "primary_color": "#ea5b0c",
        "styles": result.styles,
    }
    content = NewsletterContent(
        theme="T", subject="s", intro_1="Bij Thingsdata geloven we in slimme connectiviteit.",
        intro_2="", main_cta_text="", main_cta_url="", slot_cta_text="", slot_cta_url="",
        matches=(),
        items=(Item(
            title="Platform update", url="", subtitle="Nieuwe features in ons platform.",
            image_url="https://x.test/a.jpeg", label="Update", button_text="Lees meer",
        ),),
        header_cta_text="Discover our solutions",
        custom_fields=(("HERO_TITEL", "Connect. Monitor. "), ("HERO_TEKST", "Reliable IoT connectivity and solutions")),
    )
    verwacht = RAW.replace(_KAART2, "")
    assert render_newsletter(result.html, brand, content) == verwacht


def test_hardcoded_card_link_is_rejected() -> None:
    """Review-vondst: een vaste http-link/foto in een herhaald kaart-blok zou
    elke kaart naar dezelfde plek laten wijzen; dat moet geweigerd worden."""
    from app.newsletter.toolproof import verify_toolproof

    html = (
        "<html><body>{{INTRO_1}}"
        '<!-- ##KAART## --><td><a href="https://vast.nl/product-1">'
        '<img src="{{KAART_IMAGE_URL}}"/></a><h3>{{KAART_TITEL}}</h3></td><!-- /##KAART## -->'
        "</body></html>"
    )
    _, failed = verify_toolproof(html)
    assert any("vaste link of foto" in f for f in failed)

    # Volledig getokeniseerd kaart-blok: geen fout.
    goed = html.replace('href="https://vast.nl/product-1"', 'href="{{KAART_URL}}"')
    passed, failed = verify_toolproof(goed)
    assert failed == []
    assert any("kaart-blok herhaalt" in p for p in passed)
