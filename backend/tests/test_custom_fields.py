"""Tests voor template-eigen invulvakken ({{VAK_*}}) en optionele ##SECTIE##-blokken."""

from __future__ import annotations

import pytest

from app.newsletter.custom_fields import (
    fill_custom_fields,
    find_custom_slots,
    normalize_custom_fields,
)
from app.newsletter.models import NewsletterContent
from app.newsletter.renderer import render_newsletter

BRAND = {
    "brand_name": "Testmerk",
    "brand_email": "info@test.nl",
    "website_url": "https://test.nl",
    "logo_url": "https://test.nl/logo.png",
    "dummy_image_url": "https://test.nl/dummy.png",
    "primary_color": "#FF7200",
}


def _content(**overrides) -> NewsletterContent:
    base = dict(
        theme="Thema",
        subject="Onderwerp",
        intro_1="Intro een",
        intro_2="Intro twee",
        main_cta_text="Klik",
        main_cta_url="https://test.nl/actie",
        slot_cta_text="",
        slot_cta_url="",
        matches=(),
    )
    return NewsletterContent(**{**base, **overrides})


def test_find_custom_slots_unique_in_order() -> None:
    html = "{{VAK_B}} x {{VAK_A}} y {{VAK_B}} z {{INTRO_1}}"
    assert find_custom_slots(html) == ["B", "A"]
    assert find_custom_slots("") == []


def test_normalize_accepts_lowercase_and_prefix() -> None:
    assert normalize_custom_fields({"vak_artikel_titel": " Kop ", "QA_VRAAG": "x"}) == {
        "ARTIKEL_TITEL": "Kop",
        "QA_VRAAG": "x",
    }


def test_fill_replaces_known_and_clears_unknown() -> None:
    html = "<p>{{VAK_TITEL}}</p><p>{{VAK_ONBEKEND}}</p>"
    assert fill_custom_fields(html, {"TITEL": "Hoi"}) == "<p>Hoi</p><p></p>"


def test_empty_section_block_is_removed_entirely() -> None:
    html = (
        "<table>VOOR"
        "<!-- ##SECTIE## --><tr><td><h2>{{VAK_KOP}}</h2><p>{{VAK_TEKST}}</p></td></tr><!-- /##SECTIE## -->"
        "NA</table>"
    )
    # Geen inhoud: het hele blok (inclusief kop-markup en randen) verdwijnt.
    assert fill_custom_fields(html, {}) == "<table>VOORNA</table>"
    # Eén vak gevuld: blok blijft, markers weg, lege vakken leeg.
    kept = fill_custom_fields(html, {"KOP": "Titel"})
    assert "<h2>Titel</h2>" in kept and "##SECTIE##" not in kept


def test_multiple_sections_drop_independently() -> None:
    html = (
        "<!-- ##SECTIE## -->[A:{{VAK_A}}]<!-- /##SECTIE## -->"
        "<!-- ##SECTIE## -->[B:{{VAK_B}}]<!-- /##SECTIE## -->"
    )
    out = fill_custom_fields(html, {"B": "vol"})
    assert out == "[B:vol]"


def test_nested_sections_fail_hard() -> None:
    html = (
        "<!-- ##SECTIE## --> buiten {{VAK_A}} "
        "<!-- ##SECTIE## --> binnen {{VAK_B}} <!-- /##SECTIE## -->"
        " rest <!-- /##SECTIE## -->"
    )
    with pytest.raises(ValueError, match="geneste"):
        fill_custom_fields(html, {"A": "x"})


def test_colliding_keys_fail_hard() -> None:
    with pytest.raises(ValueError, match="TITEL"):
        normalize_custom_fields({"vak_titel": "een", "TITEL": "twee"})


def test_unclosed_section_left_untouched() -> None:
    html = "x <!-- ##SECTIE## --> {{VAK_A}} zonder einde"
    out = fill_custom_fields(html, {"A": "vol"})
    assert "##SECTIE##" in out  # geen halve verwijderingen


def test_render_newsletter_fills_custom_fields_and_drops_empty_sections() -> None:
    template = (
        "<html><body>{{INTRO_1}}"
        "<div>{{VAK_ARTIKEL_TITEL}}</div>"
        "<!-- ##SECTIE## --><div id='qa'>{{VAK_QA_VRAAG}}</div><!-- /##SECTIE## -->"
        "</body></html>"
    )
    gevuld = render_newsletter(
        template, BRAND, _content(custom_fields=(("ARTIKEL_TITEL", "Kop"), ("QA_VRAAG", "Vraag?")))
    )
    assert "Kop" in gevuld and "Vraag?" in gevuld

    leeg = render_newsletter(template, BRAND, _content())
    assert "qa" not in leeg  # sectie weggelaten
    assert "{{VAK_" not in leeg  # geen rauwe placeholders


def test_tool_validation_rejects_bad_custom_fields() -> None:
    from app.newsletter.tools import _validated_custom_fields

    assert _validated_custom_fields(None) == {}
    assert _validated_custom_fields({"vak_x": "tekst"}) == {"X": "tekst"}
    with pytest.raises(ValueError, match="object"):
        _validated_custom_fields(["geen", "object"])
    with pytest.raises(ValueError, match="tekst"):
        _validated_custom_fields({"X": ["lijst", "mag", "niet"]})
