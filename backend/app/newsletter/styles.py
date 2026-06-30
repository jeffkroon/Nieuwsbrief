"""Stijl-laag voor templates: kleuren en lettertype die een bedrijf zelf kiest.

De layout (HTML) wordt door Dunion beheerd; een bedrijf past alleen deze stijl aan.
Waarden komen van gebruikers, dus ze worden hard gesaneerd voordat ze in inline
`style`-attributen van de e-mail belanden (geen CSS-injectie).

Defaults zijn zo gekozen dat de render identiek blijft aan de oude vaste template
zolang een bedrijf niets aanpast.
"""

from __future__ import annotations

import re

# Mail-veilige lettertype-stacks. De gebruiker kiest een sleutel; wij bepalen de
# stack. Webfonts laten we bewust weg: die werken lang niet in elke mailclient.
EMAIL_SAFE_FONTS: dict[str, str] = {
    "arial": "Arial,Helvetica,sans-serif",
    "helvetica": "Helvetica,Arial,sans-serif",
    "verdana": "Verdana,Geneva,sans-serif",
    "tahoma": "Tahoma,Geneva,sans-serif",
    "trebuchet": "'Trebuchet MS',Helvetica,sans-serif",
    "georgia": "Georgia,'Times New Roman',serif",
    "times": "'Times New Roman',Times,serif",
    "courier": "'Courier New',Courier,monospace",
}
DEFAULT_FONT_KEY = "arial"
DEFAULT_FONT_STACK = EMAIL_SAFE_FONTS[DEFAULT_FONT_KEY]

# Defaults voor de kleuren. Komen overeen met de oude vaste template, zodat de
# render byte-identiek blijft als een bedrijf niets aanpast. Een ontbrekende
# kleur valt terug op de primaire merkkleur (zie effective_styles).
DEFAULT_TEXT_COLOR = "#3b3f44"
DEFAULT_BUTTON_TEXT = "#ffffff"
DEFAULT_PRIMARY = "#FF7200"

COLOR_KEYS = ("text_color", "heading_color", "button_bg", "button_text", "accent")
FONT_KEY = "font_family"

_HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def sanitize_styles(raw: dict | None) -> dict:
    """Houd alleen geldige kleuren (hex) en een bekende lettertype-sleutel over.

    Onbekende sleutels en ongeldige waarden worden weggegooid. Zo kan een
    bedrijfsgebruiker geen rommel of CSS in de mail injecteren.
    """
    raw = raw or {}
    clean: dict = {}
    for key in COLOR_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and _HEX.match(value.strip()):
            clean[key] = value.strip()
    font = raw.get(FONT_KEY)
    if isinstance(font, str) and font.strip().lower() in EMAIL_SAFE_FONTS:
        clean[FONT_KEY] = font.strip().lower()
    return clean


def effective_styles(brand: dict) -> dict:
    """Bereken de daadwerkelijk te gebruiken stijlwaarden.

    Leest `brand["styles"]` (al gesaneerd bij opslaan) en vult ontbrekende waarden
    aan met defaults / de primaire merkkleur. Geeft kant-en-klare CSS-waarden terug.
    """
    styles = brand.get("styles") or {}
    primary = brand.get("primary_color") or DEFAULT_PRIMARY
    font_key = styles.get(FONT_KEY)
    return {
        "font": EMAIL_SAFE_FONTS.get(font_key, DEFAULT_FONT_STACK),
        "text": styles.get("text_color") or DEFAULT_TEXT_COLOR,
        "heading": styles.get("heading_color") or primary,
        "button_bg": styles.get("button_bg") or primary,
        "button_text": styles.get("button_text") or DEFAULT_BUTTON_TEXT,
        "accent": styles.get("accent") or primary,
    }


def style_replacements(brand: dict) -> dict[str, str]:
    """Placeholder->waarde map voor de {{STYLE_*}}-tokens in de layout-HTML."""
    st = effective_styles(brand)
    return {
        "{{STYLE_FONT}}": st["font"],
        "{{STYLE_TEXT_COLOR}}": st["text"],
        "{{STYLE_HEADING_COLOR}}": st["heading"],
        "{{STYLE_BUTTON_BG}}": st["button_bg"],
        "{{STYLE_BUTTON_TEXT}}": st["button_text"],
        "{{STYLE_ACCENT}}": st["accent"],
    }
