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
# kleur valt terug op de default hieronder (of de primaire merkkleur).
DEFAULT_PRIMARY = "#FF7200"
DEFAULT_FOOTER_BG = "#6a6a6b"

# Alle instelbare kleuren met hun default. `None` = valt terug op de primaire merkkleur.
_COLOR_DEFAULTS: dict[str, str | None] = {
    "text_color": "#3b3f44",     # introtekst
    "heading_color": "#ffffff",  # kop op de headerfoto
    "link_color": "#0092ff",     # links in de tekst
    "page_bg": "#ffffff",        # e-mail-achtergrond
    "button_bg": None,           # knoppen -> merkkleur
    "button_text": "#ffffff",    # knop-tekst
    "accent": None,              # wedstrijd-/clubnaam op de kaart -> merkkleur
    "block_border": None,        # rand van het wedstrijdblok -> merkkleur
    "card_border": "#e8e8e8",    # rand van een kaart
    "card_bg": "#ffffff",        # achtergrond van een kaart
    "price_color": "#1a3a6e",    # prijsbedrag
    "badge_bg": "#1a3a6e",       # achtergrond van het badge-label
    "home_color": "#00AEEF",     # thuisclubnaam (wedstrijdblok)
    "away_color": "#1a3a6e",     # uitclub-/clubnaam (wedstrijdblok)
    "footer_bg": DEFAULT_FOOTER_BG,  # footer-balk
    "footer_text": "#ffffff",    # footer-tekst
}
COLOR_KEYS = tuple(_COLOR_DEFAULTS)
FONT_KEY = "font_family"

_HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def is_valid_hex_color(value: str | None) -> bool:
    """Geldige hex-kleur (bv. '#fff' of '#ffffff')? Voor validatie aan de randen."""
    return isinstance(value, str) and bool(_HEX.match(value.strip()))


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
    brand_footer = brand.get("footer_color")
    font_key = styles.get(FONT_KEY)

    def pick(key: str) -> str:
        default = _COLOR_DEFAULTS[key]
        if default is None:
            default = primary
        return styles.get(key) or default

    result = {key: pick(key) for key in COLOR_KEYS}
    result["font"] = EMAIL_SAFE_FONTS.get(font_key, DEFAULT_FONT_STACK)
    # Footer valt terug op de merk-footerkleur als er geen eigen keuze is.
    if not styles.get("footer_bg") and brand_footer:
        result["footer_bg"] = brand_footer
    return result


# Welke stijlwaarden als {{STYLE_*}}-token in de layout-HTML beschikbaar zijn.
# (De kaart-/blok-kleuren worden in code toegepast, niet via tokens.)
_TEMPLATE_TOKENS = {
    "{{STYLE_FONT}}": "font",
    "{{STYLE_TEXT_COLOR}}": "text_color",
    "{{STYLE_HEADING_COLOR}}": "heading_color",
    "{{STYLE_LINK_COLOR}}": "link_color",
    "{{STYLE_PAGE_BG}}": "page_bg",
    "{{STYLE_BUTTON_BG}}": "button_bg",
    "{{STYLE_BUTTON_TEXT}}": "button_text",
    "{{STYLE_ACCENT}}": "accent",
    "{{STYLE_FOOTER_BG}}": "footer_bg",
    "{{STYLE_FOOTER_TEXT}}": "footer_text",
}


def style_replacements(brand: dict) -> dict[str, str]:
    """Placeholder->waarde map voor de {{STYLE_*}}-tokens in de layout-HTML."""
    st = effective_styles(brand)
    return {token: st[key] for token, key in _TEMPLATE_TOKENS.items()}
