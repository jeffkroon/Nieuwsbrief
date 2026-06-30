"""Unit-tests voor de template-validatie."""

from __future__ import annotations

from app.newsletter.renderer import BANNER_MARKER
from app.newsletter.template_validation import validate_template_html


def test_missing_banner_marker_is_warning_not_error() -> None:
    errors, warnings = validate_template_html("<html>geen marker</html>")
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
    assert warnings == []  # de meegeleverde template heeft alle placeholders
