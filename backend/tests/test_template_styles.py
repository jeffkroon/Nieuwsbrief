"""Unit-tests voor de stijl-laag: sanitatie, defaults en placeholder-injectie."""

from __future__ import annotations

from app.newsletter.styles import (
    DEFAULT_FONT_STACK,
    EMAIL_SAFE_FONTS,
    effective_styles,
    sanitize_styles,
    style_replacements,
)

BRAND = {"primary_color": "#FF7200"}


def test_sanitize_keeps_valid_hex_and_known_font() -> None:
    clean = sanitize_styles(
        {
            "button_bg": "#123abc",
            "text_color": "#000",
            "font_family": "Georgia",
            "accent": "#FFFFFF",
        }
    )
    assert clean["button_bg"] == "#123abc"
    assert clean["text_color"] == "#000"
    assert clean["accent"] == "#FFFFFF"
    assert clean["font_family"] == "georgia"  # genormaliseerd naar lowercase


def test_sanitize_drops_injection_and_unknown() -> None:
    clean = sanitize_styles(
        {
            "button_bg": "red;} body{display:none",  # geen geldige hex -> weg
            "text_color": "javascript:alert(1)",  # weg
            "font_family": "Comic Sans'; evil",  # onbekend lettertype -> weg
            "rogue_key": "#fff",  # onbekende sleutel -> weg
        }
    )
    assert clean == {}


def test_sanitize_handles_none() -> None:
    assert sanitize_styles(None) == {}


def test_effective_styles_defaults_match_brand_primary() -> None:
    st = effective_styles(BRAND)
    assert st["button_bg"] == "#FF7200"  # valt terug op primaire merkkleur
    assert st["accent"] == "#FF7200"
    assert st["heading"] == "#FF7200"
    assert st["button_text"] == "#ffffff"
    assert st["text"] == "#3b3f44"
    assert st["font"] == DEFAULT_FONT_STACK


def test_effective_styles_uses_custom_values() -> None:
    brand = {**BRAND, "styles": {"button_bg": "#00ff00", "font_family": "verdana"}}
    st = effective_styles(brand)
    assert st["button_bg"] == "#00ff00"
    assert st["font"] == EMAIL_SAFE_FONTS["verdana"]
    # niet-gezette waarden vallen nog steeds terug op de merkkleur
    assert st["accent"] == "#FF7200"


def test_style_replacements_returns_all_tokens() -> None:
    repl = style_replacements(BRAND)
    for token in (
        "{{STYLE_FONT}}",
        "{{STYLE_TEXT_COLOR}}",
        "{{STYLE_HEADING_COLOR}}",
        "{{STYLE_BUTTON_BG}}",
        "{{STYLE_BUTTON_TEXT}}",
        "{{STYLE_ACCENT}}",
    ):
        assert token in repl
