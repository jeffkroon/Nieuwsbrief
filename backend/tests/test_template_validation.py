"""Unit-tests voor de template-validatie."""

from __future__ import annotations

from app.newsletter.renderer import BANNER_MARKER
from app.newsletter.template_validation import validate_template_html


def test_missing_banner_marker_is_error() -> None:
    errors, _ = validate_template_html("<html>geen marker</html>")
    assert errors  # banner-marker ontbreekt -> harde fout
    assert any("BANNERS" in e for e in errors)


def test_present_marker_no_errors_but_warnings() -> None:
    errors, warnings = validate_template_html(f"<html>{BANNER_MARKER}</html>")
    assert errors == []  # marker aanwezig -> mag opgeslagen
    assert warnings  # aanbevolen placeholders ontbreken nog


def test_full_template_has_no_errors() -> None:
    from app.newsletter.templates import load_template

    errors, warnings = validate_template_html(load_template("voetbalreizenxl-main"))
    assert errors == []
    assert warnings == []  # de meegeleverde template heeft alle placeholders
