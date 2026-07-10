"""Unit-tests voor de template-validatie."""

from __future__ import annotations

from app.newsletter.renderer import BANNER_MARKER
from app.newsletter.template_validation import validate_template_html


def test_missing_banner_marker_is_warning_not_error() -> None:
    # Geen ##BANNERS##-marker nodig; een template met losse placeholders mag.
    errors, warnings = validate_template_html("<html>{{INTRO_1}} geen marker</html>")
    assert errors == []  # niets blokkeert; admin mag elke layout opslaan
    assert any("BANNERS" in w for w in warnings)  # wel een waarschuwing


def test_present_marker_drops_its_warning() -> None:
    _, warnings = validate_template_html(f"<html>{BANNER_MARKER}</html>")
    assert not any("BANNERS" in w for w in warnings)  # marker aanwezig -> geen tip
    assert warnings  # andere aanbevolen placeholders ontbreken nog


def test_full_template_has_no_errors() -> None:
    from app.newsletter.templates import load_template

    errors, warnings = validate_template_html(load_template("voetbalreizenxl-main"))
    assert errors == []
    # De meegeleverde template heeft alle placeholders; alleen de informatieve
    # witruimte-melding mag verschijnen (die template heeft bewust vaste maten).
    assert [w for w in warnings if "witruimte niet instelbaar" not in w] == []


def test_warns_when_cta_button_lacks_own_token() -> None:
    # Een grote knop zonder cta-token kleurt mee met de productknoppen; waarschuw.
    _, warnings = validate_template_html(
        "<html><a style='background:{{STYLE_BUTTON_BG}}'>{{HOOFD_CTA_TEKST}}</a>"
        "{{ unsubscribe }}<!-- ##CARDS## --></html>"
    )
    assert any("STYLE_CTA_BUTTON_BG" in w for w in warnings)
    _, warnings = validate_template_html(
        "<html><a style='background:{{STYLE_CTA_BUTTON_BG}}'>{{HOOFD_CTA_TEKST}}</a>"
        "{{ unsubscribe }}<!-- ##CARDS## --></html>"
    )
    assert not any("STYLE_CTA_BUTTON_BG" in w for w in warnings)
