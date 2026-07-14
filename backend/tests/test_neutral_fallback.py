"""De ingebouwde fallback is neutraal (geen voetbal-styling) en wordt zichtbaar
gemeld. Een tenant zonder eigen template mag nooit stil voetbal-styling krijgen.
"""

from __future__ import annotations

import re

from app.newsletter.models import Item, NewsletterContent
from app.newsletter.renderer import render_newsletter
from app.newsletter.save_validation import validate_template_for_save
from app.newsletter.templates import load_template
from app.newsletter.toolproof import verify_toolproof
from app.newsletter.tools import DEFAULT_TEMPLATE, ToolContext, execute_tool

from tests.test_tools import CONFIG, _tenant

_INTERN = re.compile(r"\{\{[A-Z0-9_]+\}\}")  # interne tokens, niet de ESP-tags
_VOETBAL = ("Bestel tickets", "Bekijk alle wedstrijden", "##BANNERS##", "##CARDS##")


def _brand() -> dict:
    return {
        "brand_name": "Testklant", "brand_email": "info@test.nl",
        "website_url": "https://test.nl", "logo_url": "https://x/logo.png",
        "dummy_image_url": "https://x/d.png", "primary_color": "#123456",
        "brand_adres": "Straat 1", "brand_postcode_stad": "1000 AA Stad", "styles": {},
    }


def _content() -> NewsletterContent:
    return NewsletterContent(
        theme="Nieuws", subject="s", intro_1="Introtekst.", intro_2="",
        main_cta_text="Bekijk", main_cta_url="https://test.nl/x",
        slot_cta_text="Neem contact op", slot_cta_url="https://test.nl/c",
        matches=(),
        items=(Item(title="Item een", url="https://x/1", subtitle="Sub.",
                    image_url="", label="Nieuws", button_text="Lees meer"),),
        header_title="Welkom", header_subtitle="Onze update", header_cta_text="Bekijk",
        custom_fields=(("SLOT_TITEL", "Interesse?"), ("SLOT_SUBTITEL", "Wij helpen.")),
    )


def test_default_fallback_is_neutraal() -> None:
    assert DEFAULT_TEMPLATE == "neutraal-basis"


def test_neutraal_basis_is_geldig_en_toolproof() -> None:
    html = load_template("neutraal-basis")
    errors, _ = validate_template_for_save(html)
    assert errors == [], errors
    _, failed = verify_toolproof(html)
    assert failed == [], failed


def test_neutraal_basis_rendert_zonder_voetbal() -> None:
    html = load_template("neutraal-basis")
    out = render_newsletter(html, _brand(), _content())
    assert not _INTERN.findall(out), _INTERN.findall(out)
    for verboden in _VOETBAL:
        assert verboden not in out, verboden
    assert "#123456" in out  # merkkleur (accent) in de hero
    assert "Item een" in out and "{{ unsubscribe }}" in out


def test_lege_secties_vallen_weg_in_fallback() -> None:
    html = load_template("neutraal-basis")
    leeg = NewsletterContent(
        theme="N", subject="s", intro_1="Alleen intro.", intro_2="",
        main_cta_text="x", main_cta_url="u", slot_cta_text="", slot_cta_url="",
        matches=(), items=(), header_title="H", header_subtitle="S",
        header_cta_text="C", custom_fields=(),
    )
    out = render_newsletter(html, _brand(), leeg)
    assert not _INTERN.findall(out)
    assert "Interesse?" not in out  # slot-sectie valt weg zonder VAK-inhoud


def test_preview_zonder_eigen_template_waarschuwt(session, cipher) -> None:
    """Een tenant zonder eigen template krijgt de neutrale fallback + waarschuwing."""
    tenant = _tenant(session)  # heeft brand-config maar geen template-rij
    payload = {
        "theme": "Nieuws", "subject": "Onderwerp",
        "intro_1": "Intro.", "intro_2": "",
        "main_cta_text": "Bekijk", "main_cta_url": "https://x/a",
        "slot_cta_text": "Contact", "slot_cta_url": "https://x/c",
    }
    ctx = ToolContext(session=session, tenant_id=tenant.id, cipher=cipher, preview_holder=[])
    result = execute_tool("preview_newsletter", payload, ctx)
    assert "let_op_geen_eigen_template" in result
    html = ctx.preview_holder[0]
    for verboden in _VOETBAL:
        assert verboden not in html, verboden
