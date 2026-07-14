"""Unit-tests voor de opslag-garantie: een template mag de database alleen in als
hij een sentinel-render foutloos doorstaat. Vangt de kopieer-verminking (orphan-
braces / afgekapte tokens) en half-getokeniseerde templates, zonder geldige
templates ten onrechte te weigeren.
"""

from __future__ import annotations

from pathlib import Path

from app.newsletter.save_validation import validate_template_for_save

_HTML_DIR = Path(__file__).resolve().parent.parent / "app" / "newsletter" / "html"

# Een kleine, correcte tool-proof template (logo, hero-knop, intro, eigen kaart,
# footer met afmeldlink). Bewust compleet zodat hij zonder waarschuwing-ruis is.
GOED = (
    "<html><body style=\"background:{{STYLE_PAGE_BG}};\">"
    '<a href="{{WEBSITE_URL}}"><img src="{{LOGO_URL}}"></a>'
    '<h1 style="color:{{STYLE_HEADING_COLOR}};">{{HEADER_TITEL}}</h1>'
    '<p style="color:{{STYLE_TEXT_COLOR}};">{{INTRO_1}}</p>'
    '<a href="{{HOOFD_CTA_URL}}" style="background:{{STYLE_HERO_BUTTON_BG}};">{{HEADER_CTA_TEKST}}</a>'
    "<!-- ##KAART## -->"
    '<div><a href="{{KAART_URL}}"><img src="{{KAART_IMAGE_URL}}"></a>'
    "<strong>{{KAART_TITEL}}</strong><p>{{KAART_SUBTITEL}}</p></div>"
    "<!-- /##KAART## -->"
    "<footer style=\"background:{{STYLE_FOOTER_BG}};color:{{STYLE_FOOTER_TEXT}};\">"
    "{{BRAND_NAME}}<br>{{BRAND_EMAIL}}"
    '<a href="{{ unsubscribe }}">Uitschrijven</a></footer>'
    "</body></html>"
)


def test_goede_template_wordt_geaccepteerd() -> None:
    errors, _ = validate_template_for_save(GOED)
    assert errors == [], errors


def test_builtin_voetbal_template_blijft_geldig() -> None:
    """Regressie tegen valse afwijzingen: de canonieke builtin moet blijven passeren."""
    html = (_HTML_DIR / "voetbalreizenxl-main.html").read_text()
    errors, _ = validate_template_for_save(html)
    assert errors == [], errors


def test_orphan_braces_worden_geweigerd() -> None:
    """De kopieer-verminking liet losse `}}` achter (bv. `styleBG}}`)."""
    corrupt = GOED.replace("{{STYLE_PAGE_BG}}", "styleBG}}", 1)
    errors, _ = validate_template_for_save(corrupt)
    assert errors, "corrupte template met orphan-braces moet geweigerd worden"
    assert any("}}" in e or "haak" in e.lower() or "token" in e.lower() for e in errors)


def test_afgekapt_open_token_wordt_geweigerd() -> None:
    """Een afgekapt open-token (`{{STYLE_PAGE_BG` zonder sluiting) is corruptie."""
    corrupt = GOED.replace("{{STYLE_PAGE_BG}}", "{{STYLE_PAGE_BG", 1)
    errors, _ = validate_template_for_save(corrupt)
    assert errors, "afgekapt open-token moet geweigerd worden"


def test_template_zonder_placeholders_wordt_geweigerd() -> None:
    errors, _ = validate_template_for_save("<html><body>Platte tekst</body></html>")
    assert errors, "een template zonder enkele placeholder is niet tool-proof"
