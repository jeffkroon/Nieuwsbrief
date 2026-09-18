"""Wat kan een template? Eén waarheid voor agent-prompt en override-checks.

Uniformiteit-eis van Jeff: elke klant en elke template moet zich hetzelfde
gedragen. Twee gereedschappen daarvoor:
- `template_capabilities(html)`: feitenlijst voor de systeemprompt, zodat de
  assistent per gesprek WEET wat deze template ondersteunt en eerlijk is over
  wat niet kan.
- `style_key_has_effect(key, html)`: heeft een stijl-sleutel in deze template
  ergens effect? Zo niet, dan wordt een override hard geweigerd in plaats van
  stil niets te doen (zelfde eerlijkheid als de witruimte-check).

Een sleutel heeft effect via een {{STYLE_*}}-token in de HTML, óf doordat de
code zelf blokken genereert die de stijl gebruiken (##CARDS##/##BANNERS##/
##SECTIES##-blokken, de gegenereerde hero-knop {{HEADER_CTA}}).
"""

from __future__ import annotations

from app.newsletter.card_block import CARD_TPL_START
from app.newsletter.custom_fields import find_custom_slots
from app.newsletter.renderer import BANNER_MARKER, CARD_MARKER, SECTIONS_MARKER
from app.newsletter.styles import FONT_KEY, SPACING_KEYS, TEMPLATE_TOKENS

# Token per stijl-sleutel (omkering van TEMPLATE_TOKENS; font wijkt af).
_KEY_TOKENS = {key: token for token, key in TEMPLATE_TOKENS.items()}
_KEY_TOKENS[FONT_KEY] = "{{STYLE_FONT}}"

# Welke code-gegenereerde blokken gebruiken welke stijl-sleutels? De kaart- en
# banner-renderers raken verschillende sleutels; de secties-composer kan beide
# vormen renderen en telt dus bij allebei mee.
_CARD_KEYS = frozenset({"accent", "card_bg", "card_border", "badge_bg"})
_BANNER_KEYS = frozenset({"home_color", "away_color", "block_border"})
_SHARED_BLOCK_KEYS = frozenset({
    "price_color", "button_bg", "button_text", "text_color", FONT_KEY,
})


def _has_generated_blocks(html: str) -> bool:
    return CARD_MARKER in html or BANNER_MARKER in html or SECTIONS_MARKER in html


def style_key_has_effect(key: str, html: str) -> bool:
    """Heeft deze stijl-sleutel ergens effect in deze template?"""
    token = _KEY_TOKENS.get(key) or ("{{STYLE_" + key.upper() + "}}")
    if token in html:
        return True
    kaarten = CARD_MARKER in html or SECTIONS_MARKER in html
    banners = BANNER_MARKER in html or SECTIONS_MARKER in html
    if key in _CARD_KEYS and kaarten:
        return True
    if key in _BANNER_KEYS and banners:
        return True
    if key in _SHARED_BLOCK_KEYS and (kaarten or banners):
        return True
    if key in ("hero_button_bg", "hero_button_text") and "{{HEADER_CTA}}" in html:
        return True  # de gegenereerde hero-knop gebruikt deze kleuren
    if key in ("cta_button_bg", "cta_button_text") and SECTIONS_MARKER in html:
        return True  # de sectie-knop gebruikt de CTA-kleuren
    if key in ("button_bg", "button_text"):
        # Via de terugval-keten kleuren hero-/cta-knoppen mee met de
        # productknop zolang die geen eigen kleur hebben.
        suffix = "text" if key == "button_text" else "bg"
        for volger in ("hero_button", "cta_button"):
            if style_key_has_effect(f"{volger}_{suffix}", html):
                return True
    if key == FONT_KEY and "{{HEADER_CTA}}" in html:
        return True  # de gegenereerde hero-knop gebruikt het lettertype
    return False


def template_capabilities(html: str) -> dict:
    """Feiten over wat deze template ondersteunt, voor de systeemprompt."""
    html = html or ""
    spacing = [
        key for key in SPACING_KEYS
        if ("{{STYLE_" + key.upper() + "}}") in html
    ]
    return {
        "spacing_keys": spacing,
        "buttons": {
            "product": style_key_has_effect("button_bg", html),
            "hero": style_key_has_effect("hero_button_bg", html),
            "cta": style_key_has_effect("cta_button_bg", html),
        },
        "text_color": style_key_has_effect("text_color", html),
        "own_card_design": CARD_TPL_START in html,
        "generated_blocks": _has_generated_blocks(html),
        "custom_slots": find_custom_slots(html),
    }


# Welke placeholder hoort bij welk leesbaar feit? Alleen voor de UI; de agent
# krijgt de dict hierboven.
_PLACEHOLDER_LABELS = (
    ("{{HEADER_TITEL}}", "kop op de header"),
    ("{{HEADER_SUBTITEL}}", "ondertitel in de header"),
    ("{{HEADER_IMAGE_URL}}", "headerfoto"),
    ("{{HEADER_CTA_TEKST}}", "knop op de header"),
    ("{{INTRO_1}}", "eerste intro-alinea"),
    ("{{INTRO_2}}", "tweede intro-alinea"),
    ("{{HOOFD_CTA_TEKST}}", "hoofdknop"),
    ("{{SLOT_CTA_TEKST}}", "onderste knop"),
)


def capability_labels(html: str) -> list[str]:
    """Leesbare opsomming van wat deze template kan, voor de admin-UI.

    Zelfde bron als `template_capabilities`, zodat het schermbeeld nooit iets
    anders belooft dan wat de assistent te horen krijgt.
    """
    html = html or ""
    feiten = template_capabilities(html)
    labels = [naam for token, naam in _PLACEHOLDER_LABELS if token in html]

    if feiten["own_card_design"]:
        labels.append("eigen kaart-ontwerp (herhaalt per item)")
    elif feiten["generated_blocks"]:
        labels.append("blokken uit onze standaard-opmaak")

    knoppen = [naam for naam, actief in feiten["buttons"].items() if actief]
    if knoppen:
        vertaling = {"product": "blokknoppen", "hero": "headerknop", "cta": "onderste knop"}
        labels.append("kleur instelbaar: " + ", ".join(vertaling[k] for k in knoppen))
    if feiten["text_color"]:
        labels.append("tekstkleur instelbaar")
    if feiten["spacing_keys"]:
        labels.append(f"witruimte instelbaar ({len(feiten['spacing_keys'])} zones)")
    if feiten["custom_slots"]:
        labels.append(f"{len(feiten['custom_slots'])} eigen invulvakken")

    return labels or ["geen herkende invulplekken; deze template is nog niet tool-proof"]
