"""Tests voor de capability-laag: overal dezelfde aanpasbaarheid, en waar iets
echt niet kan is de weigering hard en eerlijk (nooit stil niets doen)."""

from __future__ import annotations

import pytest

from app.newsletter.capabilities import style_key_has_effect, template_capabilities
from app.newsletter.templates import load_template

MET_TOKENS = (
    "<html><body style='background:{{STYLE_PAGE_BG}}'>"
    "<p style='color:{{STYLE_TEXT_COLOR}};padding-top:{{STYLE_SPACING_BANNER_INTRO}}px'>{{INTRO_1}}</p>"
    "<td bgcolor='{{STYLE_BUTTON_BG}}'>x</td>"
    "</body></html>"
)
MET_GEGENEREERDE_BLOKKEN = "<html><body>{{INTRO_1}}<!-- ##BANNERS## -->{{HEADER_CTA}}</body></html>"
KALE = "<html><body><p>{{INTRO_1}}</p></body></html>"


def test_effect_via_token() -> None:
    assert style_key_has_effect("page_bg", MET_TOKENS)
    assert style_key_has_effect("text_color", MET_TOKENS)
    assert style_key_has_effect("button_bg", MET_TOKENS)
    assert not style_key_has_effect("footer_bg", MET_TOKENS)


def test_effect_via_generated_blocks() -> None:
    # Kaart-/knopkleuren werken ook zonder token: de code genereert de blokken.
    assert style_key_has_effect("button_bg", MET_GEGENEREERDE_BLOKKEN)
    assert style_key_has_effect("accent", MET_GEGENEREERDE_BLOKKEN)
    assert style_key_has_effect("hero_button_bg", MET_GEGENEREERDE_BLOKKEN)  # via {{HEADER_CTA}}
    assert style_key_has_effect("font_family", MET_GEGENEREERDE_BLOKKEN)
    # Maar pagina-achtergrond heeft zonder token nergens effect.
    assert not style_key_has_effect("page_bg", MET_GEGENEREERDE_BLOKKEN)


def test_kale_template_has_no_style_effect() -> None:
    for key in ("button_bg", "text_color", "page_bg", "hero_button_bg"):
        assert not style_key_has_effect(key, KALE)


def test_template_capabilities_shape() -> None:
    caps = template_capabilities(MET_TOKENS)
    assert caps["spacing_keys"] == ["spacing_banner_intro"]
    assert caps["buttons"]["product"] is True
    assert caps["own_card_design"] is False
    assert caps["custom_slots"] == []


def test_builtin_fallback_supports_everything() -> None:
    """Uniformiteits-eis: ook de fallback voor nieuwe klanten kan alles."""
    html = load_template("voetbalreizenxl-main")
    caps = template_capabilities(html)
    assert len(caps["spacing_keys"]) == 4  # alle vier de witruimte-zones
    assert caps["buttons"] == {"product": True, "hero": True, "cta": True}
    assert caps["text_color"] is True


def test_override_without_effect_is_rejected() -> None:
    from app.newsletter.tools import _apply_style_overrides

    brand = {"styles": {}}
    with pytest.raises(ValueError, match="nergens"):
        _apply_style_overrides(brand, KALE, {"button_bg": "#000000"})
    # Met gegenereerde blokken mag het wel (de code past de kleur toe).
    out = _apply_style_overrides(brand, MET_GEGENEREERDE_BLOKKEN, {"button_bg": "#000000"})
    assert out["styles"]["button_bg"] == "#000000"


def test_prompt_mentions_capabilities() -> None:
    from app.newsletter.prompts import build_system_prompt

    met_alles = build_system_prompt(template_info={
        "is_fallback": False, "name": "Magazine", "has_sections": False,
        "has_header_title": True,
        "capabilities": {
            "spacing_keys": ["spacing_banner_intro", "spacing_text_button"],
            "buttons": {"product": True, "hero": True, "cta": True},
            "text_color": True, "own_card_design": True,
            "generated_blocks": False,
            "custom_slots": ["ARTIKEL_TITEL", "QA_VRAAG_1"],
        },
    })
    assert "AANPASBAAR IN DEZE TEMPLATE" in met_alles
    assert "witruimte" in met_alles and "2 zones" in met_alles
    assert "EIGEN INVULVAKKEN" in met_alles and "ARTIKEL_TITEL" in met_alles
    assert "EIGEN kaart-ontwerp" in met_alles

    zonder_witruimte = build_system_prompt(template_info={
        "is_fallback": False, "name": "Kaal", "has_sections": False,
        "has_header_title": True,
        "capabilities": {
            "spacing_keys": [], "buttons": {"product": False, "hero": False, "cta": True},
            "text_color": False, "own_card_design": False,
            "generated_blocks": False, "custom_slots": [],
        },
    })
    assert "GEEN witruimte-aanpassing" in zonder_witruimte


def test_fallback_template_info_includes_capabilities(session) -> None:
    import uuid

    from app.services.conversation import _template_info

    info = _template_info(session, uuid.uuid4(), None)
    assert info["is_fallback"] is True
    assert len(info["capabilities"]["spacing_keys"]) == 4


def test_fallback_render_keeps_original_paddings(session, cipher) -> None:
    """De tokens in de fallback + de geïnjecteerde basis-styles = zelfde render."""
    import uuid

    from app.newsletter.tools import ToolContext, _resolve_template_html

    class _Tenant:
        id = uuid.uuid4()
        config = {"brand_name": "X"}

    ctx = ToolContext(session=session, tenant_id=_Tenant.id, cipher=cipher)
    html, brand = _resolve_template_html(ctx, _Tenant(), _Tenant.config)
    assert "{{STYLE_SPACING_BANNER_INTRO}}" in html
    assert brand["styles"]["spacing_banner_intro"] == 20  # origineel, niet de 80-default
    assert brand["styles"]["spacing_products_text"] == 0
