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

# Stijl-sleutels die de code-gegenereerde blokken (kaarten/banners/secties)
# zelf toepassen; die werken dus ook zonder token in de HTML.
_GENERATED_BLOCK_KEYS = frozenset({
    "accent", "card_bg", "card_border", "price_color", "badge_bg",
    "home_color", "away_color", "block_border", "button_bg", "button_text",
    "text_color", FONT_KEY,
})


def _has_generated_blocks(html: str) -> bool:
    return CARD_MARKER in html or BANNER_MARKER in html or SECTIONS_MARKER in html


def style_key_has_effect(key: str, html: str) -> bool:
    """Heeft deze stijl-sleutel ergens effect in deze template?"""
    token = _KEY_TOKENS.get(key) or ("{{STYLE_" + key.upper() + "}}")
    if token in html:
        return True
    generated = _has_generated_blocks(html)
    if key in _GENERATED_BLOCK_KEYS and (generated or CARD_TPL_START in html):
        # Eigen kaartblokken gebruiken tokens (dan ving de check hierboven het al),
        # maar de knop-/kaartkleuren gelden ook als terugval voor hero/cta.
        if generated:
            return True
    if key in ("hero_button_bg", "hero_button_text") and "{{HEADER_CTA}}" in html:
        return True  # de gegenereerde hero-knop gebruikt deze kleuren
    if key in ("cta_button_bg", "cta_button_text") and SECTIONS_MARKER in html:
        return True  # de sectie-knop gebruikt de CTA-kleuren
    if key in ("button_bg", "button_text"):
        # Via de terugval-keten kleuren hero-/cta-knoppen mee met de
        # productknop zolang die geen eigen kleur hebben.
        for volger in ("hero_button", "cta_button"):
            if style_key_has_effect(f"{volger}_bg", html):
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
